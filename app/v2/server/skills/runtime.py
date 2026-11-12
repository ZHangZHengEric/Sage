"""Skill catalog/source over immutable artifacts; the SDK owns materialization."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from sagents.v2.concurrency import bounded_to_thread
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.skill import (
    SkillBundle,
    SkillDescriptor,
)
from sagents.v2.contracts.skill_payload import files_digest
from sagents.v2.skill.search import SkillSearchIndex, searchable_body

from app.v2.server.skills.records import (
    SkillRecord,
    resolve_artifact_path,
)
from app.v2.server.skills.files import (
    inspect_skill_directory,
)


class CatalogSkillProvider:
    """Level-1 catalog + Level-2 source over immutable catalog artifacts."""

    def __init__(
        self, records: tuple[SkillRecord, ...], data_root: Path, *, latest_record=None,
        version_record=None, package_files=None, search_index=None,
        workspace_namespace: str | None = None, scoped_names: frozenset[str] = frozenset(),
    ) -> None:
        self._records = {item.name: item for item in records}
        self.data_root = Path(data_root)
        self._workspace_namespace = workspace_namespace
        self._scoped_names = scoped_names
        self.latest_record = latest_record
        self.version_record = version_record
        self._search_index = search_index if search_index is not None else SkillSearchIndex()
        self._bundles = {name: bundle for name, bundle in package_skill_bundles(package_files or {}).items()
                         if name not in self._records or not self._records[name].pinned}

    def _scoped(self, descriptor: SkillDescriptor) -> SkillDescriptor:
        if self._workspace_namespace is None or descriptor.name not in self._scoped_names:
            return descriptor
        return descriptor.model_copy(update={"metadata": {
            **descriptor.metadata, "workspace_namespace": self._workspace_namespace,
        }})

    async def list_skills(self, *, run_id: str) -> tuple[SkillDescriptor, ...]:
        descriptors = {name: _descriptor(item) for name, item in self._records.items()}
        descriptors.update({name: bundle.descriptor for name, bundle in self._bundles.items()})
        return tuple(self._scoped(descriptors[name]) for name in sorted(descriptors))

    async def get_skill(self, name: str, *, run_id: str) -> SkillDescriptor:
        if name in self._bundles:
            return self._scoped(self._bundles[name].descriptor)
        try:
            return self._scoped(_descriptor(self._records[name]))
        except KeyError as exc:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="skill.not_found",
                    category=ErrorCategory.VALIDATION,
                    message=f"skill {name!r} is not registered",
                    safe_to_resume=True,
                )
            ) from exc

    async def search_skills(self, query, *, run_id, allowed_names, limit):
        def search():
            documents = {}
            for name in allowed_names:
                if name in self._bundles:
                    bundle = self._bundles[name]
                    documents[f"package/{name}/{bundle.content_hash}"] = lambda bundle=bundle: (
                        bundle.descriptor, searchable_body(bundle.files["SKILL.md"])
                    )
                elif name in self._records:
                    record = self._records[name]
                    key = f"catalog/{record.artifact_path}/{record.package_sha256}"
                    documents[key] = lambda record=record: (
                        _descriptor(record), self._search_body(record)
                    )
            return self._search_index.search(query, documents, limit)

        return tuple(self._scoped(item) for item in await bounded_to_thread("skill-io", search))

    def _search_body(self, record):
        path = resolve_artifact_path(self.data_root, record.artifact_path) / "SKILL.md"
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > record.total_bytes:
                    raise ValueError("invalid Skill artifact file")
                content = stream.read(record.total_bytes + 1)
            if len(content) > record.total_bytes or hashlib.sha256(content).hexdigest() != record.skill_md_sha256:
                raise ValueError("SKILL.md hash differs from the frozen record")
        except (OSError, ValueError) as exc:
            raise SageV2Error(RuntimeErrorInfo(
                code="skill.artifact_changed",
                category=ErrorCategory.PROVIDER_PERMANENT,
                message=f"skill {record.name!r} artifact no longer matches its version",
                safe_to_resume=False,
            )) from exc
        return searchable_body(content)

    async def fetch(self, name: str, *, run_id: str) -> SkillBundle:
        descriptor = await self.get_skill(name, run_id=run_id)
        if name in self._bundles:
            return self._bundles[name].model_copy(update={"descriptor": descriptor})
        record = self._records[name]
        return await self._fetch_record(record, descriptor)

    async def fetch_latest(self, name: str, *, run_id: str) -> SkillBundle:
        if name in self._bundles:
            return await self.fetch(name, run_id=run_id)
        await self.get_skill(name, run_id=run_id)
        admitted = self._records[name]
        record = await self.latest_record(admitted) if self.latest_record is not None else admitted
        if (record.skill_id, record.name, record.owner_user_id, record.status) != (
            admitted.skill_id, admitted.name, admitted.owner_user_id, "active",
        ):
            raise SageV2Error(RuntimeErrorInfo(code="skill.not_found", category=ErrorCategory.POLICY_DENIED,
                message="Current Skill no longer matches this Run's admitted identity", safe_to_resume=True))
        if admitted.pinned:
            record = admitted
        return await self._fetch_record(record, self._scoped(_descriptor(record)))

    async def fetch_for_restore(self, name: str, *, run_id: str, version: str) -> SkillBundle:
        admitted = await self.get_skill(name, run_id=run_id)
        if version == admitted.version:
            return await self.fetch(name, run_id=run_id)
        record = self._records.get(name)
        historic = None
        if record is not None and not record.pinned and self.version_record is not None:
            historic = await self.version_record(version)
        if historic is None or (historic.skill_id, historic.owner_user_id, historic.name, historic.version_id) != (
            record.skill_id, record.owner_user_id, record.name, version,
        ):
            raise SageV2Error(RuntimeErrorInfo(
                code="skill.restore_version_changed", category=ErrorCategory.PROVIDER_PERMANENT,
                message=f"Accepted Skill version is unavailable for {name!r}", safe_to_resume=False,
            ))
        return await self._fetch_record(historic, self._scoped(_descriptor(historic)))

    async def _fetch_record(self, record, descriptor):
        name = record.name
        package = await bounded_to_thread(
            "skill-io",
            lambda: inspect_skill_directory(
                resolve_artifact_path(self.data_root, record.artifact_path)
            ),
        )
        if package.package_sha256 != record.package_sha256:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="skill.artifact_changed",
                    category=ErrorCategory.PROVIDER_PERMANENT,
                    message=f"skill {name!r} artifact no longer matches its version",
                    safe_to_resume=False,
                )
            )
        return SkillBundle(
            descriptor=descriptor,
            files=package.files,
            content_hash=package.package_sha256,
        )


def package_skill_bundles(files):
    """Package resources override catalog sources without publishing globally."""
    from sagents.v2.optimization.package_workspace import validate_skill_metadata

    bundles = {}
    for path, instructions in files.items():
        parts = path.split("/")
        if len(parts) != 3 or parts[0] != "skills" or parts[2] != "SKILL.md":
            continue
        name = parts[1]
        validate_skill_metadata(path, instructions)
        lines = instructions.splitlines()
        description = next((line.strip() for line in lines if line.strip()), "")
        if lines and lines[0].strip() == "---":
            from sagents.v2.package.strict_yaml import load_unique_yaml
            end = next(i for i in range(1, len(lines)) if lines[i].strip() in {"---", "..."})
            description = load_unique_yaml("\n".join(lines[1:end]))["description"]
        prefix = f"skills/{name}/"
        contents = {key[len(prefix):]: value.encode("utf-8") for key, value in files.items() if key.startswith(prefix)}
        digest = files_digest(contents)
        bundles[name] = SkillBundle(descriptor=SkillDescriptor(name=name, description=description,
            source_id="agent-package", version=digest), files=contents, content_hash=digest)
    return bundles


def package_files_for_agent(bundle, agent_id):
    """Resolve files using the same compiled aliases as the Agent graph."""
    if agent_id is None or agent_id in bundle.manifest.agents or agent_id == bundle.manifest.metadata.id:
        return bundle.files
    for alias, child in bundle.dependencies.items():
        if agent_id == alias:
            return child.files
        if agent_id.startswith(alias + "."):
            files = package_files_for_agent(child, agent_id[len(alias) + 1:])
            if files is not None:
                return files
    return None


def enabled_skill_names(records, package):
    bundled = package_skill_bundles(package.files)
    selected = {name for definition in package.manifest.agents.values() for name in definition.skills}
    return tuple(dict.fromkeys([*(record.name for record in records), *(name for name in sorted(bundled) if name in selected)]))


def _descriptor(record: SkillRecord) -> SkillDescriptor:
    return SkillDescriptor(
        name=record.name,
        description=record.description,
        source_id="catalog",
        version=record.version_id,
        metadata={
            "skill_id": record.skill_id,
            "artifact_path": record.artifact_path,
        },
    )

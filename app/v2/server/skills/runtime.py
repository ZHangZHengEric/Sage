"""Skill catalog/source over immutable artifacts; the SDK owns materialization."""

from __future__ import annotations

from pathlib import Path

from sagents.v2.concurrency import bounded_to_thread
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.skill import (
    SkillBundle,
    SkillDescriptor,
)
from sagents.v2.contracts.skill_payload import files_digest

from app.v2.server.skills.records import (
    SkillRecord,
    resolve_artifact_path,
)
from app.v2.server.skills.files import (
    inspect_skill_directory,
)


class CatalogSkillProvider:
    """Level-1 catalog + Level-2 source over immutable catalog artifacts."""

    def __init__(self, records: tuple[SkillRecord, ...], data_root: Path, *, latest_record=None, package_files=None) -> None:
        self._records = {item.name: item for item in records}
        self.data_root = Path(data_root)
        self.latest_record = latest_record
        self._bundles = package_skill_bundles(package_files or {})

    async def list_skills(self, *, run_id: str) -> tuple[SkillDescriptor, ...]:
        descriptors = {name: _descriptor(item) for name, item in self._records.items()}
        descriptors.update({name: bundle.descriptor for name, bundle in self._bundles.items()})
        return tuple(descriptors[name] for name in sorted(descriptors))

    async def get_skill(self, name: str, *, run_id: str) -> SkillDescriptor:
        if name in self._bundles:
            return self._bundles[name].descriptor
        try:
            return _descriptor(self._records[name])
        except KeyError as exc:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="skill.not_found",
                    category=ErrorCategory.VALIDATION,
                    message=f"skill {name!r} is not registered",
                    safe_to_resume=True,
                )
            ) from exc

    async def fetch(self, name: str, *, run_id: str) -> SkillBundle:
        if name in self._bundles:
            return self._bundles[name]
        descriptor = await self.get_skill(name, run_id=run_id)
        record = self._records[name]
        return await self._fetch_record(record, descriptor)

    async def fetch_latest(self, name: str, *, run_id: str) -> SkillBundle:
        if name in self._bundles:
            return self._bundles[name]
        await self.get_skill(name, run_id=run_id)
        admitted = self._records[name]
        record = await self.latest_record(admitted) if self.latest_record is not None else admitted
        if (record.skill_id, record.name, record.owner_user_id, record.status) != (
            admitted.skill_id, admitted.name, admitted.owner_user_id, "active",
        ):
            raise SageV2Error(RuntimeErrorInfo(code="skill.not_found", category=ErrorCategory.POLICY_DENIED,
                message="Current Skill no longer matches this Run's admitted identity", safe_to_resume=True))
        return await self._fetch_record(record, _descriptor(record))

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

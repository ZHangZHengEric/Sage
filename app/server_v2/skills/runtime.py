"""sagents/v2 Skill ports backed by the Server catalog.

Listing never copies. ``load_skill`` prefers an edited tenant Skill and otherwise
materializes one content-addressed bundle inside the sandbox-visible workspace.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import AsyncExitStack
from pathlib import Path, PurePosixPath

from sagents.v2._concurrency import bounded_to_thread
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.principals import RequestContext
from sagents.v2.skill import (
    SkillBundle,
    SkillDescriptor,
)

from app.server_v2.runtime.loop import compose_catalog_loop
from app.server_v2.skills.records import (
    SkillPackage,
    SkillRecord,
    resolve_artifact_path,
    workspace_skill_path,
)
from app.server_v2.skills.files import (
    inspect_skill_directory,
    package_sha256_of,
    write_skill_package,
)


class CatalogSkillProvider:
    """Level-1 catalog + Level-2 source over immutable catalog artifacts."""

    def __init__(self, records: tuple[SkillRecord, ...], data_root: Path) -> None:
        self._records = {item.name: item for item in records}
        self.data_root = Path(data_root)

    async def list_skills(self, *, run_id: str) -> tuple[SkillDescriptor, ...]:
        del run_id
        return tuple(
            _descriptor(item)
            for item in sorted(self._records.values(), key=lambda value: value.name)
        )

    async def get_skill(self, name: str, *, run_id: str) -> SkillDescriptor:
        del run_id
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
        descriptor = await self.get_skill(name, run_id=run_id)
        record = self._records[name]
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


class ReadThroughSkillWorkspace:
    """Expose edited Skills or lazily materialize immutable versions in /workspace."""

    def __init__(
        self, data_root: Path, user_id: str, records: tuple[SkillRecord, ...]
    ) -> None:
        self.data_root = Path(data_root)
        self.user_id = user_id
        self._records = {item.name: item for item in records}

    async def materialize(
        self, bundle: SkillBundle, *, run_id: str, destination: str
    ) -> str:
        del run_id
        name = bundle.descriptor.name
        workspace = workspace_skill_path(self.data_root, self.user_id, name)
        if workspace.is_dir():
            return destination
        record = self._records.get(name)
        if record is None:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="skill.not_found",
                    category=ErrorCategory.PROVIDER_PERMANENT,
                    message=f"skill {name!r} was not admitted for this run",
                    safe_to_resume=False,
                )
            )
        cache_key = hashlib.sha256(bundle.content_hash.encode()).hexdigest()
        host_cache = workspace.parent / ".catalog" / name / cache_key
        wire_cache = (
            PurePosixPath(destination).parent / ".catalog" / name / cache_key
        ).as_posix()
        if host_cache.is_dir():
            current_hash = await bounded_to_thread(
                "skill-io", lambda: package_sha256_of(host_cache)
            )
            if current_hash != bundle.content_hash:
                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="skill.workspace_cache_changed",
                        category=ErrorCategory.CONFLICT,
                        message=f"materialized cache for skill {name!r} was modified",
                        safe_to_resume=True,
                    )
                )
            return wire_cache
        files = dict(bundle.files)
        files[".materialized-skill.json"] = json.dumps(
            {
                "name": name,
                "version": bundle.descriptor.version,
                "content_hash": bundle.content_hash,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        package = SkillPackage(
            name=name,
            description=bundle.descriptor.description,
            files=files,
            skill_md_sha256=(
                f"sha256:{hashlib.sha256(bundle.files['SKILL.md']).hexdigest()}"
            ),
            package_sha256=bundle.content_hash,
            file_count=len(bundle.files),
            total_bytes=sum(len(value) for value in bundle.files.values()),
        )
        try:
            await bounded_to_thread(
                "skill-io", lambda: write_skill_package(host_cache, package)
            )
        except SageV2Error as exc:
            if exc.info.category != ErrorCategory.CONFLICT or not host_cache.is_dir():
                raise
        current_hash = await bounded_to_thread(
            "skill-io", lambda: package_sha256_of(host_cache)
        )
        if current_hash != bundle.content_hash:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="skill.workspace_cache_changed",
                    category=ErrorCategory.CONFLICT,
                    message=f"materialized cache for skill {name!r} is invalid",
                    safe_to_resume=True,
                )
            )
        return wire_cache


class CatalogRunDriver:
    """Load the catalog Agent, then materialize a sagents/v2 loop for this run."""

    def __init__(self, service, run_id: str) -> None:
        self.service = service
        self.run_id = run_id
        self._driver = None
        self._ports = None

    async def _resolve(self, context: RequestContext):
        if self._driver is not None:
            return self._driver
        runtime = self.service.application.entrypoint().runtime
        command = await runtime.session_store.get_start_command(self.run_id)
        self._driver, self._ports = await compose_catalog_loop(
            self.service,
            command,
            user_id=context.actor.principal_id,
        )
        return self._driver

    async def execute(self, run_id: str, context: RequestContext):
        try:
            return await (await self._resolve(context)).execute(run_id, context)
        finally:
            await self._close_ports()

    async def resume(self, run_id: str, context: RequestContext):
        try:
            return await (await self._resolve(context)).resume(run_id, context)
        finally:
            await self._close_ports()

    async def _close_ports(self) -> None:
        ports = self._ports
        self._ports = None
        if ports is None:
            return
        async with AsyncExitStack() as stack:
            for handle in ports.scope_handles:
                closer = getattr(handle, "close", None)
                if closer is not None:
                    stack.push_async_callback(closer)


def _descriptor(record: SkillRecord) -> SkillDescriptor:
    return SkillDescriptor(
        name=record.name,
        description=record.description,
        source_id="catalog",
        version=record.version_id,
        metadata={
            "skill_id": record.skill_id,
            "dimension": record.dimension,
            "artifact_path": record.artifact_path,
        },
    )

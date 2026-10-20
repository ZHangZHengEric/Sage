"""Skill catalog/source over immutable artifacts; the SDK owns materialization."""

from __future__ import annotations

from pathlib import Path

from sagents.v2.concurrency import bounded_to_thread
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.skill import (
    SkillBundle,
    SkillDescriptor,
)

from app.v2.server.skills.records import (
    SkillRecord,
    resolve_artifact_path,
)
from app.v2.server.skills.files import (
    inspect_skill_directory,
)


class CatalogSkillProvider:
    """Level-1 catalog + Level-2 source over immutable catalog artifacts."""

    def __init__(self, records: tuple[SkillRecord, ...], data_root: Path) -> None:
        self._records = {item.name: item for item in records}
        self.data_root = Path(data_root)

    async def list_skills(self, *, run_id: str) -> tuple[SkillDescriptor, ...]:
        return tuple(
            _descriptor(item)
            for item in sorted(self._records.values(), key=lambda value: value.name)
        )

    async def get_skill(self, name: str, *, run_id: str) -> SkillDescriptor:
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

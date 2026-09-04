from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy import select

from app.server_v2.core.database import Database
from app.server_v2.db.models import AgentSkillSelectionRow, SkillRow, SkillVersionRow
from app.server_v2.domain.skills import (
    AgentSkillBinding,
    SkillDimension,
    SkillRecord,
    normalize_skill_name,
    reject_absolute_artifact_path,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SkillStore(Protocol):
    async def get(self, skill_id: str) -> SkillRecord | None: ...
    async def list_visible(
        self, *, user_id: str, role: str, dimension: SkillDimension | None = None
    ) -> list[SkillRecord]: ...
    async def publish(self, record: SkillRecord) -> SkillRecord: ...
    async def disable(self, skill_id: str) -> None: ...
    async def replace_bindings(
        self,
        *,
        owner_user_id: str,
        agent_id: str,
        bindings: list[AgentSkillBinding],
    ) -> None: ...
    async def list_bindings(
        self, *, owner_user_id: str, agent_id: str
    ) -> list[AgentSkillBinding]: ...


class DatabaseSkillStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def get(self, skill_id: str) -> SkillRecord | None:
        async with self.database.session() as session:
            row = await session.get(SkillRow, skill_id)
            if row is None or not row.current_version_id:
                return None
            version = await session.get(SkillVersionRow, row.current_version_id)
        if version is None:
            return None
        return _record(row, version)

    async def list_visible(
        self, *, user_id: str, role: str, dimension: SkillDimension | None = None
    ) -> list[SkillRecord]:
        async with self.database.session() as session:
            rows = list((await session.execute(select(SkillRow))).scalars().all())
            versions = {
                row.version_id: row
                for row in (await session.execute(select(SkillVersionRow))).scalars().all()
            }
        records = [
            _record(row, versions[row.current_version_id])
            for row in rows
            if row.current_version_id in versions
        ]
        return [
            item
            for item in records
            if _visible(item, user_id=user_id, role=role, dimension=dimension)
        ]

    async def publish(self, record: SkillRecord) -> SkillRecord:
        reject_absolute_artifact_path(record.artifact_path)
        now = _now()
        skill_id = record.skill_id
        async with self.database.transaction() as session:
            existing = (
                await session.execute(
                    select(SkillRow).where(
                        SkillRow.dimension == record.dimension,
                        SkillRow.owner_user_id == record.owner_user_id,
                        SkillRow.name == record.name,
                    )
                )
            ).scalars().first()
            if existing is None:
                session.add(
                    SkillRow(
                        skill_id=record.skill_id,
                        dimension=record.dimension,
                        owner_user_id=record.owner_user_id,
                        name=record.name,
                        description=record.description,
                        current_version_id=record.version_id,
                        status="active",
                        created_at=now,
                        updated_at=now,
                    )
                )
            else:
                existing.description = record.description
                existing.current_version_id = record.version_id
                existing.status = "active"
                existing.updated_at = now
                skill_id = existing.skill_id
            session.add(
                SkillVersionRow(
                    version_id=record.version_id,
                    skill_id=skill_id,
                    revision=record.revision,
                    artifact_path=record.artifact_path,
                    skill_md_sha256=record.skill_md_sha256,
                    package_sha256=record.package_sha256,
                    file_count=record.file_count,
                    total_bytes=record.total_bytes,
                    created_at=now,
                )
            )
        saved = await self.get(skill_id)
        assert saved is not None
        return saved

    async def disable(self, skill_id: str) -> None:
        async with self.database.transaction() as session:
            row = await session.get(SkillRow, skill_id)
            if row is None:
                return
            row.status = "disabled"
            row.updated_at = _now()

    async def replace_bindings(
        self,
        *,
        owner_user_id: str,
        agent_id: str,
        bindings: list[AgentSkillBinding],
    ) -> None:
        async with self.database.transaction() as session:
            current = (
                await session.execute(
                    select(AgentSkillSelectionRow).where(
                        AgentSkillSelectionRow.owner_user_id == owner_user_id,
                        AgentSkillSelectionRow.agent_id == agent_id,
                    )
                )
            ).scalars().all()
            for row in current:
                await session.delete(row)
            for binding in bindings:
                session.add(
                    AgentSkillSelectionRow(
                        owner_user_id=owner_user_id,
                        agent_id=agent_id,
                        skill_name=normalize_skill_name(binding.skill_name),
                        source_skill_id=binding.source_skill_id or "",
                        position=binding.position,
                    )
                )

    async def list_bindings(
        self, *, owner_user_id: str, agent_id: str
    ) -> list[AgentSkillBinding]:
        async with self.database.session() as session:
            rows = (
                await session.execute(
                    select(AgentSkillSelectionRow).where(
                        AgentSkillSelectionRow.owner_user_id == owner_user_id,
                        AgentSkillSelectionRow.agent_id == agent_id,
                    )
                )
            ).scalars().all()
        return [
            AgentSkillBinding(
                owner_user_id=row.owner_user_id,
                agent_id=row.agent_id,
                skill_name=row.skill_name,
                source_skill_id=row.source_skill_id or None,
                position=row.position,
            )
            for row in sorted(rows, key=lambda item: item.position)
        ]


def _visible(
    item: SkillRecord,
    *,
    user_id: str,
    role: str,
    dimension: SkillDimension | None,
) -> bool:
    if item.status != "active":
        return False
    if dimension is not None and item.dimension != dimension:
        return False
    if item.dimension == "system":
        return True
    if item.owner_user_id == user_id:
        return True
    return role == "admin"


def _record(row: SkillRow, version: SkillVersionRow) -> SkillRecord:
    return SkillRecord(
        skill_id=row.skill_id,
        version_id=version.version_id,
        revision=version.revision,
        dimension=row.dimension,  # type: ignore[arg-type]
        owner_user_id=row.owner_user_id,
        name=row.name,
        description=row.description,
        artifact_path=version.artifact_path,
        skill_md_sha256=version.skill_md_sha256,
        package_sha256=version.package_sha256,
        file_count=version.file_count,
        total_bytes=version.total_bytes,
        status=row.status,
    )


class MemorySkillStore:
    def __init__(self) -> None:
        self._skills: dict[str, SkillRecord] = {}
        self._bindings: dict[tuple[str, str], list[AgentSkillBinding]] = {}

    async def get(self, skill_id: str) -> SkillRecord | None:
        return self._skills.get(skill_id)

    async def list_visible(
        self, *, user_id: str, role: str, dimension: SkillDimension | None = None
    ) -> list[SkillRecord]:
        return [
            item
            for item in self._skills.values()
            if item.status == "active"
            and (dimension is None or item.dimension == dimension)
            and (
                item.dimension == "system"
                or item.owner_user_id == user_id
                or role == "admin"
            )
        ]

    async def publish(self, record: SkillRecord) -> SkillRecord:
        reject_absolute_artifact_path(record.artifact_path)
        current = next(
            (
                item
                for item in self._skills.values()
                if item.dimension == record.dimension
                and item.owner_user_id == record.owner_user_id
                and item.name == record.name
            ),
            None,
        )
        stored = record
        if current is not None and current.skill_id != record.skill_id:
            stored = SkillRecord(
                skill_id=current.skill_id,
                version_id=record.version_id,
                revision=record.revision,
                dimension=record.dimension,
                owner_user_id=record.owner_user_id,
                name=record.name,
                description=record.description,
                artifact_path=record.artifact_path,
                skill_md_sha256=record.skill_md_sha256,
                package_sha256=record.package_sha256,
                file_count=record.file_count,
                total_bytes=record.total_bytes,
                status="active",
            )
            self._skills.pop(current.skill_id, None)
        self._skills[stored.skill_id] = stored
        return stored

    async def disable(self, skill_id: str) -> None:
        current = self._skills.get(skill_id)
        if current is None:
            return
        self._skills[skill_id] = SkillRecord(
            skill_id=current.skill_id,
            version_id=current.version_id,
            revision=current.revision,
            dimension=current.dimension,
            owner_user_id=current.owner_user_id,
            name=current.name,
            description=current.description,
            artifact_path=current.artifact_path,
            skill_md_sha256=current.skill_md_sha256,
            package_sha256=current.package_sha256,
            file_count=current.file_count,
            total_bytes=current.total_bytes,
            status="disabled",
        )

    async def replace_bindings(
        self,
        *,
        owner_user_id: str,
        agent_id: str,
        bindings: list[AgentSkillBinding],
    ) -> None:
        self._bindings[(owner_user_id, agent_id)] = [
            AgentSkillBinding(
                owner_user_id=owner_user_id,
                agent_id=agent_id,
                skill_name=normalize_skill_name(item.skill_name),
                source_skill_id=item.source_skill_id,
                position=item.position,
            )
            for item in bindings
        ]

    async def list_bindings(
        self, *, owner_user_id: str, agent_id: str
    ) -> list[AgentSkillBinding]:
        return list(self._bindings.get((owner_user_id, agent_id), ()))

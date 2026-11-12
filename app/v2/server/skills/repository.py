from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from dataclasses import replace
from typing import Protocol, cast

from sqlalchemy import CursorResult, select, text, update
from sqlalchemy.exc import IntegrityError

from app.v2.server.database import Database
from app.v2.server.skills.orm import AgentSkillSelectionRow, SkillRow, SkillVersionRow
from app.v2.server.skills.downloads import import_error
from app.v2.server.skills.records import (
    AgentSkillBinding,
    SkillRecord,
    normalize_skill_name,
    reject_absolute_artifact_path,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SkillStore(Protocol):
    async def get(self, skill_id: str) -> SkillRecord | None: ...
    async def get_versions(self, version_ids: list[str]) -> list[SkillRecord]: ...
    async def list_versions(self, skill_id: str, *, limit: int = 50, before_revision: int | None = None) -> list[SkillRecord]: ...
    async def list_visible(self, *, user_id: str, role: str) -> list[SkillRecord]: ...
    async def publish(self, record: SkillRecord, *, expected_version_id: str | None = None) -> SkillRecord: ...
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

    async def get_versions(self, version_ids: list[str]) -> list[SkillRecord]:
        if not version_ids:
            return []
        async with self.database.session() as session:
            rows = (await session.execute(select(SkillRow, SkillVersionRow).join(
                SkillVersionRow, SkillVersionRow.skill_id == SkillRow.skill_id
            ).where(SkillVersionRow.version_id.in_(version_ids)))).all()
        return [_record(row, version) for row, version in rows]

    async def list_versions(self, skill_id: str, *, limit: int = 50, before_revision: int | None = None) -> list[SkillRecord]:
        statement = select(SkillRow, SkillVersionRow).join(
            SkillVersionRow, SkillVersionRow.skill_id == SkillRow.skill_id
        ).where(SkillRow.skill_id == skill_id)
        if before_revision is not None:
            statement = statement.where(SkillVersionRow.revision < before_revision)
        async with self.database.session() as session:
            rows = (await session.execute(statement.order_by(
                SkillVersionRow.revision.desc(), SkillVersionRow.created_at.desc()
            ).limit(limit))).all()
        return [_record(row, version) for row, version in rows]

    async def list_visible(self, *, user_id: str, role: str) -> list[SkillRecord]:
        # Visibility is a WHERE clause, not a full scan: this runs on every chat
        # turn, so it must stay proportional to the caller's own Skills.
        statement = (
            select(SkillRow, SkillVersionRow)
            .join(
                SkillVersionRow,
                SkillRow.current_version_id == SkillVersionRow.version_id,
            )
            .where(SkillRow.status == "active")
        )
        if role != "admin":
            statement = statement.where(SkillRow.owner_user_id == user_id)
        async with self.database.session() as session:
            rows = (await session.execute(statement)).all()
        return [_record(row, version) for row, version in rows]

    async def publish(self, record: SkillRecord, *, expected_version_id: str | None = None) -> SkillRecord:
        try:
            return await self._publish(record, expected_version_id=expected_version_id)
        except IntegrityError as exc:
            if expected_version_id is None:
                raise
            raise import_error("技能已被其他操作更新，请重新预览", conflict=True) from exc

    async def _publish(self, record: SkillRecord, *, expected_version_id: str | None) -> SkillRecord:
        reject_absolute_artifact_path(record.artifact_path)
        now = _now()
        skill_id = record.skill_id
        revision = record.revision
        async with self.database.transaction() as session:
            existing = (
                (
                    await session.execute(
                        select(SkillRow).where(
                            SkillRow.owner_user_id == record.owner_user_id,
                            SkillRow.name == record.name,
                        ).with_for_update()
                    )
                )
                .scalars()
                .first()
            )
            current_version = existing.current_version_id if existing and existing.status == "active" else ""
            if existing is not None:
                previous = await session.get(SkillVersionRow, existing.current_version_id)
                if previous is not None:
                    revision = previous.revision + 1
            if expected_version_id is not None and current_version != expected_version_id:
                raise import_error("技能已被其他操作更新，请重新预览", conflict=True)
            if existing is None:
                session.add(
                    SkillRow(
                        skill_id=record.skill_id,
                        owner_user_id=record.owner_user_id,
                        name=record.name,
                        description=record.description,
                        current_version_id=record.version_id,
                        status="active",
                        created_at=now,
                        updated_at=now,
                    )
                )
            elif expected_version_id is not None:
                changed = await session.execute(
                    update(SkillRow).where(
                        SkillRow.skill_id == existing.skill_id,
                        SkillRow.current_version_id == existing.current_version_id,
                        SkillRow.status == existing.status,
                    ).values(description=record.description, current_version_id=record.version_id,
                             status="active", updated_at=now)
                    .execution_options(synchronize_session=False)
                )
                if cast(CursorResult, changed).rowcount != 1:
                    raise import_error("技能已被其他操作更新，请重新预览", conflict=True)
                skill_id = existing.skill_id
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
                    revision=revision,
                    description=record.description,
                    artifact_path=record.artifact_path,
                    skill_md_sha256=record.skill_md_sha256,
                    package_sha256=record.package_sha256,
                    file_count=record.file_count,
                    total_bytes=record.total_bytes,
                    created_at=now,
                )
            )
        return replace(record, skill_id=skill_id, revision=revision, created_at=now)

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
        skill_visibility: dict | None = None,
        configured_names: list[str] | None = None,
        agent_record=None,
        expected_package_ref: str | None = None,
    ) -> None:
        from app.v2.server.catalog.orm import AgentRow
        from app.v2.server.catalog.repository import DatabaseCatalogStore, _agent_record, _agent_values, require_current_package
        from app.v2.server.catalog.packages import package_owner
        from sagents.v2.agent.management import AgentPackageBundle

        async with self.database.transaction() as session:
            if session.get_bind().dialect.name == "sqlite":
                await session.execute(text("BEGIN IMMEDIATE"))
            agent = await session.get(AgentRow, agent_id, with_for_update=True)
            if agent is not None and agent.owner_user_id != owner_user_id:
                raise ValueError("Skill binding owner does not match Agent")
            store = DatabaseCatalogStore(self.database)
            creating = agent_record is not None and expected_package_ref is None
            if creating:
                if agent is not None:
                    raise ValueError("catalog Agent already exists")
                await store._catalog(session, owner_user_id)
                session.add(await store._new_agent_row(session, owner_user_id, agent_record))
            elif agent is None and (skill_visibility is not None or agent_record is not None):
                raise ValueError("catalog Agent is missing")
            if agent is not None:
                require_current_package(agent.package_ref, expected_package_ref)
            current = (
                (
                    await session.execute(
                        select(AgentSkillSelectionRow).where(
                            AgentSkillSelectionRow.owner_user_id == owner_user_id,
                            AgentSkillSelectionRow.agent_id == agent_id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            pins = {(row.skill_name, row.source_skill_id): row.source_version_id for row in current}
            for row in current:
                await session.delete(row)
            for binding in bindings:
                source_version = (
                    pins.get((binding.skill_name, binding.source_skill_id or ""))
                    if skill_visibility is not None or agent_record is not None
                    else binding.source_version_id
                )
                session.add(
                    AgentSkillSelectionRow(
                        owner_user_id=owner_user_id,
                        agent_id=agent_id,
                        skill_name=normalize_skill_name(binding.skill_name),
                        source_skill_id=binding.source_skill_id or "",
                        position=binding.position,
                        source_version_id=source_version,
                    )
                )
            # Binding index and canonical package must commit or roll back together.
            if agent is not None:
                if agent_record is not None:
                    agent.package_ref = await store.packages.save_in_transaction(
                        session, package_owner(owner_user_id), agent_record.package,
                    )
                    for field, value in _agent_values(agent_record).items():
                        setattr(agent, field, value)
                    return
                package_row = await store.packages._get(session, package_owner(owner_user_id), "bundle", agent.package_ref) if agent.package_ref else None
                if package_row is None:
                    raise ValueError("catalog Agent package is missing")
                package = AgentPackageBundle.model_validate(package_row.payload)
                if package.content_hash != agent.package_ref:
                    raise ValueError("catalog Agent package hash mismatch")
                record = _agent_record(agent, package=package)
                record = record.with_configuration(
                    skills=(configured_names if configured_names is not None else
                            [normalize_skill_name(binding.skill_name) for binding in bindings]),
                    skill_visibility=skill_visibility,
                )
                agent.package_ref = await store.packages.save_in_transaction(session, package_owner(owner_user_id), record.package)
                for field, value in _agent_values(record).items():
                    setattr(agent, field, value)


    async def set_binding_version(self, *, owner_user_id: str, agent_id: str, skill_id: str,
                                  version_id: str | None) -> bool:
        from app.v2.server.catalog.orm import AgentRow

        async with self.database.transaction() as session:
            if session.get_bind().dialect.name == "sqlite":
                await session.execute(text("BEGIN IMMEDIATE"))
            agent = await session.get(AgentRow, agent_id, with_for_update=True)
            if agent is not None and agent.owner_user_id != owner_user_id:
                return False
            result = await session.execute(update(AgentSkillSelectionRow).where(
                AgentSkillSelectionRow.owner_user_id == owner_user_id,
                AgentSkillSelectionRow.agent_id == agent_id,
                AgentSkillSelectionRow.source_skill_id == skill_id,
            ).values(source_version_id=version_id))
            return cast(CursorResult, result).rowcount > 0

    async def list_bindings(
        self, *, owner_user_id: str, agent_id: str
    ) -> list[AgentSkillBinding]:
        async with self.database.session() as session:
            rows = (
                (
                    await session.execute(
                        select(AgentSkillSelectionRow).where(
                            AgentSkillSelectionRow.owner_user_id == owner_user_id,
                            AgentSkillSelectionRow.agent_id == agent_id,
                        )
                    )
                )
                .scalars()
                .all()
            )
        return [
            AgentSkillBinding(
                owner_user_id=row.owner_user_id,
                agent_id=row.agent_id,
                skill_name=row.skill_name,
                source_skill_id=row.source_skill_id or None,
                position=row.position,
                source_version_id=row.source_version_id,
            )
            for row in sorted(rows, key=lambda item: item.position)
        ]


def _record(row: SkillRow, version: SkillVersionRow) -> SkillRecord:
    return SkillRecord(
        skill_id=row.skill_id,
        version_id=version.version_id,
        revision=version.revision,
        owner_user_id=row.owner_user_id,
        name=row.name,
        description=version.description if version.description is not None else (
            row.description if version.version_id == row.current_version_id else ""),
        artifact_path=version.artifact_path,
        skill_md_sha256=version.skill_md_sha256,
        package_sha256=version.package_sha256,
        file_count=version.file_count,
        total_bytes=version.total_bytes,
        status=row.status,
        created_at=version.created_at,
    )


class MemorySkillStore:
    def __init__(self) -> None:
        self._skills: dict[str, SkillRecord] = {}
        self._versions: dict[str, SkillRecord] = {}
        self._bindings: dict[tuple[str, str], list[AgentSkillBinding]] = {}

    async def get(self, skill_id: str) -> SkillRecord | None:
        return self._skills.get(skill_id)

    async def get_versions(self, version_ids: list[str]) -> list[SkillRecord]:
        return [replace(self._versions[version], status=self._skills[self._versions[version].skill_id].status)
                for version in version_ids if version in self._versions]

    async def list_versions(self, skill_id: str, *, limit: int = 50, before_revision: int | None = None) -> list[SkillRecord]:
        return sorted((item for item in self._versions.values() if item.skill_id == skill_id
            and (before_revision is None or item.revision < before_revision)),
            key=lambda item: item.revision, reverse=True)[:limit]

    async def list_visible(self, *, user_id: str, role: str) -> list[SkillRecord]:
        return [
            item
            for item in self._skills.values()
            if item.status == "active"
            and (item.owner_user_id == user_id or role == "admin")
        ]

    async def publish(self, record: SkillRecord, *, expected_version_id: str | None = None) -> SkillRecord:
        reject_absolute_artifact_path(record.artifact_path)
        current = next(
            (
                item
                for item in self._skills.values()
                if item.owner_user_id == record.owner_user_id
                and item.name == record.name
            ),
            None,
        )
        current_version = current.version_id if current and current.status == "active" else ""
        if expected_version_id is not None and current_version != expected_version_id:
            raise import_error("技能已被其他操作更新，请重新预览", conflict=True)
        stored = record
        if current is not None and current.skill_id != record.skill_id:
            stored = SkillRecord(
                skill_id=current.skill_id,
                version_id=record.version_id,
                revision=record.revision,
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
        stored = replace(stored, created_at=stored.created_at or _now(),
            revision=current.revision + 1 if current and current.version_id != stored.version_id else stored.revision)
        self._skills[stored.skill_id] = stored
        self._versions[stored.version_id] = stored
        return stored

    async def disable(self, skill_id: str) -> None:
        current = self._skills.get(skill_id)
        if current is None:
            return
        self._skills[skill_id] = SkillRecord(
            skill_id=current.skill_id,
            version_id=current.version_id,
            revision=current.revision,
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
        before_commit: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        validated = [
            AgentSkillBinding(
                owner_user_id=owner_user_id,
                agent_id=agent_id,
                skill_name=normalize_skill_name(item.skill_name),
                source_skill_id=item.source_skill_id,
                position=item.position,
                source_version_id=item.source_version_id,
            )
            for item in bindings
        ]
        key = (owner_user_id, agent_id)
        if before_commit is not None:
            await before_commit()
            pins = {(item.skill_name, item.source_skill_id): item.source_version_id
                    for item in self._bindings.get(key, ())}
            validated = [
                replace(item, source_version_id=pins.get((item.skill_name, item.source_skill_id)))
                for item in validated
            ]
        self._bindings[key] = validated

    async def set_binding_version(self, *, owner_user_id: str, agent_id: str, skill_id: str,
                                  version_id: str | None) -> bool:
        key = (owner_user_id, agent_id)
        current = self._bindings.get(key, ())
        if not any(item.source_skill_id == skill_id for item in current):
            return False
        self._bindings[key] = [
            replace(item, source_version_id=version_id) if item.source_skill_id == skill_id else item
            for item in current
        ]
        return True

    async def list_bindings(
        self, *, owner_user_id: str, agent_id: str
    ) -> list[AgentSkillBinding]:
        return list(self._bindings.get((owner_user_id, agent_id), ()))

from __future__ import annotations

from typing import Protocol
from datetime import datetime, timezone

from app.v2.server.database import Database

from sqlalchemy import delete, select, update

from app.v2.server.catalog.orm import AgentRow, CatalogRow
from app.v2.server.catalog.packages import is_external_tool, package_owner
from app.v2.server.packages.repository import DatabasePackageStore
from app.v2.server.packages.orm import ManagedRecordRow
from sagents.v2.agent.management import AgentPackageBundle
from app.v2.server.identity.orm import UserRow
from app.v2.server.identity.orm import ApiKeyRow
from app.v2.server.skills.orm import AgentSkillSelectionRow
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from app.v2.server.catalog.records import (
    AgentRecord,
    ModelRecord,
    UserCatalog,
    apply_delete,
    apply_upsert,
    catalog_payload,
    empty_catalog,
)

_SECTIONS = ("models", "mcp_servers", "a2a_agents")


class CatalogStore(Protocol):
    async def list_agent_summaries(self, user_ids: list[str]) -> list[dict]: ...
    async def agent_owner(self, agent_id: str) -> str | None: ...
    async def get(self, user_id: str) -> UserCatalog: ...
    async def create_agent(self, user_id: str, record: AgentRecord) -> None: ...
    async def update_agent(self, user_id: str, record: AgentRecord) -> None: ...
    async def delete_agent(self, user_id: str, agent_id: str) -> None: ...
    async def replace_section(
        self, user_id: str, section: str, catalog: UserCatalog
    ) -> UserCatalog: ...
    async def list_all_models(
        self, user_ids: list[str]
    ) -> list[tuple[str, ModelRecord]]: ...
    async def default_model(self, user_id: str) -> ModelRecord | None: ...
    async def upsert_model(
        self, user_id: str, payload: dict[str, object]
    ) -> ModelRecord: ...
    async def delete_model(self, user_id: str, model_id: str) -> None: ...


class DatabaseCatalogStore:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.packages = DatabasePackageStore(database)

    async def list_agent_summaries(self, user_ids: list[str]) -> list[dict]:
        if not user_ids:
            return []
        catalog_statement = select(
            CatalogRow.user_id, CatalogRow.default_agent_id, CatalogRow.models,
        ).where(CatalogRow.user_id.in_(user_ids))
        async with self.database.session() as session:
            catalogs = (await session.execute(catalog_statement)).all()
        initialized = {row.user_id for row in catalogs}
        missing = [user_id for user_id in user_ids if user_id not in initialized]
        # Preserve lazy creation of the user's default agent, without loading
        # packages or taking write locks for already initialized catalogs.
        for user_id in missing:
            async with self.database.transaction() as session:
                await self._catalog(session, user_id)
        statement = select(
            AgentRow.id, AgentRow.owner_user_id, AgentRow.package_ref,
        ).where(AgentRow.owner_user_id.in_(user_ids)).order_by(AgentRow.id)
        async with self.database.session() as session:
            if missing:
                catalogs = (await session.execute(catalog_statement)).all()
            rows = (await session.execute(statement)).all()
        # Legacy records still use the existing migration path. Initialized
        # records are read without validating or resolving complete packages.
        legacy_owners = {row.owner_user_id for row in rows if not row.package_ref}
        for user_id in legacy_owners:
            await self.get(user_id)
        owners = {user_id: package_owner(user_id) for user_id in user_ids}
        async with self.database.session() as session:
            if legacy_owners:
                rows = (await session.execute(statement)).all()
            refs = {row.package_ref for row in rows}
            packages = (await session.execute(select(
                ManagedRecordRow.owner, ManagedRecordRow.ref,
                ManagedRecordRow.payload["manifest"]["agents"].label("definitions"),
            ).where(
                ManagedRecordRow.owner.in_(owners.values()),
                ManagedRecordRow.kind == "bundle", ManagedRecordRow.ref.in_(refs),
            ))).all() if refs else []
        definitions = {(row.owner, row.ref): row.definitions for row in packages}
        models = {row.user_id: {model["id"]: model["model"] for model in row.models}
                  for row in catalogs}
        defaults = {row.user_id: row.default_agent_id for row in catalogs}
        owner_order = {user_id: index for index, user_id in enumerate(user_ids)}
        result = []
        for row in sorted(rows, key=lambda row: (
            owner_order[row.owner_user_id], row.id != defaults[row.owner_user_id], row.id,
        )):
            agents = definitions.get((owners[row.owner_user_id], row.package_ref))
            if agents is None or row.id not in agents:
                raise ValueError("catalog Agent package is missing; refusing legacy fallback")
            agent = agents[row.id]
            model_id = agent.get("models", {}).get("primary", "default")
            model_id = "" if model_id == "default" else model_id
            result.append(dict(
                id=row.id, user_id=row.owner_user_id, name=agent["name"],
                description=agent.get("description") or "", model_id=model_id,
                model_name=models[row.owner_user_id].get(model_id, model_id),
                tool_count=sum(not is_external_tool(name) for name in agent.get("tools", [])),
                skill_count=len(agent.get("skills", [])),
            ))
        return result

    async def agent_owner(self, agent_id: str) -> str | None:
        async with self.database.session() as session:
            return await session.scalar(
                select(AgentRow.owner_user_id).where(AgentRow.id == agent_id)
            )

    async def _catalog(self, session, user_id: str) -> CatalogRow:
        # Lock a stable parent even before the first catalog is created. This
        # serializes initialization/default changes across server processes.
        owner = await session.get(UserRow, user_id, with_for_update=True)
        if owner is None:
            raise _not_found("user not found")
        row = await session.get(CatalogRow, user_id, with_for_update=True)
        if row is None:
            initial = empty_catalog()
            initial_record = initial.agents[0]
            session.add(await self._new_agent_row(session, user_id, initial_record))
            row = CatalogRow(
                user_id=user_id,
                default_agent_id=initial.default_agent_id,
                models=[],
                mcp_servers=[],
                a2a_agents=[],
            )
            session.add(row)
            await session.flush()
        return row

    async def get(self, user_id: str) -> UserCatalog:
        async with self.database.transaction() as session:
            row = await self._catalog(session, user_id)
            agents = (
                await session.scalars(
                    select(AgentRow)
                    .where(AgentRow.owner_user_id == user_id)
                    .order_by(AgentRow.id)
                )
            ).all()
            bindings = (
                await session.scalars(
                    select(AgentSkillSelectionRow)
                    .where(AgentSkillSelectionRow.owner_user_id == user_id)
                    .order_by(AgentSkillSelectionRow.position)
                )
            ).all()
            skills: dict[str, list[str]] = {}
            for binding in bindings:
                skills.setdefault(binding.agent_id, []).append(binding.skill_name)
            refs = {agent.package_ref for agent in agents if agent.package_ref}
            package_rows = (await session.scalars(select(ManagedRecordRow).where(
                ManagedRecordRow.owner == package_owner(user_id),
                ManagedRecordRow.kind == "bundle", ManagedRecordRow.ref.in_(refs),
            ))).all() if refs else []
            packages = {row.ref: row for row in package_rows}
            records = []
            for agent in agents:
                if agent.package_ref:
                    stored = packages.get(agent.package_ref)
                    if stored is None:
                        raise ValueError("catalog Agent package is missing; refusing legacy fallback")
                    package = AgentPackageBundle.model_validate(stored.payload)
                    if package.content_hash != agent.package_ref:
                        raise ValueError("catalog Agent package hash mismatch")
                    record = _agent_record(agent, [], package=package)
                else:
                    record = _agent_record(agent, skills.get(agent.id, []))
                    agent.package_ref = await self.packages.save_in_transaction(
                        session, package_owner(user_id), record.package)
                records.append(record)
            records.sort(key=lambda agent: agent.id != row.default_agent_id)
            return UserCatalog(
                default_agent_id=row.default_agent_id,
                agents=records,
                models=row.models,
                mcp_servers=row.mcp_servers,
                a2a_agents=row.a2a_agents,
            )

    async def create_agent(self, user_id: str, record: AgentRecord) -> None:
        async with self.database.transaction() as session:
            await self._catalog(session, user_id)
            session.add(await self._new_agent_row(session, user_id, record))

    async def update_agent(self, user_id: str, record: AgentRecord) -> None:
        record = AgentRecord.model_validate(record.model_dump(mode="json"))
        async with self.database.transaction() as session:
            await self._catalog(session, user_id)
            row = await session.get(AgentRow, record.id, with_for_update=True)
            if row is None or row.owner_user_id != user_id:
                raise _not_found("agent not found")
            row.package_ref = await self.packages.save_in_transaction(session, package_owner(user_id), record.package)
            for key, value in _agent_values(record).items():
                setattr(row, key, value)

    async def _new_agent_row(self, session, user_id, record):
        record = AgentRecord.model_validate(record.model_dump(mode="json"))
        row = _agent_row(user_id, record)
        row.package_ref = await self.packages.save_in_transaction(session, package_owner(user_id), record.package)
        return row

    async def migrate_packages(self):
        async with self.database.session() as session:
            owners = list((await session.scalars(select(AgentRow.owner_user_id).distinct())).all())
        for owner in owners:
            await self.get(owner)

    async def delete_agent(self, user_id: str, agent_id: str) -> None:
        async with self.database.transaction() as session:
            catalog = await self._catalog(session, user_id)
            row = await session.get(AgentRow, agent_id, with_for_update=True)
            if row is None or row.owner_user_id != user_id:
                raise _not_found("agent not found")
            remaining = (
                await session.scalars(
                    select(AgentRow.id)
                    .where(AgentRow.owner_user_id == user_id, AgentRow.id != agent_id)
                    .order_by(AgentRow.id)
                )
            ).all()
            if not remaining:
                raise _not_found("at least one agent is required")
            if catalog.default_agent_id == agent_id:
                catalog.default_agent_id = remaining[0]
            await session.execute(
                delete(AgentSkillSelectionRow).where(
                    AgentSkillSelectionRow.owner_user_id == user_id,
                    AgentSkillSelectionRow.agent_id == agent_id,
                )
            )
            # A deleted agent's credentials must never become unscoped keys.
            await session.execute(
                update(ApiKeyRow)
                .where(
                    ApiKeyRow.owner_user_id == user_id,
                    ApiKeyRow.agent_id == agent_id,
                    ApiKeyRow.revoked_at == "",
                )
                .values(revoked_at=datetime.now(timezone.utc).isoformat())
            )
            await session.delete(row)

    async def replace_section(
        self, user_id: str, section: str, catalog: UserCatalog
    ) -> UserCatalog:
        if section not in _SECTIONS:
            raise ValueError(f"unknown catalog section: {section}")
        documents = catalog_payload(catalog)
        async with self.database.transaction() as session:
            row = await self._catalog(session, user_id)
            setattr(row, section, documents[section])
        return catalog

    async def list_all_models(
        self, user_ids: list[str]
    ) -> list[tuple[str, ModelRecord]]:
        return [
            (user_id, model)
            for user_id in user_ids
            for model in (await self.get(user_id)).models
        ]

    async def default_model(self, user_id: str) -> ModelRecord | None:
        models = (await self.get(user_id)).models
        return next(
            (item for item in models if item.is_default), models[0] if models else None
        )

    async def upsert_model(
        self, user_id: str, payload: dict[str, object]
    ) -> ModelRecord:
        record, catalog = apply_upsert(await self.get(user_id), payload)
        await self.replace_section(user_id, "models", catalog)
        return record

    async def delete_model(self, user_id: str, model_id: str) -> None:
        catalog = apply_delete(await self.get(user_id), model_id)
        await self.replace_section(user_id, "models", catalog)


def _agent_values(record: AgentRecord) -> dict:
    return record.model_dump(mode="json", exclude={"id", "skills", "package", "external_tools"})


def _agent_row(user_id: str, record: AgentRecord) -> AgentRow:
    return AgentRow(id=record.id, owner_user_id=user_id, **_agent_values(record))


def _agent_record(row: AgentRow, skills: list[str], *, package=None) -> AgentRecord:
    return AgentRecord(
        id=row.id,
        package=package,
        name=row.name,
        description=row.description,
        instructions=row.instructions,
        model_id=row.model_id,
        tools=row.tools,
        tool_approval=row.tool_approval,
        execution_policy=row.execution_policy,
        skills=skills,
    )


def _not_found(message: str) -> SageV2Error:
    return SageV2Error(
        RuntimeErrorInfo(
            code="server.catalog.records.not_found",
            category=ErrorCategory.VALIDATION,
            message=message,
        )
    )

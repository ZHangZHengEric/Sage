from __future__ import annotations

from typing import Protocol
from datetime import datetime, timezone

from app.v2.server.database import Database

from sqlalchemy import delete, select, update

from app.v2.server.catalog.orm import AgentRow, CatalogRow
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
            session.add(_agent_row(user_id, initial.agents[0]))
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
            records = [
                _agent_record(agent, skills.get(agent.id, [])) for agent in agents
            ]
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
            session.add(_agent_row(user_id, record))

    async def update_agent(self, user_id: str, record: AgentRecord) -> None:
        async with self.database.transaction() as session:
            await self._catalog(session, user_id)
            row = await session.get(AgentRow, record.id, with_for_update=True)
            if row is None or row.owner_user_id != user_id:
                raise _not_found("agent not found")
            for key, value in _agent_values(record).items():
                setattr(row, key, value)

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
    return record.model_dump(mode="json", exclude={"id", "skills"})


def _agent_row(user_id: str, record: AgentRecord) -> AgentRow:
    return AgentRow(id=record.id, owner_user_id=user_id, **_agent_values(record))


def _agent_record(row: AgentRow, skills: list[str]) -> AgentRecord:
    return AgentRecord(
        id=row.id,
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

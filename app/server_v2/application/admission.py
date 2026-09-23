"""Shared admission for AG-UI and A2A runs."""

from __future__ import annotations

from dataclasses import dataclass

from app.server_v2.application.composition import composition_metadata
from app.server_v2.core.errors import ServerV2Error
from app.server_v2.domain.catalog import (
    UserCatalog,
    enabled_a2a_agents,
    enabled_mcp_servers,
    require_agent,
)
from app.server_v2.domain.skills import SkillRecord
from app.server_v2.domain.threads import resolve_thread_agent_id


@dataclass(frozen=True, slots=True)
class AdmittedRun:
    session_id: str
    agent_id: str
    agent: object
    skills: tuple[SkillRecord, ...]
    catalog: UserCatalog
    metadata: dict
    model_ready: bool


class RunAdmission:
    def __init__(self, host) -> None:
        self.host = host

    async def prepare(
        self,
        *,
        user_id: str,
        session_id: str,
        agent_id: str,
        pin_existing: bool,
        call_depth: int = 0,
        absent: str = "thread not found",
    ) -> AdmittedRun:
        existing = await self.host.threads.find(session_id)
        if existing is not None and existing.user_id != user_id:
            raise ServerV2Error("not_found", absent)
        catalog = await self.host.catalog.get(user_id)
        requested = (
            resolve_thread_agent_id(existing, agent_id) if pin_existing else agent_id
        )
        agent = require_agent(catalog, requested or None)
        skills = tuple(
            await self.host.skill_catalog.bound_skills(
                owner_user_id=user_id, agent_id=agent.id
            )
        )
        return AdmittedRun(
            session_id=session_id,
            agent_id=agent.id,
            agent=agent,
            skills=skills,
            catalog=catalog,
            metadata=composition_metadata(
                agent=agent,
                skills=skills,
                mcp_servers=tuple(item.name for item in enabled_mcp_servers(catalog)),
                a2a_agents=tuple(item.name for item in enabled_a2a_agents(catalog)),
                call_depth=call_depth,
            ),
            model_ready=self.host.execution.has_model(catalog),
        )

    async def remember(
        self, session_id: str, user_id: str, *, title: str, agent_id: str
    ) -> None:
        await self.host.threads.upsert(
            session_id, user_id, title=title, agent_id=agent_id
        )

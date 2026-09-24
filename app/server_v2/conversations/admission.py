"""Shared admission for AG-UI and A2A runs."""

from __future__ import annotations

from dataclasses import dataclass

from app.server_v2.catalog.records import (
    UserCatalog,
    enabled_a2a_agents,
    enabled_mcp_servers,
    require_agent,
)
from app.server_v2.conversations.composition import composition_metadata
from app.server_v2.conversations.records import resolve_thread_agent_id
from app.server_v2.skills.records import SkillRecord
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error


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
    def __init__(self, *, threads, catalog, skills, execution) -> None:
        self.threads = threads
        self.catalog = catalog
        self.skills = skills
        self.execution = execution

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
        existing = await self.threads.find(session_id)
        if existing is not None and existing.user_id != user_id:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="server.conversations.admission.not_found",
                    category=ErrorCategory.VALIDATION,
                    message=absent,
                )
            )
        catalog = await self.catalog.store.get(user_id)
        requested = (
            resolve_thread_agent_id(existing, agent_id) if pin_existing else agent_id
        )
        agent = require_agent(catalog, requested or None)
        skills = tuple(
            await self.skills.bound_skills(owner_user_id=user_id, agent_id=agent.id)
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
            model_ready=self.execution.has_model(catalog),
        )

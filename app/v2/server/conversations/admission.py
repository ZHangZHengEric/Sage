"""Shared admission for AG-UI and A2A runs."""

from __future__ import annotations

from dataclasses import dataclass

from app.v2.server.catalog.records import (
    UserCatalog,
    enabled_a2a_agents,
    enabled_mcp_servers,
    require_agent,
)
from app.v2.server.conversations.composition import composition_metadata
from app.v2.server.conversations.records import resolve_thread_agent_id
from app.v2.server.skills.records import SkillRecord
from app.v2.server.runtime.policy import ExecutionPolicy, execution_metadata, intersect_policies, server_ceiling
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.package.manifest import CompositionResolver


@dataclass(frozen=True, slots=True)
class AdmittedRun:
    session_id: str
    agent_id: str
    agent: object
    skills: tuple[SkillRecord, ...]
    catalog: UserCatalog
    metadata: dict
    model_ready: bool
    max_steps: int | None


class RunAdmission:
    def __init__(self, *, threads, catalog, skills, execution, users=None, settings=None,
                 session_access=None, context_for=None) -> None:
        self.threads = threads
        self.catalog = catalog
        self.skills = skills
        self.execution = execution
        self.users = users
        self.settings = settings
        self.session_access = session_access
        self.context_for = context_for

    async def prepare(
        self,
        *,
        user_id: str,
        session_id: str,
        agent_id: str,
        pin_existing: bool,
        call_depth: int = 0,
        package=None,
        absent: str = "thread not found",
        tenant_id: str | None = None,
        key_id: str | None = None,
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
        binding = await self.threads.binding(session_id)
        if binding is not None and (
            binding.owner_id != user_id or binding.tenant_id != (tenant_id or user_id)
            or (agent_id and agent_id != binding.agent_id and not pin_existing)
        ):
            raise SageV2Error(RuntimeErrorInfo(
                code="server.session.ownership_conflict", category=ErrorCategory.CONFLICT,
                message="session_id is already bound to another tenant or Agent",
                metadata={"side_effect_state": "not_applied"},
            ))
        if binding is None and self.session_access is not None and tenant_id is None:
            # Pre-upgrade or orphaned Sessions may have no SQL claim yet.
            # Validate their durable commands before adopting an identity.
            context = self.context_for(user_id)
            try:
                runs = await self.session_access.list_session_runs(session_id, context)
            except SageV2Error as exc:
                if not exc.info.code.endswith("not_found"):
                    raise
                runs = ()
            for run in runs:
                command = await self.session_access.get_start_command(run.run_id, context)
                if (command.config.metadata.get("server_v2.workspace_user_id", user_id) != user_id
                        or (agent_id and command.agent_id != agent_id and not pin_existing)):
                    raise SageV2Error(RuntimeErrorInfo(
                        code="server.session.ownership_conflict", category=ErrorCategory.CONFLICT,
                        message="Session belongs to another tenant or Agent",
                        metadata={"side_effect_state": "not_applied"},
                    ))
        catalog = await self.catalog.get(user_id)
        requested = (
            resolve_thread_agent_id(existing, agent_id) if pin_existing else agent_id
        )
        if package is None:
            agent = require_agent(catalog, requested or None)
        else:
            from app.v2.server.catalog.records import AgentRecord
            package_manifest = package.resolved_manifest()
            CompositionResolver().resolve(package_manifest)
            root_id = package_manifest.entrypoint.agent
            if root_id is None:
                raise SageV2Error(RuntimeErrorInfo(
                    code="server.package.entrypoint_invalid", category=ErrorCategory.VALIDATION,
                    message="Package 必须指定 Agent 入口；Flow 请配置在 Agent 的 entrypoint 中",
                ))
            if requested and requested != root_id:
                raise ValueError("Package entrypoint does not match the session Agent")
            definition = package_manifest.agents[root_id]
            route = package_manifest.models.get(definition.models.get("primary", "primary"))
            agent = AgentRecord(id=root_id, name=definition.name,
                instructions=definition.instructions.inline or "",
                model_id=route.model if route and route.model != "default" else "",
                tools=list(definition.tools), skills=list(definition.skills),
                tool_approval=definition.tool_approval)

        # Freeze the effective package budget with the admitted Agent. The
        # resolver intersects Agent budgets with the package policy ceiling.
        from app.v2.server.config.manifest import server_v2_run_manifest
        effective = package.resolved_manifest() if package else server_v2_run_manifest(self.settings, agent=agent, registry=getattr(self.catalog, "extensions", None))
        resolved = CompositionResolver().resolve(effective)
        if package is None:
            skills = tuple(await self.skills.bound_skills(owner_user_id=user_id, agent_id=agent.id))
        else:
            visible = await self.skills.list_visible(user_id=user_id, role="user")
            selected = {name for definition in package.manifest.agents.values() for name in definition.skills}
            skills = tuple(item for item in visible if item.name in selected)
        user = await self.users.get_by_id(user_id) if self.users is not None else None
        if self.users is not None and user is None:
            raise SageV2Error(RuntimeErrorInfo(code="server.admission.forbidden",
                category=ErrorCategory.AUTHORIZATION, message="User no longer exists"))
        policy = intersect_policies(
            user.execution_policy if user else ExecutionPolicy(),
            agent.execution_policy,
            server_ceiling(self.settings) if self.settings else ExecutionPolicy(shell="sandboxed"),
        )
        return AdmittedRun(
            session_id=session_id,
            agent_id=agent.id,
            agent=agent,
            skills=skills,
            catalog=catalog,
            metadata={**composition_metadata(
                agent=agent,
                skills=skills,
                mcp_servers=tuple(item.name for item in enabled_mcp_servers(catalog)),
                a2a_agents=tuple(item.name for item in enabled_a2a_agents(catalog)),
                call_depth=call_depth, package=package,
            ), **execution_metadata(policy, user_id=user_id, agent_id=agent.id, key_id=key_id)},
            model_ready=self.execution.has_model(catalog),
            max_steps=resolved.policy_ceilings[agent.id].max_steps,
        )

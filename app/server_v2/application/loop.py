"""Shared Run assembly for catalog chat and managed packages.

Chat keeps a pinned catalog Agent and materializes a loop on the process
Application. A package keeps an immutable version and its own table prefix.
Both call ``prepare_tenant_binding`` and ``open_model_lease`` for skills,
MCP, A2A peers, and the model lease. Sandbox provisioning lives next to the
official tool plugin.
"""

from __future__ import annotations

from contextlib import AsyncExitStack
from dataclasses import dataclass, replace

from sagents.v2.agent.factory import AgentCompositionFactory
from sagents.v2.context.components import ContextComponentBundle
from sagents.v2.contracts.commands import StartRun
from sagents.v2.model import RecordingModelProvider
from sagents.v2.package.manifest.resolver import CompositionResolver
from sagents.v2.skill.plugins.session import SessionDerivedSkillActivationRepository
from sagents.v2.tool.composite import CompositeToolCatalog, CompositeToolExecutor
from sagents.v2.tool.plugins.skill import SkillToolPlugin

from app.server_v2.application.assembly import skill_ports, tenant_tools
from app.server_v2.application.composition import (
    RunComposition,
    load_composition,
    selected_a2a_agents,
    selected_mcp_servers,
)
from app.server_v2.application.manifest import server_v2_run_manifest
from app.server_v2.application.official import attach_official_tools, resolve_agent_tools
from app.server_v2.domain.catalog import (
    catalog_model,
    enabled_a2a_agents,
    enabled_mcp_servers,
    require_agent,
)
from app.server_v2.infrastructure.models import close_model_provider, create_catalog_provider


@dataclass(frozen=True, slots=True)
class TenantBinding:
    provider: object
    workspace: object
    external: tuple


def prepare_tenant_binding(host, user_id: str, records, mcp_servers, a2a_agents, *, call_depth: int = 0):
    """Skill ports plus this tenant's MCP and A2A plugins, in catalog order."""

    provider, workspace = skill_ports(host, user_id, records)
    external = tuple(
        tenant_tools(host, user_id, mcp_servers, a2a_agents, call_depth=call_depth)
    )
    return TenantBinding(provider=provider, workspace=workspace, external=external)


def package_model_record(catalog, selected: str):
    if selected == "default":
        record = next((item for item in catalog.models if item.is_default), None)
        return record or next(iter(catalog.models), None)
    return next((item for item in catalog.models if item.id == selected), None)


async def open_model_lease(execution, user_id: str, record, *, allow_standalone: bool = False):
    """Borrow a pooled client, or build a one-off provider when chat has no pool."""

    if record is None:
        return None, None
    if execution.model_pool is not None or not allow_standalone:
        lease = await execution.acquire_model(user_id, record)
        return lease.provider, lease
    model = await create_catalog_provider(record)
    return model, _OwnedModelScope(model)


async def compose_catalog_loop(service, command: StartRun, *, user_id: str):
    catalog = await service.catalog.get(user_id)
    frozen = await _composition(service, command, catalog, user_id=user_id)
    agent, records = frozen.agent, frozen.skills
    names = tuple(record.name for record in records)
    tools = resolve_agent_tools(agent.tools, has_skills=bool(names))
    manifest = server_v2_run_manifest(
        service.settings,
        agent=agent,
        skills=names,
        tools=tools,
    )
    resolved = CompositionResolver().resolve(manifest)
    raw_model, model_scope = await _run_model(service, catalog, agent, user_id=user_id)
    extra = [model_scope] if model_scope is not None else []
    ports = None
    try:
        model = _recorded_model(service, service.model_budget.wrap(raw_model))
        ports = await service.application.materialize_agent(
            manifest,
            tenant_id=user_id,
            agent_id=agent.id,
            run_id=command.idempotency_key,
            model=model,
        )
        official, official_runtime, sandbox_handle = await attach_official_tools(
            service, command, user_id=user_id
        )
        extra.extend([official_runtime, sandbox_handle])
        factory = AgentCompositionFactory(
            service.application.entrypoint().runtime,
            context_components=ContextComponentBundle(
                token_estimator=ports.token_estimator,
                summary_store=_optional_service(service, "context.summary-store"),
                summarizer=ports.summarizer,
                reducer=ports.context_reducer,
            ),
        )
        binding = prepare_tenant_binding(
            service,
            user_id,
            records,
            selected_mcp_servers(catalog, frozen.mcp_servers),
            selected_a2a_agents(catalog, frozen.a2a_agents),
            call_depth=frozen.call_depth,
        )

        async def resolve_session_id(run_id: str) -> str:
            run = await service.application.entrypoint().runtime.session_store.get_run(
                run_id
            )
            return run.session_id

        loader = factory.create_skill_loader(
            resolved,
            agent.id,
            catalog=binding.provider,
            source=binding.provider,
            workspace=binding.workspace,
            activations=SessionDerivedSkillActivationRepository(
                service.application.service("derived-state.store"),
                resolve_session_id,
            ),
            enabled_skills=names,
            workspace_root="/workspace",
            skill_loading=ports.skill_loading,
        )
        catalogs = [official.catalog]
        executors = [official.executor]
        if service.agent_management is not None:
            from sagents.v2.tool.plugins.agent_management import AgentManagementToolPlugin

            management = AgentManagementToolPlugin(service.agent_management)
            catalogs.append(management.catalog)
            executors.append(management.executor)
        if names:
            skill_tool = SkillToolPlugin(loader, language=service.settings.language)
            catalogs.append(skill_tool.catalog)
            executors.append(skill_tool.executor)
        # Tools from the tenant's own catalogs are granted per catalog rather
        # than per Agent: the Agent's ``tools`` list names official tools, which
        # is all the product lets it choose from. Without this they would be
        # composed into the Run and then refused at call time, so configuring a
        # peer or an MCP server would look like it worked and never do anything.
        for tool in binding.external:
            catalogs.append(tool)
            executors.append(tool)
        from app.server_v2.application.tool_policy import server_tool_policy

        loop = factory.create_loop(
            resolved,
            agent.id,
            model=model,
            tool_catalog=CompositeToolCatalog(tuple(catalogs)),
            tool_executor=CompositeToolExecutor(tuple(executors)),
            granted_catalogs=binding.external,
            skill_loader=loader if names else None,
            tool_policy=server_tool_policy(service.agent_management)
            if service.agent_management is not None
            else None,
            continuation_policy=ports.continuation_policy,
            tool_selection_policy=ports.tool_selection_policy,
            log_sink=service.application.service("observability.log-sink"),
            trace_sink=_optional_service(service, "observability.trace-sink"),
        )
        # The host manifest hash, not a per-Run one: it catches a Run routed
        # to a restarted process with different backends. Drift in the Agent's
        # own configuration is handled by the frozen composition instead.
        loop.expected_resolved_spec_hash = command.resolved_spec_hash
        return loop, replace(ports, scope_handles=(*extra, *ports.scope_handles))
    except BaseException:
        async with AsyncExitStack() as stack:
            for handle in (*extra, *(ports.scope_handles if ports else ())):
                closer = getattr(handle, "close", None)
                if closer is not None:
                    stack.push_async_callback(closer)
        raise


async def _composition(service, command: StartRun, catalog, *, user_id: str):
    """Replay the admitted composition, or derive one for an internal Run.

    Runs that did not enter through the AG-UI endpoint carry no snapshot. They
    compose from the live catalog, but a grant the caller already narrowed is
    still a ceiling: it is never widened back to the Agent's own bindings.
    """

    frozen = load_composition(command, user_id=user_id)
    if frozen is not None:
        return frozen
    agent = require_agent(catalog, command.agent_id)
    records = tuple(
        await service.skill_catalog.bound_skills(
            owner_user_id=user_id, agent_id=agent.id
        )
    )
    granted = command.config.enabled_skills
    if granted is not None:
        allowed = set(granted)
        records = tuple(item for item in records if item.name in allowed)
    return RunComposition(
        agent=agent,
        skills=records,
        mcp_servers=tuple(item.name for item in enabled_mcp_servers(catalog)),
        a2a_agents=tuple(item.name for item in enabled_a2a_agents(catalog)),
    )


async def _run_model(service, catalog, agent, *, user_id):
    record = catalog_model(catalog, agent.model_id)
    provider, scope = await open_model_lease(
        service.execution, user_id, record, allow_standalone=True
    )
    if provider is not None:
        return provider, scope
    pool = service.execution.model_pool
    return pool or service.application.service("model.provider"), None


def _recorded_model(service, model):
    if isinstance(model, RecordingModelProvider):
        return model
    runtime = service.application.entrypoint().runtime

    async def resolve_session_id(run_id: str) -> str:
        return (await runtime.session_store.get_run(run_id)).session_id

    return RecordingModelProvider(
        model,
        sink=service.application.service("observability.diagnostic-sink"),
        log_sink=service.application.service("observability.log-sink"),
        trace_sink=_optional_service(service, "observability.trace-sink"),
        session_id_resolver=resolve_session_id,
    )


def _optional_service(service, name: str):
    try:
        return service.application.service(name)
    except KeyError:
        return None


class _OwnedModelScope:
    def __init__(self, model):
        self.model = model

    async def close(self):
        model, self.model = self.model, None
        if model is not None:
            await close_model_provider(model)

"""Server adapters for tenant resources and the common SAgents Package pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sagents.v2.contracts.commands import StartRun

from app.v2.server.conversations.composition import (
    RunComposition,
    load_composition,
)
from app.v2.server.config.manifest import server_v2_run_manifest
from app.v2.server.catalog.records import (
    enabled_a2a_agents,
    enabled_mcp_servers,
    require_agent,
)
from app.v2.server.runtime.models import (
    close_model_provider,
    create_catalog_provider,
)

if TYPE_CHECKING:
    from sagents.v2.application import SAgentApplication

    from app.v2.server.catalog.service import CatalogService
    from app.v2.server.config.settings import ServerSettings
    from app.v2.server.identity.context import RequestContexts
    from app.v2.server.packages.management import ServerAgentManagement
    from app.v2.server.runtime.execution import ProcessExecution
    from app.v2.server.runtime.integrations.a2a import A2APluginCache
    from app.v2.server.runtime.integrations.mcp import McpPluginCache
    from app.v2.server.skills.service import SkillCatalogService
    from app.v2.server.storage import ServerPaths


@dataclass(frozen=True, slots=True)
class TenantBinding:
    provider: object
    workspace: object
    external: tuple


@dataclass(frozen=True, slots=True)
class CatalogRunDependencies:
    settings: ServerSettings
    paths: ServerPaths
    catalog: CatalogService
    skill_catalog: SkillCatalogService
    execution: ProcessExecution
    application: SAgentApplication
    mcp_plugins: McpPluginCache
    a2a_plugins: A2APluginCache
    contexts: RequestContexts
    agent_management: ServerAgentManagement | None
    users: object
    keys: object = None
    threads: object = None


def prepare_tenant_binding(
    paths,
    mcp_plugins,
    a2a_plugins,
    user_id: str,
    records,
    mcp_servers,
    a2a_agents,
    *,
    agent_id: str,
    workspace_user_id: str | None = None,
    workspace_for_run=None,
    call_depth: int = 0,
):
    """Skill ports plus this tenant's MCP and A2A plugins, in catalog order."""

    from app.v2.server.skills.runtime import (
        CatalogSkillProvider,
        ReadThroughSkillWorkspace,
    )

    provider = CatalogSkillProvider(records, paths.data_root)
    workspace = ReadThroughSkillWorkspace(paths.data_root, workspace_user_id or user_id, records, agent_id=agent_id, workspace_for_run=workspace_for_run)
    external = tuple(
        plugin
        for plugin in (
            mcp_plugins.get(user_id, mcp_servers),
            a2a_plugins.get(user_id, a2a_agents, call_depth=call_depth),
        )
        if plugin is not None
    )
    return TenantBinding(provider=provider, workspace=workspace, external=external)


def package_model_record(catalog, selected: str):
    if selected == "default":
        record = next((item for item in catalog.models if item.is_default), None)
        return record or next(iter(catalog.models), None)
    return next((item for item in catalog.models if item.id == selected), None)


async def open_model_lease(
    execution, user_id: str, record, *, allow_standalone: bool = False
):
    """Borrow a pooled client, or build a one-off provider when chat has no pool."""

    if record is None:
        return None, None
    if execution.model_pool is not None:
        lease = await execution.model_pool.pool.acquire(user_id, record)
        return lease.provider, lease
    if not allow_standalone:
        raise RuntimeError("model pool is not started")
    model = await create_catalog_provider(record)
    return model, _OwnedModelScope(model)


async def compose_catalog_loop(
    service: CatalogRunDependencies, command: StartRun, *, user_id: str, run_id: str | None = None
):
    """Resolve the catalog ID to a Package, then use the shared Package builder."""
    from types import SimpleNamespace
    from app.v2.server.storage.workspaces import with_workspace_binding

    command = await with_workspace_binding(command, user_id, service.threads)
    catalog = await service.catalog.get(user_id)
    frozen = await _composition(service, command, catalog, user_id=user_id)
    bundle = frozen.package or frozen.agent.package
    manifest = bundle.resolved_manifest() if frozen.package is not None else server_v2_run_manifest(
        service.settings, agent=frozen.agent,
        skills=tuple(record.name for record in frozen.skills),
    )
    owner_run_id = run_id or command.idempotency_key
    factory = service.agent_management.package_builder_factory
    context = service.contexts.for_user(user_id)
    builder = await factory.build(
        bundle, service.paths.runtime_root, context,
        service.agent_management, catalog_run=(service, command, frozen),
    )
    builder.with_admitted_run_contract(owner_run_id, command.resolved_spec_hash)
    application = await builder.build(manifest, tenant_id=user_id)
    return PackageRunDriver(application), SimpleNamespace(scope_handles=(application,))


class PackageRunDriver:
    def __init__(self, application):
        self.application = application

    async def execute(self, run_id, context):
        return await self.application.entrypoint().drive_admitted_run(run_id, context)

    async def resume(self, run_id, context):
        return await self.application.entrypoint().drive_admitted_run(run_id, context, resume=True)


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


class _OwnedModelScope:
    def __init__(self, model):
        self.model = model

    async def close(self):
        model, self.model = self.model, None
        if model is not None:
            await close_model_provider(model)

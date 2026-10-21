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


async def load_catalog_agent(host, command, user_id):
    """Freeze product inputs, then load through the standard public App API."""
    from app.v2.server.runtime.sdk_plugins import run_selections, execution_selection, select_run_capabilities
    from app.v2.server.catalog.model_config import app_models
    service = host._catalog_run_dependencies()
    frozen = load_composition(command, user_id=user_id)
    catalog = await service.catalog.editor_catalog(user_id) if frozen is not None else await service.catalog.get_for_run(user_id, command.agent_id)
    if frozen is None:
        frozen = await _composition(service, command, catalog, user_id=user_id)
    bundle = frozen.package or frozen.agent.package_bundle
    manifest = bundle.resolved_manifest() if frozen.package is not None else server_v2_run_manifest(
        service.settings, agent=frozen.agent, registry=getattr(service.catalog, "extensions", None),
        skills=tuple(record.name for record in frozen.skills),
    )
    from app.v2.server.conversations.composition import selected_mcp_servers, selected_a2a_agents
    selections = run_selections(owner=user_id,
        mcp=selected_mcp_servers(catalog, frozen.mcp_servers), a2a=selected_a2a_agents(catalog, frozen.a2a_agents))
    runtime = service.application.runtime_configuration
    identity = {"session.store", "derived-state.store", "execution.scheduler", "execution.job-runtime",
                "observability.provider"}
    choices = select_run_capabilities(runtime.capabilities, manifest.runtime, selections)
    for key in identity:
        if key in runtime.capabilities:
            choices[key] = runtime.capabilities[key]
    choices["execution.binding"] = execution_selection(host, owner=user_id, agent_id=frozen.agent.id,
                                                       command=command, sandbox=frozen.agent.sandbox)
    selected_runtime = runtime.model_copy(update={"capabilities": choices})
    selected_models = command.config.metadata.get("server_v2.models") or app_models(catalog)
    # Dependency packages are pinned independently; publish updates explicitly.
    async def load(member):
        children = {name: await load(child) for name, child in member.dependencies.items()}
        package = manifest if member is bundle else member.resolved_manifest()
        current = next((value for value in service.application.loaded_agents if value.package_id == package.metadata.id), None)
        while True:
            try:
                if current is None:
                    return await service.application.load_agent(package, subagents=children,
                        runtime=selected_runtime, models=selected_models)
                return await service.application.update_agent(agent=current, package=package, subagents=children,
                    runtime=selected_runtime, models=selected_models)
            except ValueError as exc:
                if "Agent was updated" not in str(exc) and "Package changed; use update_agent" not in str(exc):
                    raise
                current = next((value for value in service.application.loaded_agents if value.package_id == package.metadata.id), None)
    return await load(bundle)


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

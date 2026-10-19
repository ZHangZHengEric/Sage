"""Build managed Agent packages with Server models, tools and workspaces."""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from dataclasses import replace

from app.v2.server.catalog.records import enabled_a2a_agents, enabled_mcp_servers
from app.v2.server.config.manifest import server_v2_manifest
from app.v2.server.runtime.loop import (
    open_model_lease,
    package_model_record,
)
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.package.manifest.runtime import CapabilitySelection


class CatalogPackageModel:
    def __init__(self, catalog, execution, user_id, routes, *, snapshot=None):
        self.catalog, self.execution = catalog, execution
        self.user_id, self.routes = user_id, routes
        self.snapshot = snapshot

    @asynccontextmanager
    async def provider(self, binding):
        catalog = self.snapshot if self.snapshot is not None else await self.catalog.get(self.user_id)
        route = self.routes.get(binding) or self.routes.get("primary")
        selected = route.credential.removeprefix("server-model:") if route and route.credential else "default"
        record = package_model_record(catalog, selected)
        if record is None:
            if selected != "default" or self.execution.fallback_model is None:
                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="server.packages.builder.validation",
                        category=ErrorCategory.VALIDATION,
                        message="package model is unavailable in caller catalog",
                    )
                )
            yield self.execution.fallback_model
            return
        if route is not None:
            record = record.model_copy(update={
                "protocol": route.provider, "base_url": route.base_url or record.base_url,
                "model": route.model, "request": route.request, "limits": route.limits,
                "capabilities": route.capabilities, "capability_profile": route.capability_profile,
            })
        _provider, scope = await open_model_lease(self.execution, self.user_id, record)
        try:
            yield scope.provider
        finally:
            await scope.close()

    async def diagnostic_request(self, request):
        import inspect
        async with self.provider(request.model_binding) as provider:
            preview = getattr(provider, "diagnostic_request", None)
            value = preview(request) if preview is not None else None
            return await value if inspect.isawaitable(value) else value

    async def capabilities(self, binding):
        async with self.provider(binding) as provider:
            return await provider.capabilities(binding)

    async def probe_capabilities(self, request):
        async with self.provider(request.model_binding) as provider:
            return await provider.probe_capabilities(request)

    async def stream(self, request):
        async with self.provider(request.model_binding) as provider:
            stream = provider.stream(request)
            try:
                async for event in stream:
                    yield event
            finally:
                await stream.aclose()


class ServerPackageBuilderFactory:
    """Describe registrations and serializable choices for managed Apps."""
    def __init__(self, *, host, settings, paths, catalog, skills, execution,
                 mcp_plugins, a2a_plugins, extensions, run_quota, policy, log_sink, diagnostic_sink):
        self.host, self.settings, self.paths = host, settings, paths
        self.catalog, self.skills, self.execution = catalog, skills, execution
        self.extensions, self.run_quota, self.policy = extensions, run_quota, policy
        self.log_sink, self.diagnostic_sink = log_sink, diagnostic_sink

    async def build(self, bundle, root, context, management):
        await self.policy.authorize("restore", bundle, context, management)
        from sagents.v2 import ApplicationConfiguration
        from app.v2.server.runtime.sdk_plugins import (
            server_registrations, service_registration, service_selection,
            run_selections, execution_selection, select_run_capabilities, SCHEDULER_CONFIG_SCHEMA,
        )
        from app.v2.server.catalog.model_config import app_models
        from app.v2.server.conversations.composition import composition_metadata
        from sagents.v2.runtime.execution.scheduler.plugins.ephemeral import InMemoryScheduler
        user = context.actor.principal_id
        catalog = (await self.catalog.get(user)).model_copy(deep=True)
        records = tuple(await self.skills.list_visible(user_id=user, role="user"))
        from app.v2.server.catalog.records import AgentRecord
        root_id = bundle.manifest.entrypoint.agent
        agent = AgentRecord(id=root_id, name=bundle.manifest.agents[root_id].name, package=bundle)
        mcp, a2a = enabled_mcp_servers(catalog), enabled_a2a_agents(catalog)
        composition = composition_metadata(agent=agent, skills=records,
            mcp_servers=tuple(item.name for item in mcp), a2a_agents=tuple(item.name for item in a2a), package=bundle)["server_v2.composition"]
        choices = run_selections(owner=user, composition=composition, mcp=mcp, a2a=a2a)
        choices.pop("agent.self-configuration", None)
        choices["execution.binding"] = execution_selection(self.host, owner=user, agent_id=root_id,
            command=None, sandbox=bundle.manifest.agents[root_id].sandbox, settings=self.settings)
        registrations = [*self.extensions, *server_registrations(self.host)]
        scheduler = InMemoryScheduler(quota_group=self.run_quota, max_pending_items=self.settings.max_pending_runs)
        for capability, value, ownership in (
            ("execution.scheduler", scheduler, "owned"),
            ("execution.model-budget", self.execution.model_budget, "borrowed"),
            ("server.model-clients", self.execution.model_pool, "borrowed"),
            ("observability.log-sink", self.log_sink, "borrowed"),
            ("observability.diagnostic-sink", self.diagnostic_sink, "borrowed"),
        ):
            scheduler_port = capability == "execution.scheduler"
            registrations.append(service_registration(capability, value, ownership=ownership,
                dependencies=("server.model-clients",) if scheduler_port else (),
                config_schema=SCHEDULER_CONFIG_SCHEMA if scheduler_port else None))
            choices[capability] = service_selection(capability, config={
                "max_concurrent_runs": self.settings.max_concurrent_runs,
                "max_concurrent_runs_per_tenant": self.settings.max_concurrent_runs_per_user,
                "max_pending_items": self.settings.max_pending_runs,
            } if scheduler_port else None)
        settings = replace(self.settings, mysql_url=None) if root.name.startswith("validate-") else self.settings
        runtime = server_v2_manifest(settings).runtime
        capabilities = select_run_capabilities(runtime.capabilities, bundle.manifest.runtime, choices)
        if capabilities.get("session.store") and settings.mysql_url:
            selection = capabilities["session.store"]
            suffix = hashlib.sha256(str(root).encode()).hexdigest()[:24]
            capabilities["session.store"] = selection.model_copy(update={"config": {
                **selection.config, "table_prefix": f"managed_{suffix}",
            }})
        else:
            capabilities["session.store"] = CapabilitySelection(plugin="sage.session.filesystem", config={"root": str(root)})
        runtime = runtime.model_copy(update={"capabilities": capabilities, "state_root": str(root),
            "plugin_trust_policy": bundle.manifest.runtime.plugin_trust_policy})
        return ApplicationConfiguration(tuple(registrations), runtime, app_models(catalog))

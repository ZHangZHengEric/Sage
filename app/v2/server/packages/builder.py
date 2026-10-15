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
    prepare_tenant_binding,
)
from app.v2.server.runtime.official import provision_workspace, agent_network_policy
from sagents.v2 import SAgentBuilder
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.package.manifest.runtime import CapabilitySelection
from sagents.v2.runtime.execution import RunExecutionBinding


class CatalogPackageModel:
    def __init__(self, catalog, execution, user_id, routes):
        self.catalog, self.execution = catalog, execution
        self.user_id, self.routes = user_id, routes

    @asynccontextmanager
    async def provider(self, binding):
        catalog = await self.catalog.get(self.user_id)
        route = self.routes.get(binding)
        selected = route.model if route else "default"
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
            record = record.for_route(route)
        _provider, scope = await open_model_lease(self.execution, self.user_id, record)
        try:
            yield scope.provider
        finally:
            await scope.close()

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


class PackageBindings:
    def __init__(self, paths, execution, user_id, *, agents, settings):
        self.paths, self.execution, self.user_id = paths, execution, user_id
        self.agents, self.settings = agents, settings
        self.workspaces = {}

    def workspace_for_run(self, run_id):
        return self.workspaces[run_id][0]

    async def acquire(self, request):
        if (
            request.context.actor.principal_id != self.user_id
            or request.context.actor.tenant_id != self.user_id
        ):
            raise PermissionError("execution identity does not match package owner")
        policy = getattr(request.workspace_policy, "value", request.workspace_policy)
        if policy == "private_child":
            workspace = self.paths.workspace_dir(
                self.user_id, request.agent_id, private_run_id=request.run_id
            )
        elif policy == "shared_parent":
            workspace = self.paths.workspace_dir(self.user_id, request.agent_id)
        else:
            raise ValueError("unsupported workspace policy")
        # Resolve on every acquisition, including child Runs and resumed Runs.
        # Indexing fails closed if the runtime asks for an undeclared Agent.
        network = agent_network_policy(self.agents[request.agent_id].sandbox, self.settings)
        handle = await provision_workspace(
            self.execution, workspace, request.context, run_id=request.run_id,
            network=network,
        )
        token = object()
        self.workspaces[request.run_id] = (workspace, token)
        binding = RunExecutionBinding(
            run_id=request.run_id,
            agent_id=request.agent_id,
            parent_run_id=request.parent_run_id,
            workspace_root="/workspace",
            workspace_policy=request.workspace_policy,
            sandbox=handle,
            grant_issuer=self.execution.sandbox_grant_issuer,
            lifecycle=request.lifecycle,
        )
        # The runtime owns the binding; discard the lookup when it is released.
        import weakref
        def forget():
            if self.workspaces.get(request.run_id, (None, None))[1] is token:
                self.workspaces.pop(request.run_id, None)
        weakref.finalize(binding, forget)
        return binding


class PackageBuilder(SAgentBuilder):
    def __init__(self, settings, run_quota, root):
        super().__init__()
        self.settings, self.run_quota, self.root = settings, run_quota, root

    async def build(self, manifest, **kwargs):
        # Temporary validation never creates permanent MySQL table families.
        settings = self.settings
        if self.root.name.startswith("validate-"):
            settings = replace(settings, mysql_url=None)
        runtime = server_v2_manifest(settings).runtime
        capabilities = dict(runtime.capabilities)
        capabilities.update(manifest.runtime.capabilities)
        if "session.store" in capabilities:
            selection = capabilities["session.store"]
            suffix = hashlib.sha256(str(self.root).encode()).hexdigest()[:24]
            capabilities["session.store"] = selection.model_copy(
                update={
                    "config": {**selection.config, "table_prefix": f"managed_{suffix}"}
                }
            )
        capabilities.setdefault(
            "tool.catalog", CapabilitySelection(plugin="sage.tool.official")
        )
        effective = manifest.model_copy(
            update={
                "runtime": runtime.model_copy(
                    update={
                        "capabilities": capabilities,
                        "plugin_trust_policy": manifest.runtime.plugin_trust_policy,
                    }
                )
            }
        )
        from sagents.v2.runtime.execution.scheduler.plugins.ephemeral import (
            InMemoryScheduler,
        )

        scheduler = InMemoryScheduler(
            quota_group=self.run_quota,
            max_pending_items=self.settings.max_pending_runs,
        )
        self.with_scheduler(scheduler)
        try:
            app = await super().build(effective, **kwargs)
            await app.adopt_resource(scheduler, close_after_existing=True)
            return app
        except BaseException:
            await scheduler.close()
            raise


class ServerPackageBuilderFactory:
    def __init__(
        self,
        *,
        settings,
        paths,
        catalog,
        skills,
        execution,
        mcp_plugins,
        a2a_plugins,
        extensions,
        run_quota,
        policy,
        log_sink,
    ):
        self.settings = settings
        self.paths = paths
        self.catalog = catalog
        self.skills = skills
        self.execution = execution
        self.mcp_plugins = mcp_plugins
        self.a2a_plugins = a2a_plugins
        self.extensions = extensions
        self.run_quota = run_quota
        self.policy = policy
        self.log_sink = log_sink

    async def build(self, bundle, root, context, management):
        await self.policy.authorize("restore", bundle, context, management)
        from app.v2.server.packages.tool_policy import server_tool_policy

        user_id = context.actor.principal_id
        bindings = PackageBindings(
            self.paths, self.execution, user_id,
            agents=bundle.manifest.agents, settings=self.settings,
        )
        builder = (
            PackageBuilder(self.settings, self.run_quota, root)
            .with_defaults(session_root=root)
            .with_log_sink(self.log_sink)
            .with_model_provider(
                CatalogPackageModel(
                    self.catalog,
                    self.execution,
                    user_id,
                    bundle.manifest.models,
                )
            )
            .with_execution_binding_provider(
                bindings
            )
            .with_agent_management(management)
            .with_tool_policy(server_tool_policy(management))
        )
        for registration in self.extensions:
            builder.register(registration)
        records = tuple(await self.skills.list_visible(user_id=user_id, role="user"))
        catalog = await self.catalog.get(user_id)
        binding = prepare_tenant_binding(
            self.paths,
            self.mcp_plugins,
            self.a2a_plugins,
            user_id,
            records,
            enabled_mcp_servers(catalog),
            enabled_a2a_agents(catalog),
            agent_id=bundle.manifest.entrypoint.agent,
            workspace_for_run=bindings.workspace_for_run,
        )
        builder.with_skill_provider(
            binding.provider, binding.provider, binding.workspace
        )
        for tool in binding.external:
            builder.with_additional_tools(tool, tool)
        return builder

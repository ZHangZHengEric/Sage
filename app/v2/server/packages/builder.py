"""Build managed Agent packages with Server models, tools and workspaces."""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from dataclasses import replace

from app.v2.server.catalog.records import enabled_a2a_agents, enabled_mcp_servers
from app.v2.server.config.manifest import server_v2_manifest
from app.v2.server.conversations.composition import selected_mcp_servers, selected_a2a_agents
from app.v2.server.runtime.loop import (
    open_model_lease,
    package_model_record,
    prepare_tenant_binding,
)
from app.v2.server.runtime.official import provision_workspace, agent_network_policy, BoundWorkspaceHandle
from sagents.v2 import SAgentBuilder
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.package.manifest.runtime import CapabilitySelection, RuntimeConfig
from sagents.v2.package.manifest.models import ModelRoute
from sagents.v2.runtime.execution import RunExecutionBinding


class CatalogPackageModel:
    def __init__(self, catalog, execution, user_id, routes, *, snapshot=None):
        self.catalog, self.execution = catalog, execution
        self.user_id, self.routes = user_id, routes
        self.snapshot = snapshot

    @asynccontextmanager
    async def provider(self, binding):
        catalog = self.snapshot if self.snapshot is not None else await self.catalog.get(self.user_id)
        route = self.routes.get(binding) or self.routes.get("primary")
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


class PackageBindings:
    def __init__(self, paths, execution, user_id, *, agents, settings, command=None, catalog=None):
        self.paths, self.execution, self.user_id = paths, execution, user_id
        self.agents, self.settings = agents, settings
        self.command, self.catalog = command, catalog
        self.workspaces = {}
        self.handles = {}

    def workspace_for_run(self, run_id):
        return self.workspaces[run_id][0]

    async def acquire(self, request):
        if (
            request.context.actor.principal_id != self.user_id
            or request.context.actor.tenant_id != self.user_id
        ):
            raise PermissionError("execution identity does not match package owner")
        from app.v2.server.storage.workspaces import workspace_user
        owner = workspace_user(self.command, self.user_id) if self.command else self.user_id
        policy = getattr(request.workspace_policy, "value", request.workspace_policy)
        if policy == "private_child":
            workspace = self.paths.workspace_dir(
                owner, request.agent_id, private_run_id=request.run_id
            )
        elif policy == "shared_parent":
            workspace = self.paths.workspace_dir(owner, request.agent_id)
        else:
            raise ValueError("unsupported workspace policy")
        # Resolve on every acquisition, including child Runs and resumed Runs.
        # Indexing fails closed if the runtime asks for an undeclared Agent.
        live = None
        if self.command is not None:
            catalog = await self.catalog.get(self.user_id)
            live_agent = next((item for item in catalog.agents if item.id == request.agent_id), None)
            from sagents.v2.package.manifest.agents import AgentSandboxConfig
            live = live_agent.sandbox if live_agent else AgentSandboxConfig()
        network = agent_network_policy(self.agents[request.agent_id].sandbox, self.settings, live=live)
        handle = await provision_workspace(
            self.execution, workspace, request.context, run_id=request.run_id,
            network=network,
        )
        token = object()
        self.workspaces[request.run_id] = (workspace, token)
        self.handles[request.agent_id] = handle
        binding = RunExecutionBinding(
            run_id=request.run_id,
            agent_id=request.agent_id,
            parent_run_id=request.parent_run_id,
            workspace_root="/workspace",
            host_workspace=str(workspace),
            workspace_policy=request.workspace_policy,
            sandbox=BoundWorkspaceHandle(handle, self.execution.sandbox_provider),
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
    def __init__(self, settings, run_quota, root, *, application=None):
        super().__init__()
        self.settings, self.run_quota, self.root = settings, run_quota, root
        self.host_application = application
        self.catalog_snapshot = None

    async def build(self, *, runtime=None, runtime_config_text=None, tenant_id=None):
        from sagents.v2.composition.inputs import runtime_input
        from sagents.v2.package.manifest.runtime import merge_capability_selections
        from sagents.v2.runtime.execution.scheduler.plugins.ephemeral import InMemoryScheduler

        selected = runtime_input(runtime, config_text=runtime_config_text) or RuntimeConfig()
        settings = replace(self.settings, mysql_url=None) if self.root.name.startswith("validate-") else self.settings
        base = server_v2_manifest(settings).runtime
        capabilities = merge_capability_selections(base.capabilities, selected.capabilities)
        if self.host_application is None and "session.store" in capabilities:
            selection = capabilities["session.store"]
            suffix = hashlib.sha256(str(self.root).encode()).hexdigest()[:24]
            capabilities["session.store"] = selection.model_copy(update={
                "config": {**selection.config, "table_prefix": f"managed_{suffix}"}
            })
        capabilities.setdefault("tool.catalog", CapabilitySelection(plugin="sage.tool.official"))
        effective = base.model_copy(update={"capabilities": capabilities,
            "plugin_trust_policy": selected.plugin_trust_policy})
        if self.host_application is not None:
            self.with_shared_runtime(self.host_application)
        else:
            scheduler = InMemoryScheduler(quota_group=self.run_quota,
                max_pending_items=self.settings.max_pending_runs)
            self.with_scheduler(scheduler)
            self.with_owned_resources(scheduler)
        return await super().build(runtime=effective, tenant_id=tenant_id)

    def _prepare_package(self, package):
        # Catalog profiles are host-owned model metadata, frozen for this builder.
        from sagents.v2.package.manifest.resolver import ResolvedSageManifest
        if isinstance(package, ResolvedSageManifest):
            return package
        routes = dict(package.models)
        if self.catalog_snapshot is not None:
            for key, route in routes.items():
                record = package_model_record(self.catalog_snapshot, route.model)
                if record is not None:
                    selected = record.for_route(route)
                    routes[key] = route.model_copy(update={
                        "request": selected.request, "limits": selected.limits,
                        "capabilities": selected.capabilities,
                        "capability_profile": selected.current_profile(),
                    })
        return package.model_copy(update={"models": routes})


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
        diagnostic_sink,
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
        self.diagnostic_sink = diagnostic_sink

    async def build(self, bundle, root, context, management, *, catalog_run=None):
        await self.policy.authorize("restore", bundle, context, management)
        from app.v2.server.packages.tool_policy import server_tool_policy

        user_id = context.actor.principal_id
        catalog = (await self.catalog.get(user_id)).model_copy(deep=True)
        command = catalog_run[1] if catalog_run is not None else None
        service = catalog_run[0] if catalog_run is not None else None
        from sagents.v2.agent.management.loading import bundle_agent_definitions
        bindings = PackageBindings(
            self.paths, self.execution, user_id,
            agents=bundle_agent_definitions(bundle), settings=self.settings,
            command=command, catalog=self.catalog,
        )
        builder = (
            PackageBuilder(self.settings, self.run_quota, root,
                           application=service.application if service else None)
            .with_defaults(session_root=root)
            .with_log_sink(self.log_sink)
            .with_diagnostic_sink(self.diagnostic_sink)
            .with_model_budget(self.execution.model_budget)
            .with_model_provider_factory(
                lambda resolved, agent_id: CatalogPackageModel(
                    self.catalog,
                    self.execution,
                    user_id,
                    {binding: ModelRoute.model_validate(resolved.model_routes[route])
                     for binding, route in resolved.agents[agent_id].model_bindings.items()},
                    snapshot=catalog,
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
        builder.catalog_snapshot = catalog
        frozen = catalog_run[2] if catalog_run is not None else None
        records = frozen.skills if frozen is not None else tuple(await self.skills.list_visible(user_id=user_id, role="user"))
        binding = prepare_tenant_binding(
            self.paths,
            self.mcp_plugins,
            self.a2a_plugins,
            user_id,
            records,
            selected_mcp_servers(catalog, frozen.mcp_servers) if frozen else enabled_mcp_servers(catalog),
            selected_a2a_agents(catalog, frozen.a2a_agents) if frozen else enabled_a2a_agents(catalog),
            agent_id=bundle.manifest.entrypoint.agent,
            workspace_for_run=bindings.workspace_for_run,
            call_depth=frozen.call_depth if frozen else 0,
        )
        builder.with_skill_provider(
            binding.provider, binding.provider, binding.workspace
        )
        for tool in binding.external:
            builder.with_additional_tools(tool, tool)
        if catalog_run is not None:
            from app.v2.server.runtime.policy import frozen_execution, live_execution_policy

            key_id, admitted_policy = frozen_execution(command)
            async def current_policy():
                return await live_execution_policy(command, users=service.users, keys=service.keys,
                    catalog=self.catalog, settings=self.settings, user_id=user_id)
            builder.with_tool_policy(server_tool_policy(management,
                execution_policy=admitted_policy, current_policy=current_policy,
                machine_invocation=key_id is not None))
            if (command.invocation_mode != "plan" and key_id is None
                    and command.parent_run_id is None and admitted_policy.shell != "deny"):
                import json
                from sagents.v2.agent.self_configuration import SelfConfigurationService, SqliteSelfConfigurationStore
                from sagents.v2.tool.plugins.sandbox_mcp import SandboxMcpSessionFactory
                from app.v2.server.storage.workspaces import workspace_user

                async def authorize_self_configuration(request, request_context):
                    if (request_context.actor.principal_id != user_id
                            or request_context.actor.tenant_id != user_id
                            or request_context.actor.delegated_by
                            or await service.users.get_by_id(user_id) is None):
                        raise PermissionError("Only the authenticated owner can configure this Agent")
                    live = await current_policy()
                    if live is None or live.shell == "deny":
                        raise PermissionError("The live execution grant does not permit capability changes")

                def self_configuration(agent_id):
                    if agent_id != command.agent_id:
                        return None
                    return SelfConfigurationService(
                        store=SqliteSelfConfigurationStore(self.paths.runtime_root / "self-configuration.sqlite3"),
                        owner=json.dumps(["server", user_id, agent_id]),
                        workspace_root=self.paths.workspace_dir(workspace_user(command, user_id), agent_id),
                        workspace_alias="/workspace", authorize=authorize_self_configuration,
                        mcp_session_factory=SandboxMcpSessionFactory(bindings.handles[agent_id], self.execution.sandbox_grant_issuer),
                    )
                builder.with_self_configuration(self_configuration)
        return builder

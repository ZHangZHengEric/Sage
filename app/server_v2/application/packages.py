"""Full-package hosting. Identity, credentials, backend and grants belong to Server."""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from dataclasses import replace

from sagents.v2 import AgentManagementService, AgentPackageBundle, SAgentBuilder
from sagents.v2.package.manifest.runtime import CapabilitySelection
from sagents.v2.runtime.execution import RunExecutionBinding
from sagents.v2.tool.plugins.agent_management import AgentManagementToolPlugin

from app.server_v2.core.errors import ServerV2Error
from app.server_v2.domain.catalog import enabled_a2a_agents, enabled_mcp_servers
from app.server_v2.application.official import (
    official_tool_catalog,
    resolve_agent_tools,
    workspace_sandbox_spec,
)
from app.server_v2.application.manifest import server_v2_manifest


class CatalogPackageModel:
    def __init__(self, host, user_id, routes):
        self.host, self.user_id, self.routes = host, user_id, routes

    @asynccontextmanager
    async def provider(self, binding):
        catalog = await self.host.catalog.get(self.user_id)
        route = self.routes.get(binding)
        selected = route.model if route else "default"
        record = next((item for item in catalog.models if item.id == selected), None)
        if selected == "default":
            record = next((item for item in catalog.models if item.is_default), None)
            record = record or next(iter(catalog.models), None)
        if record is None:
            if selected != "default" or self.host.execution.fallback_model is None:
                raise ServerV2Error(
                    "validation", "package model is unavailable in caller catalog"
                )
            yield self.host.execution.fallback_model
        else:
            lease = await self.host.execution.acquire_model(self.user_id, record)
            try:
                yield lease.provider
            finally:
                await lease.close()

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
    def __init__(self, host, user_id):
        self.host, self.user_id = host, user_id

    async def acquire(self, request):
        if (
            request.context.actor.principal_id != self.user_id
            or request.context.actor.tenant_id != self.user_id
        ):
            raise PermissionError("execution identity does not match package owner")
        policy = getattr(request.workspace_policy, "value", request.workspace_policy)
        workspace = self.host.paths.workspace_dir(self.user_id)
        if policy == "private_child":
            workspace = (
                workspace
                / ".runs"
                / hashlib.sha256(request.run_id.encode()).hexdigest()
            )
        elif policy != "shared_parent":
            raise ValueError("unsupported workspace policy")
        workspace.mkdir(parents=True, exist_ok=True)
        handle = await self.host.execution.sandbox_provider.provision(
            workspace_sandbox_spec(workspace), request.context, run_id=request.run_id
        )
        return RunExecutionBinding(
            run_id=request.run_id,
            agent_id=request.agent_id,
            parent_run_id=request.parent_run_id,
            workspace_root="/workspace",
            workspace_policy=request.workspace_policy,
            sandbox=handle,
            grant_issuer=self.host.execution.sandbox_grant_issuer,
            lifecycle=request.lifecycle,
        )


class PackageBuilder(SAgentBuilder):
    def __init__(self, host, root):
        super().__init__()
        self.host, self.root = host, root

    async def build(self, manifest, **kwargs):
        # Temporary validation never creates permanent MySQL table families.
        settings = self.host.settings
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
            quota_group=self.host.run_quota,
            max_pending_items=self.host.settings.max_pending_runs,
        )
        self.with_scheduler(scheduler)
        try:
            app = await super().build(effective, **kwargs)
            await app.adopt_resource(scheduler, close_after_existing=True)
            return app
        except BaseException:
            await scheduler.close()
            raise


class ServerAgentManagement(AgentManagementService):
    def __init__(self, host, store=None):
        self.host = host
        super().__init__(
            host.paths.data_root / "managed",
            store=store,
            builder_factory=self.builder,
            max_applications=host.settings.max_managed_applications,
            max_concurrent_builds=host.settings.max_managed_builds,
            authorize=self.authorize_package,
            model_budget=host.model_budget,
            job_runtime=host.application.service("execution.job-runtime"),
            allow_source_plugins=host.package_authorizer is not None,
            inventory=tuple(
                {"id": item.descriptor.plugin_id, "version": item.descriptor.version}
                for item in host.package_extensions
            ),
        )

    def context_for(self, user_id: str):
        return self.host.request_context(user_id)

    def capacity_snapshot(self) -> dict:
        group = self.host.run_quota
        return {
            "management": self.capacity(),
            "models": self.host.model_budget.snapshot(),
            "runs": {
                "active": len(group.leases()),
                "pending": group.pending(),
                "max_active": group.max_active,
                "max_per_user": group.max_per_tenant,
                "max_pending": group.max_pending,
            },
        }

    def schema(self):
        return {
            **super().schema(),
            "host_policy": {
                "model_routes": "provider=server; model=caller catalog ID or default; no URL or credentials",
                "runtime_capabilities": [
                    "flow.node",
                    "tool.catalog",
                    "memory.provider",
                ],
                "plugin_selection": "must be declared and explicitly host-authorized",
                "max_steps": 10000,
                "interfaces": "HTTP and AG-UI supplied by Server",
                "execution": "single process, shared global/per-user scheduler quotas",
            },
        }

    async def resources(self, context):
        user_id = context.actor.principal_id
        if (
            context.actor.tenant_id != user_id
            or await self.host.users.get_by_id(user_id) is None
        ):
            raise PermissionError("unknown package owner")
        catalog = await self.host.catalog.get(user_id)
        skills = await self.host.skills.list_visible(user_id=user_id, role="user")
        return {
            **await super().resources(context),
            "models": [item.public_dict() for item in catalog.models],
            "tools": [
                *official_tool_catalog(),
                *[
                    {"name": name, "source": server.name}
                    for server in enabled_mcp_servers(catalog)
                    for name in server.tools
                ],
                *[
                    {"name": name, "source": peer.name}
                    for peer in enabled_a2a_agents(catalog)
                    for name in peer.skills
                ],
            ],
            "skills": [
                {"name": item.name, "version_id": item.version_id} for item in skills
            ],
        }

    async def authorize_package(self, action, bundle, context):
        user_id = context.actor.principal_id
        if (
            context.actor.tenant_id != user_id
            or await self.host.users.get_by_id(user_id) is None
        ):
            raise PermissionError("package owner is not an authenticated user")
        # Read/control survive a revoked model or extension; execution must not.
        if action in {"read", "read_run", "cancel", "reply"}:
            return
        manifest = bundle.manifest
        if manifest.runtime.deployment_profile != "controlled_host":
            raise PermissionError("Server supports a single controlled host")
        if (
            set(manifest.runtime.capabilities)
            - {"flow.node", "tool.catalog", "memory.provider"}
            or manifest.runtime.required_guarantees
        ):
            raise PermissionError("runtime backends and guarantees are host owned")
        if manifest.credentials or manifest.environments:
            raise PermissionError(
                "credentials and environment overrides are host owned"
            )
        if manifest.interfaces:
            raise PermissionError("protocol interfaces are provided by Server")
        declared = {item.id for item in manifest.plugins}
        if any(
            selection.plugin not in declared
            for capability in manifest.runtime.capabilities
            for selection in manifest.runtime.selections(capability)
        ):
            raise PermissionError(
                "Selected plugins must be explicitly declared and authorized"
            )
        if (manifest.policies.budgets.max_steps or 100) > 10000:
            raise PermissionError("max_steps exceeds host ceiling 10000")
        catalog = await self.host.catalog.get(user_id)
        models = {item.id for item in catalog.models} | {"default"}
        for route in manifest.models.values():
            if (
                route.provider != "server"
                or route.model not in models
                or route.base_url
                or route.credential
                or route.plugin
            ):
                raise PermissionError(
                    "model routes must reference caller catalog IDs using provider=server"
                )
        known = {item["name"] for item in official_tool_catalog()}
        known.update(item.name for item in AgentManagementToolPlugin(self).definitions)
        known.add("load_skill")
        known.update(
            name for server in enabled_mcp_servers(catalog) for name in server.tools
        )
        known.update(
            name for peer in enabled_a2a_agents(catalog) for name in peer.skills
        )
        visible = await self.host.skills.list_visible(user_id=user_id, role="user")
        skills = {item.name for item in visible}
        for agent in manifest.agents.values():
            custom_tools = (
                manifest.runtime.selections("tool.catalog")
                and self.host.package_authorizer is not None
            )
            if (set(agent.tools) - known and not custom_tools) or set(
                agent.skills
            ) - skills:
                raise PermissionError("package requests unavailable tools or skills")
            if (
                agent.memory.recall or agent.memory.auto_write
            ) and not manifest.runtime.selections("memory.provider"):
                raise PermissionError(
                    "memory behavior requires a host-authorized memory provider"
                )
            if (agent.budgets.max_steps or 100) > 10000:
                raise PermissionError("max_steps exceeds host ceiling 10000")
        if manifest.plugins or action == "load_source_plugin":
            if self.host.package_authorizer is None:
                raise PermissionError(
                    "custom plugins require host registration and authorization"
                )
            allowed = {
                item.descriptor.plugin_id for item in self.host.package_extensions
            }
            for declaration in manifest.plugins:
                if (
                    declaration.id not in allowed
                    and f"extensions/{declaration.id}.py" not in bundle.files
                ):
                    raise PermissionError("plugin is not registered by host")
        if self.host.package_authorizer is not None:
            await self.host.package_authorizer(action, bundle, context)

    async def builder(self, bundle, root, context):
        await self.authorize_package("restore", bundle, context)
        from app.server_v2.application.tool_policy import server_tool_policy

        user_id = context.actor.principal_id
        builder = (
            PackageBuilder(self.host, root)
            .with_defaults(session_root=root)
            .with_model_provider(
                CatalogPackageModel(self.host, user_id, bundle.manifest.models)
            )
            .with_execution_binding_provider(PackageBindings(self.host, user_id))
            .with_agent_management(self)
            .with_tool_policy(server_tool_policy(self))
        )
        for registration in self.host.package_extensions:
            builder.register(registration)
        from app.server_v2.application.assembly import skill_ports, tenant_tools

        records = tuple(
            await self.host.skills.list_visible(user_id=user_id, role="user")
        )
        provider, workspace = skill_ports(self.host, user_id, records)
        builder.with_skill_provider(provider, provider, workspace)
        catalog = await self.host.catalog.get(user_id)
        for tool in tenant_tools(
            self.host,
            user_id,
            enabled_mcp_servers(catalog),
            enabled_a2a_agents(catalog),
        ):
            builder.with_additional_tools(tool, tool)
        return builder

    async def template(self, context, agent_id=None):
        from sagents.v2.package.presets import BuiltinPackageFactory
        from app.server_v2.domain.catalog import require_agent

        data = BuiltinPackageFactory.create(
            "assistant", package_id="user.assistant", model="default"
        ).model_dump(mode="json")
        data["runtime"]["capabilities"] = {}
        data["interfaces"] = {}
        data["credentials"] = {}
        for route in data["models"].values():
            route.update(
                provider="server",
                model="default",
                base_url=None,
                credential=None,
                plugin=None,
            )
        if agent_id:
            agent = require_agent(
                await self.host.catalog.get(context.actor.principal_id), agent_id
            )
            data["metadata"].update(id=f"user.{agent.id}", name=agent.name)
            definition = data["agents"]["assistant"]
            definition.update(
                name=agent.name,
                description=agent.description,
                instructions={"inline": agent.instructions or "Be helpful."},
                tools=list(
                    resolve_agent_tools(agent.tools, has_skills=bool(agent.skills))
                ),
                skills=list(
                    await self.host.skill_catalog.bound_names(
                        context.actor.principal_id, agent_id
                    )
                ),
            )
            for route in data["models"].values():
                route["model"] = agent.model_id or "default"
        return AgentPackageBundle.model_validate({"manifest": data}).model_dump(
            mode="json"
        )

    async def recover_pending(self):
        """Re-open unarchived operations in bounded pages; never replay a StartRun."""
        from sagents.v2.agent.management.service import owner_key
        import logging

        for user in await self.host.users.list_users():
            context = self.host.request_context(user.user_id)
            offset = 0
            while True:
                rows = await self.list_runs(context, limit=100, offset=offset)
                for row in rows:
                    if not row.get("handle"):
                        continue  # Caller must retry incomplete admission with original input.
                    if (
                        await self.store.terminal_status(
                            owner_key(context), row["operation"]
                        )
                        is not None
                    ):
                        continue
                    try:
                        await self.status(row["operation"], context)
                    except Exception:
                        logging.getLogger(__name__).exception(
                            "managed operation recovery failed: %s", row["operation"]
                        )
                if len(rows) < 100:
                    break
                offset += len(rows)

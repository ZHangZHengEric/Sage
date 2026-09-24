"""Server grants for user-owned Agent packages."""

from __future__ import annotations

from sagents.v2.tool.plugins.agent_management import AgentManagementToolPlugin

from app.server_v2.runtime.official import official_tool_catalog
from app.server_v2.catalog.records import enabled_a2a_agents, enabled_mcp_servers


class ServerPackagePolicy:
    def __init__(self, *, users, catalog, skills, package_authorizer, extensions):
        self.users = users
        self.catalog = catalog
        self.skills = skills
        self.package_authorizer = package_authorizer
        self.extensions = extensions

    async def authorize(self, action, bundle, context, management):
        user_id = context.actor.principal_id
        if (
            context.actor.tenant_id != user_id
            or await self.users.get_by_id(user_id) is None
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
        catalog = await self.catalog.get(user_id)
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
        known.update(
            item.name for item in AgentManagementToolPlugin(management).definitions
        )
        known.add("load_skill")
        known.update(
            name for server in enabled_mcp_servers(catalog) for name in server.tools
        )
        known.update(
            name for peer in enabled_a2a_agents(catalog) for name in peer.skills
        )
        visible = await self.skills.list_visible(user_id=user_id, role="user")
        skills = {item.name for item in visible}
        for agent in manifest.agents.values():
            custom_tools = (
                manifest.runtime.selections("tool.catalog")
                and self.package_authorizer is not None
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
            if self.package_authorizer is None:
                raise PermissionError(
                    "custom plugins require host registration and authorization"
                )
            allowed = {item.descriptor.plugin_id for item in self.extensions}
            for declaration in manifest.plugins:
                if (
                    declaration.id not in allowed
                    and f"extensions/{declaration.id}.py" not in bundle.files
                ):
                    raise PermissionError("plugin is not registered by host")
        if self.package_authorizer is not None:
            await self.package_authorizer(action, bundle, context)

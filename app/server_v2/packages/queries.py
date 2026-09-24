"""Server-facing schema, resource, template and capacity views for packages."""

from __future__ import annotations

from sagents.v2 import AgentPackageBundle
from sagents.v2.package.presets import BuiltinPackageFactory

from app.server_v2.runtime.official import (
    official_tool_catalog,
    resolve_agent_tools,
)
from app.server_v2.catalog.records import (
    enabled_a2a_agents,
    enabled_mcp_servers,
    require_agent,
)


class ServerPackageQueries:
    def __init__(
        self, *, users, catalog, skills, skill_catalog, model_budget, run_quota
    ):
        self.users = users
        self.catalog = catalog
        self.skills = skills
        self.skill_catalog = skill_catalog
        self.model_budget = model_budget
        self.run_quota = run_quota

    def capacity_snapshot(self, management_capacity: dict) -> dict:
        group = self.run_quota
        return {
            "management": management_capacity,
            "models": self.model_budget.snapshot(),
            "runs": {
                "active": len(group.leases()),
                "pending": group.pending(),
                "max_active": group.max_active,
                "max_per_user": group.max_per_tenant,
                "max_pending": group.max_pending,
            },
        }

    def schema(self, base_schema: dict) -> dict:
        return {
            **base_schema,
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

    async def resources(self, context, base_resources) -> dict:
        user_id = context.actor.principal_id
        if (
            context.actor.tenant_id != user_id
            or await self.users.get_by_id(user_id) is None
        ):
            raise PermissionError("unknown package owner")
        catalog = await self.catalog.get(user_id)
        skills = await self.skills.list_visible(user_id=user_id, role="user")
        return {
            **await base_resources(context),
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

    async def template(self, context, agent_id=None):
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
                await self.catalog.get(context.actor.principal_id), agent_id
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
                    await self.skill_catalog.bound_names(
                        context.actor.principal_id, agent_id
                    )
                ),
            )
            for route in data["models"].values():
                route["model"] = agent.model_id or "default"
        return AgentPackageBundle.model_validate({"manifest": data}).model_dump(
            mode="json"
        )

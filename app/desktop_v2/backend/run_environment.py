"""Resolve Desktop catalog inputs once, before accepting a Run.

Live environments retain credentials in memory. Durable metadata contains model
routes and MCP configuration fingerprints, not copies of catalog secrets. After
a restart MCP recovery fails closed if the referenced configuration has changed.
"""

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from app.desktop_v2.backend.catalog import (
    DesktopAgentRecord,
    DesktopModelProviderRecord,
)
from sagents.v2.tool.plugins.mcp import McpToolPlugin


@dataclass(frozen=True)
class DesktopRunEnvironment:
    workspace: Path
    agents: dict[str, DesktopAgentRecord]
    providers: dict[str, DesktopModelProviderRecord]
    mcp: McpToolPlugin
    snapshot: dict

    def provider(self, agent, *, fast=False):
        key = "fast_llm_provider_id" if fast else "llm_provider_id"
        provider_id = agent.config.get(key) or agent.config["llm_provider_id"]
        return self.providers[provider_id]


class DesktopRunEnvironmentMixin:
    async def _agent_in_environment(self, command, environment, user_id):
        agent = (
            environment.agents.get(command.agent_id)
            if environment is not None
            else None
        )
        if agent is None:
            return await self._agent_for_command(command, user_id)
        # Preserve Desktop's explicit "approve and remember" authorization
        # update without adopting unrelated catalog configuration changes.
        current = await self.catalog.get_agent(command.agent_id, user_id)
        remembered = (
            current.config.get("approvedShellCommands") if current is not None else None
        )
        if remembered is not None:
            return agent.model_copy(
                update={
                    "config": {
                        **agent.config,
                        "approvedShellCommands": list(remembered),
                    }
                },
                deep=True,
            )
        return agent

    async def _capture_run_environment(self, request, user_id):
        # Materialize defaults before taking the catalog copies.
        await self._agent(request.agent_id, user_id)
        agents = {
            value.agent_id: value.model_copy(deep=True)
            for value in await self.catalog.list_agents(user_id)
        }
        providers = {}
        overrides = request.run_context
        for agent_id, agent in agents.items():
            config = deepcopy(agent.config)
            config["systemContext"] = {
                **(config.get("systemContext") or config.get("system_context") or {}),
                **deepcopy(overrides.system_context),
            }
            if overrides.model_provider_id is not None:
                config["llm_provider_id"] = overrides.model_provider_id
            if overrides.fast_model_provider_id is not None:
                config["fast_llm_provider_id"] = overrides.fast_model_provider_id
            if agent_id == request.agent_id and overrides.tools is not None:
                allowed = config.get("availableTools")
                allowed_names = set(allowed or ())
                if config.get("availableSkills"):
                    allowed_names.add("load_skill")
                if allowed is not None and not set(overrides.tools) <= allowed_names:
                    raise ValueError("run tools exceed the agent tool grant")
                config["availableTools"] = list(overrides.tools)
                if "load_skill" not in overrides.tools:
                    # Composition otherwise implicitly adds load_skill for an
                    # agent with Skills, expanding an explicit Run tool grant.
                    config["availableSkills"] = []
            agent = agent.model_copy(update={"config": config}, deep=True)
            # An explicitly selected route must never silently fall back.
            for selected in (
                overrides.model_provider_id,
                overrides.fast_model_provider_id,
            ):
                if selected is not None:
                    value = await self.catalog.get_model_provider(selected, user_id)
                    if value is None or not value.api_key or not value.base_url:
                        raise ValueError(
                            f"run model provider is unavailable: {selected}"
                        )
            primary = (await self._provider(agent, user_id)).model_copy(deep=True)
            fast = (await self._fast_provider(agent, primary)).model_copy(deep=True)
            config["llm_provider_id"] = primary.id
            config["fast_llm_provider_id"] = fast.id
            agents[agent_id] = agent.model_copy(update={"config": config}, deep=True)
            providers.update({primary.id: primary, fast.id: fast})
        mcp, bindings = await self._resolve_run_mcp(user_id, overrides.mcp_bindings)
        workspace = await self.workspace_root(request.workspace_id, request.agent_id)
        snapshot = {
            "version": 1,
            "workspace": str(workspace.resolve()),
            "agents": {
                key: self._agent_runtime_snapshot(value)
                for key, value in agents.items()
            },
            "providers": {
                key: self._model_route_snapshot(value)
                for key, value in providers.items()
            },
            "mcp_bindings": bindings,
            "mcp_fingerprint": McpToolPlugin.servers_fingerprint(mcp.servers),
            "settings": self._read_settings_sync().model_dump(
                mode="json",
                include={
                    "language",
                    "agent_workspace_path",
                    "component_selections",
                    "component_configs",
                },
            ),
        }
        return DesktopRunEnvironment(workspace, agents, providers, mcp, snapshot)

    async def _resolve_run_mcp(self, user_id, bindings):
        from app.desktop_v2.backend.schemas import DesktopMcpBinding

        records = {
            value.name: value.model_copy(deep=True)
            for value in await self.catalog.list_mcp(user_id)
        }
        if bindings is None:
            bindings = [
                DesktopMcpBinding(name=value.name, required=False)
                for value in records.values()
                if not value.disabled
            ]
        if len({value.name for value in bindings}) != len(bindings):
            raise ValueError("duplicate run MCP binding")
        servers = []
        for binding in bindings:
            record = records.get(binding.name)
            if record is None or record.disabled:
                raise ValueError(f"run MCP server is unavailable: {binding.name}")
            if binding.env and record.protocol != "stdio":
                raise ValueError("run MCP environment overrides require stdio")
            record = record.model_copy(
                update={"env": {**record.env, **binding.env}}, deep=True
            )
            servers.append(self._mcp_config(record, required=binding.required))
        # One plugin per root invocation. Children may reuse it; unrelated Runs
        # never share discovery state or the in-memory operation ledger.
        return McpToolPlugin(tuple(servers)), [
            value.model_dump(mode="json") for value in bindings
        ]

    async def _environment_for_command(self, command, user_id, run_id):
        root_run_id = run_id
        while command.parent_run_id:
            root_run_id = command.parent_run_id
            command = await self.session_store.get_start_command(root_run_id)
        cached = self._run_environments.get(root_run_id)
        if cached is not None:
            return cached
        snapshot = command.config.metadata.get("desktop_environment")
        if snapshot is None:
            return None  # Runs persisted before environment snapshots.
        if snapshot.get("version") != 1:
            raise ValueError("unsupported Desktop run environment version")
        from app.desktop_v2.backend.schemas import DesktopMcpBinding

        mcp, _ = await self._resolve_run_mcp(
            user_id,
            [
                DesktopMcpBinding.model_validate(value)
                for value in snapshot["mcp_bindings"]
            ],
        )
        if (
            McpToolPlugin.servers_fingerprint(mcp.servers)
            != snapshot["mcp_fingerprint"]
        ):
            raise ValueError(
                "Run MCP configuration changed; restore its original configuration before recovery"
            )
        agents = {
            key: DesktopAgentRecord.model_validate({**value, "user_id": user_id})
            for key, value in snapshot["agents"].items()
        }
        providers = {}
        for key, route in snapshot["providers"].items():
            current = await self.catalog.get_model_provider(key, user_id)
            if current is None or not current.api_key:
                raise ValueError(f"Run model credentials are unavailable: {key}")
            providers[key] = DesktopModelProviderRecord.model_validate(
                {**route, "user_id": user_id, "api_key": current.api_key}
            )
        workspace = Path(snapshot["workspace"]).resolve(strict=True)
        if not workspace.is_dir():
            raise ValueError("Run workspace is no longer a directory")
        environment = DesktopRunEnvironment(
            workspace, agents, providers, mcp, deepcopy(snapshot)
        )
        self._run_environments[root_run_id] = environment
        return environment

"""Server capability plugins; the SDK owns all Agent execution and recovery."""
from __future__ import annotations

from sagents.v2.package.manifest.models import ModelRoute
from sagents.v2.package.manifest.runtime import CapabilitySelection
from sagents.v2.runtime.extensions import (
    CapabilityKey, CapabilityOffer, ExtensionDependency, ExtensionDescriptor,
    ExtensionRegistration, ExtensionScope,
)


def service_registration(capability, value, *, ownership="borrowed", dependencies=(), config_schema=None):
    return ExtensionRegistration(
        descriptor=ExtensionDescriptor(
            plugin_id="com.sage.server." + capability.replace(".", "-"),
            name="Server " + capability, version="2.0.0",
            provides=(CapabilityOffer(capability=capability, api_version="2"),),
            supported_scopes=frozenset({ExtensionScope.PROCESS}),
            dependencies=tuple(ExtensionDependency(capability=name) for name in dependencies),
            config_schema=config_schema or {"type": "object", "additionalProperties": False},
        ), factory=lambda context, deps: value, ownership=ownership,
    )


def service_selection(capability, *, config=None):
    return CapabilitySelection(plugin="com.sage.server." + capability.replace(".", "-"), scope="process", config=config or {})


SCHEDULER_CONFIG_SCHEMA = {"type": "object", "properties": {
    name: {"type": "integer", "minimum": 1} for name in (
        "max_concurrent_runs", "max_concurrent_runs_per_tenant", "max_pending_items")}, "additionalProperties": False}



def run_registration(capability, factory, *, extra=(), dependencies=()):
    return ExtensionRegistration(
        descriptor=ExtensionDescriptor(
            plugin_id="com.sage.server.run." + capability.replace(".", "-"),
            name="Server " + capability, version="2.0.0",
            provides=tuple(CapabilityOffer(capability=name, api_version="2") for name in (capability, *extra)),
            dependencies=(ExtensionDependency(capability="execution.environment"), *dependencies),
            supported_scopes=frozenset({ExtensionScope.RUN}), default_scope=ExtensionScope.RUN,
            config_schema={"type": "object", "properties": {
                "owner": {"type": "string"}, "composition": {"type": "object"},
                "mcp_fingerprints": {"type": "object"}, "a2a_fingerprints": {"type": "object"},
            }, "additionalProperties": False},
        ), factory=factory, ownership="borrowed",
        start=(lambda instance, context, deps: {
            CapabilityKey(capability=name): getattr(instance, "catalog" if name == "tool.catalog" else "executor", instance)
            if name.startswith("tool.") else instance for name in (capability, *extra)
        }) if extra else None,
    )


async def run_inputs(host, context, deps):
    from app.v2.server.conversations.composition import load_composition
    run = deps.require("execution.environment")
    user = run.context.actor.principal_id
    if user != run.context.actor.tenant_id or context.config.get("owner", user) != user:
        raise PermissionError("Server Run resources belong to another owner")
    command = run.command
    store = deps.require("session.store")
    while command.parent_run_id:
        command = await store.get_start_command(command.parent_run_id)
    frozen = load_composition(command, user_id=user)
    if frozen is None:
        raw = context.config.get("composition")
        if raw is None:
            raise ValueError("Run has no accepted Server composition")
        command = command.model_copy(update={"agent_id": raw["agent"]["id"], "config": command.config.model_copy(update={
            "metadata": {**command.config.metadata, "server_v2.composition": raw},
            "enabled_skills": tuple(item["name"] for item in raw["skills"]),
        })})
        frozen = load_composition(command, user_id=user)
    return run, command, frozen, user


def server_registrations(host):
    dependency = (ExtensionDependency(capability="session.store"),)

    async def model(context, deps):
        from app.v2.server.packages.builder import CatalogPackageModel
        run, command, frozen, user = await run_inputs(host, context, deps)
        routes = {key: ModelRoute.model_validate(value) for key, value in context.agent_configuration["model_routes"].items()}
        return CatalogPackageModel(host.catalog_store, host.execution, user, routes)

    async def skills(context, deps):
        from app.v2.server.skills.runtime import CatalogSkillProvider
        _, _, frozen, _ = await run_inputs(host, context, deps)
        return CatalogSkillProvider(frozen.skills, host.paths.data_root)

    async def tools(context, deps):
        import hashlib
        from app.v2.server.conversations.composition import selected_a2a_agents, selected_mcp_servers
        from app.v2.server.runtime.integrations.external_tools import ScopedExternalTools
        from sagents.v2.tool import CompositeToolCatalog, CompositeToolExecutor
        from sagents.v2.tool.plugins.ephemeral import InMemoryToolCatalog, InMemoryToolExecutor
        run, command, frozen, user = await run_inputs(host, context, deps)
        catalog = await host.catalog_store.editor_catalog(user)
        servers = selected_mcp_servers(catalog, frozen.mcp_servers)
        peers = selected_a2a_agents(catalog, frozen.a2a_agents)
        for key, records in (("mcp_fingerprints", servers), ("a2a_fingerprints", peers)):
            actual = {record.name: hashlib.sha256(record.model_dump_json().encode()).hexdigest() for record in records}
            if actual != context.config.get(key, {}):
                raise ValueError(f"Run {key} configuration is incompatible with its accepted snapshot")
        providers = [value for value in (
            host.mcp_plugins.get(user, servers),
            host.a2a_plugins.get(user, peers, call_depth=frozen.call_depth),
        ) if value is not None]
        definition = context.agent_configuration["definition"]
        names = tuple(definition.get("tools", ()))
        async def command_reader(run_id):
            if run_id != run.run_id:
                raise PermissionError("external tools cannot read a different Run")
            return run.command
        scoped = tuple(ScopedExternalTools(value, {run.command.agent_id: type("Grant", (), {"tools": names})()},
                                          command_reader=command_reader) for value in providers)
        class Tools:
            catalog = CompositeToolCatalog(scoped) if scoped else InMemoryToolCatalog(())
            executor = CompositeToolExecutor(scoped) if scoped else InMemoryToolExecutor({}, {})
        return Tools()

    async def policy(context, deps):
        from app.v2.server.packages.tool_policy import server_tool_policy
        from app.v2.server.runtime.policy import (
            EXECUTION_METADATA_KEY, ExecutionPolicy, frozen_execution,
            intersect_policies, live_execution_policy,
        )
        run, command, frozen, user = await run_inputs(host, context, deps)
        if "server_v2.execution" not in command.config.metadata:
            return server_tool_policy(host.agent_management)
        key_id, admitted = frozen_execution(command, catalog_agent_id=frozen.agent.id)
        async def current():
            return await live_execution_policy(command, users=host.users, keys=host.credentials.keys,
                catalog=host.catalog_store, settings=host.settings, user_id=user, catalog_agent_id=frozen.agent.id)
        member_grants = command.config.metadata[EXECUTION_METADATA_KEY].get("agents", {})

        async def member_policy(run_id):
            if run_id != run.run_id:
                raise PermissionError("tool policy cannot read a different Run")
            selected = run.command
            store = deps.require("session.store")
            # Dynamically spawned Fibre experts inherit their parent's ceiling.
            while selected.agent_id not in member_grants and selected.parent_run_id:
                selected = await store.get_start_command(selected.parent_run_id)
            grant = member_grants.get(selected.agent_id)
            if grant is None:
                return None
            member = await host.catalog_store.get_execution_policy(user, grant["agent_id"])
            return intersect_policies(ExecutionPolicy.model_validate(grant["policy"]), member) if member is not None else None

        return server_tool_policy(host.agent_management, execution_policy=admitted,
                                  current_policy=current, run_policy=member_policy if member_grants else None,
                                  machine_invocation=key_id is not None)

    async def self_configuration(context, deps):
        import json
        from sagents.v2.agent.self_configuration import SelfConfigurationService, SqliteSelfConfigurationStore
        from sagents.v2.tool.plugins.sandbox_mcp import SandboxMcpSessionFactory
        from app.v2.server.runtime.policy import frozen_execution, live_execution_policy
        from app.v2.server.storage.workspaces import workspace_user
        run, command, frozen, user = await run_inputs(host, context, deps)
        key_id, admitted = frozen_execution(command, catalog_agent_id=frozen.agent.id)
        if run.command.parent_run_id or command.invocation_mode == "plan" or key_id is not None or admitted.shell == "deny":
            return None
        async def authorize(request, request_context):
            if (request_context.actor.principal_id != user or request_context.actor.tenant_id != user
                    or request_context.actor.delegated_by):
                raise PermissionError("Only the authenticated owner can configure this Agent")
            current = await live_execution_policy(command, users=host.users, keys=host.credentials.keys,
                catalog=host.catalog_store, settings=host.settings, user_id=user, catalog_agent_id=frozen.agent.id)
            if current is None or current.shell == "deny":
                raise PermissionError("The live execution grant does not permit capability changes")
        return SelfConfigurationService(
            store=SqliteSelfConfigurationStore(host.paths.runtime_root / "self-configuration.sqlite3"),
            owner=json.dumps(["server", user, frozen.agent.id]),
            workspace_root=host.paths.workspace_dir(workspace_user(command, user), frozen.agent.id),
            workspace_alias=run.workspace_root, authorize=authorize,
            mcp_session_factory=SandboxMcpSessionFactory(run.sandbox, run.grant_issuer),
        )

    management = service_registration("agent.management", None)
    management = ExtensionRegistration(descriptor=management.descriptor,
        factory=lambda context, deps: host.agent_management, ownership="borrowed")
    return (
        management,
        run_registration("model.provider", model, dependencies=dependency),
        run_registration("skill.catalog", skills, extra=("skill.source",), dependencies=dependency),
        run_registration("tool.catalog", tools, extra=("tool.executor",), dependencies=dependency),
        run_registration("agent.tool-policy", policy, dependencies=dependency),
        run_registration("agent.self-configuration", self_configuration, dependencies=dependency),
    )


def run_selections(*, owner, composition=None, mcp=(), a2a=()):
    import hashlib
    config = {"owner": owner,
              "mcp_fingerprints": {record.name: hashlib.sha256(record.model_dump_json().encode()).hexdigest() for record in mcp},
              "a2a_fingerprints": {record.name: hashlib.sha256(record.model_dump_json().encode()).hexdigest() for record in a2a}}
    if composition is not None:
        config["composition"] = composition
    choices = {name: CapabilitySelection(plugin="com.sage.server.run." + name.replace(".", "-"), scope="run", config=config)
               for name in ("model.provider", "skill.catalog", "agent.tool-policy", "agent.self-configuration")}
    choices["agent.management"] = service_selection("agent.management")
    choices["tool.catalog"] = (CapabilitySelection(plugin="sage.tool.official"),
        CapabilitySelection(plugin="com.sage.server.run.tool-catalog", scope="run", config=config, grant_tools=True))
    return choices


# Product defaults expressed as standard execution.binding policy parameters.
# An explicit process field in plugin_overrides replaces its product default.
SERVER_PROCESS_DEFAULTS = {
    "enabled": True, "allow_shell": True,
    "allowed_executables": ["bash", "sh", "python", "python3", "rg", "git", "node", "sage-frontend-test"],
    "allowed_env_names": ["PATH", "PYTHONPATH", "NODE_PATH", "PLAYWRIGHT_BROWSERS_PATH",
        "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD", "FONTCONFIG_FILE", "npm_config_offline", "npm_config_update_notifier"],
    "max_wall_time_seconds": 300, "max_output_bytes": 4 * 1024**2,
}


def execution_selection(host, *, owner, agent_id, command, sandbox, settings=None):
    from app.v2.server.runtime.official import agent_network_policy
    from app.v2.server.storage.workspaces import workspace_user
    from sagents.v2.runtime.execution.configuration import LocalExecutionPolicy
    from sagents.v2.runtime.execution.sandbox import FileOperation
    settings = settings or host.settings
    raw = dict(settings.plugin_overrides.get("execution.binding", {}).get("config", {}))
    configured_policy = raw.pop("policy", {})
    policy = LocalExecutionPolicy.model_validate({
        **configured_policy,
        "process": {**SERVER_PROCESS_DEFAULTS, **configured_policy.get("process", {})},
        "network": agent_network_policy(sandbox, settings).model_dump(mode="json"),
    })
    if command is not None and command.invocation_mode == "plan":
        policy = policy.narrow({"filesystem": {"allowed_operations": [FileOperation.READ, FileOperation.LIST]},
                                "process": {"read_only": True}})
    workspace_owner = workspace_user(command, owner) if command is not None else owner
    return CapabilitySelection(plugin="sage.execution.binding.local-workspace", config={
        "workspace": str(host.paths.workspace_dir(workspace_owner, agent_id)),
        "private_workspace_root": str(host.paths.workspace_dir(workspace_owner, agent_id).parent / ".sage-private-workspaces"),
        "policy": policy.model_dump(mode="json"),
        "linux_execution_uid": settings.linux_execution_uid,
        "linux_execution_gid": settings.linux_execution_gid,
        **raw,
        # Product contract: Linux tenants always see /workspace. Desktop uses
        # the same SDK binding without this explicit mount alias.
        "workspace_alias": "/workspace",
    })


def select_run_capabilities(base, package_runtime, product):
    """Preserve authorized package implementations while adding product tools."""
    from sagents.v2.package.manifest.runtime import merge_capability_selections
    choices = merge_capability_selections(base, package_runtime.capabilities)
    for capability, selection in product.items():
        if capability in {"model.provider", "skill.catalog"} and package_runtime.selections(capability):
            continue
        if capability == "tool.catalog":
            declared = package_runtime.selections(capability)
            if declared:
                external = selection[-1]
                choices[capability] = (*declared, external) if all(item.plugin != external.plugin for item in declared) else declared
                continue
        choices[capability] = selection
    return choices

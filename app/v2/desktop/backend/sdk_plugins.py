"""Desktop product capabilities registered with the standard Sage SDK.

Factories receive authenticated Run resources and frozen package inputs. Sage
owns execution, sandbox leases, tool assembly and all scope cleanup.
"""
from __future__ import annotations

import json

from sagents.v2.agent.policy import ApprovalStrategy, DefaultToolPolicy
from sagents.v2.package.manifest.runtime import CapabilitySelection
from sagents.v2.runtime.extensions import (
    CapabilityOffer, ExtensionDependency, ExtensionDescriptor, ExtensionRegistration,
    ExtensionScope,
)


class DesktopPurposeModel:
    def __init__(self, primary, auxiliary):
        self.primary, self.auxiliary = primary, auxiliary

    async def capabilities(self, binding):
        return await self.primary.capabilities(binding)

    async def probe_capabilities(self, request):
        return await self.primary.probe_capabilities(request)

    def _provider(self, request):
        return self.auxiliary if request.metadata.get("purpose") in {
            "continuation_judge", "memory_recall_query", "tool_selection",
        } else self.primary

    async def diagnostic_request(self, request):
        import inspect
        method = getattr(self._provider(request), "diagnostic_request", None)
        result = method(request) if method is not None else None
        return await result if inspect.isawaitable(result) else result

    async def stream(self, request):
        stream = self._provider(request).stream(request)
        try:
            async for event in stream:
                yield event
        finally:
            await stream.aclose()


async def desktop_run_inputs(service, context, dependencies):
    run = dependencies.require("execution.environment")
    user_id = run.context.actor.principal_id
    if run.context.actor.tenant_id != user_id:
        raise PermissionError("Desktop Run owner and tenant must match")
    environment = await service._environment_for_command(run.command, user_id, run.run_id)
    if environment is None:
        raise ValueError("Run has no recoverable standard Desktop configuration")
    agent_id = context.agent_configuration["definition"].get("source_agent_id") or context.agent_id
    agent = environment.agents.get(agent_id)
    if agent is None:
        # External package aliases are resolved through an explicit frozen map.
        agent_id = context.config.get("agent_ids", {}).get(agent_id)
        agent = environment.agents.get(agent_id)
    if agent is None:
        raise ValueError(f"Agent is absent from the admitted Desktop catalog: {context.agent_id}")
    current = await service.catalog.get_agent(agent.agent_id, user_id)
    if current is not None and "approvedShellCommands" in current.config:
        agent = agent.model_copy(update={"config": {
            **agent.config, "approvedShellCommands": current.config["approvedShellCommands"],
        }}, deep=True)
    return run, environment, agent


def desktop_registrations(service):
    def registration(capability, factory, *, ownership="borrowed"):
        return ExtensionRegistration(
            descriptor=ExtensionDescriptor(
                plugin_id="com.sage.desktop.run." + capability.replace(".", "-"),
                name="Desktop " + capability, version="2.0.0",
                provides=(CapabilityOffer(capability=capability, api_version="2"),),
                dependencies=(ExtensionDependency(capability="execution.environment"),),
                supported_scopes=frozenset({ExtensionScope.RUN}), default_scope=ExtensionScope.RUN,
                config_schema={"type": "object", "additionalProperties": False},
            ), factory=factory, ownership=ownership,
        )

    async def model(context, deps):
        _, environment, agent = await desktop_run_inputs(service, context, deps)
        return DesktopPurposeModel(
            await service._model_provider(environment.provider(agent), agent),
            await service._model_provider(environment.provider(agent, fast=True), agent, enable_thinking=False),
        )

    async def skills(context, deps):
        _, _, agent = await desktop_run_inputs(service, context, deps)
        return service._skill_provider(agent)

    async def tools(context, deps):
        from sagents.v2.tool import CompositeToolCatalog, CompositeToolExecutor, FilteredToolCatalog
        from sagents.v2.tool.plugins.ephemeral import InMemoryToolCatalog, InMemoryToolExecutor
        run, environment, agent = await desktop_run_inputs(service, context, deps)
        declared = set(context.agent_configuration["definition"]["tools"])
        if run.command.config.enabled_tools is not None:
            declared.intersection_update(run.command.config.enabled_tools)
        mcp_catalog = FilteredToolCatalog(environment.mcp, declared)
        providers = [type("Ports", (), {"catalog": mcp_catalog, "executor": environment.mcp})()]
        binding = await service.studio_run_binding(run.run_id, agent, run.command.session_id)
        if binding:
            studio = service.studio_tool_provider(run.run_id, agent.user_id, binding)
            providers.append(type("Ports", (), {"catalog": studio, "executor": studio})())
        class Tools:
            catalog = CompositeToolCatalog(tuple(value.catalog for value in providers)) if providers else InMemoryToolCatalog(())
            executor = CompositeToolExecutor(tuple(value.executor for value in providers)) if providers else InMemoryToolExecutor({}, {})
        return Tools()

    async def policy(context, deps):
        from .shell_policy import ShellCommandOperationAssessor
        run, _, agent = await desktop_run_inputs(service, context, deps)
        return DefaultToolPolicy(
            approval_strategy=ApprovalStrategy(run.command.config.metadata.get("approval_mode") or "high_risk"),
            operation_assessor=ShellCommandOperationAssessor(
                agent.config.get("commandPolicy"), agent.config.get("approvedShellCommands") or (),
            ), operation_assessor_id="v2-desktop-shell-policy",
        )

    async def output_checker(context, deps):
        from .openui_completion import OpenUiOutputChecker
        return OpenUiOutputChecker(service.openui_parser)

    async def context_provider(context, deps):
        from .openui import OpenUiContextProvider
        from .run_context import PreferredSkillsContextProvider
        from .studio import StudioContextProvider
        run, _, agent = await desktop_run_inputs(service, context, deps)
        providers = [OpenUiContextProvider(), PreferredSkillsContextProvider()]
        binding = await service.studio_run_binding(run.run_id, agent, run.command.session_id)
        if binding:
            providers.append(StudioContextProvider(service.studio_store, agent.user_id, binding,
                                                 refresh=service.reconcile_studio_results))
        class Context:
            async def segments(self, command, *, run_id=None):
                segments = []
                for provider in providers:
                    segments.extend(await provider.segments(command, run_id=run_id))
                return tuple(segments)
        return Context()

    async def self_configuration(context, deps):
        from sagents.v2.agent.self_configuration import SelfConfigurationService, SqliteSelfConfigurationStore
        from sagents.v2.tool.plugins.sandbox_mcp import SandboxMcpSessionFactory
        run, environment, agent = await desktop_run_inputs(service, context, deps)
        if run.command.parent_run_id or run.command.invocation_mode == "plan":
            return None
        async def authorize(request, request_context):
            if (request_context.actor.principal_id != agent.user_id
                    or request_context.actor.tenant_id != agent.user_id
                    or request_context.actor.delegated_by):
                raise PermissionError("Only the Agent owner can change its capabilities")
        return SelfConfigurationService(
            store=SqliteSelfConfigurationStore(service.runtime_root / "self-configuration.sqlite3"),
            owner=json.dumps(["desktop", agent.user_id, agent.agent_id]),
            workspace_root=environment.workspace, workspace_alias=run.workspace_root,
            authorize=authorize,
            mcp_session_factory=SandboxMcpSessionFactory(run.sandbox, run.grant_issuer,
                                                       workspace_root=run.workspace_root),
        )

    budget = ExtensionRegistration(
        descriptor=ExtensionDescriptor(plugin_id="com.sage.desktop.model-budget", name="Desktop model budget", version="2",
            provides=(CapabilityOffer(capability="execution.model-budget", api_version="2"),),
            supported_scopes=frozenset({ExtensionScope.PROCESS}),
            config_schema={"type": "object", "additionalProperties": False}),
        factory=lambda context, deps: service.model_budget, ownership="borrowed",
    )
    return (
        budget,
        registration("model.provider", model),
        registration("skill.provider", skills),
        registration("tool.provider", tools),
        registration("agent.tool-policy", policy),
        registration("context.segment-provider", context_provider),
        registration("agent.output-checker", output_checker),
        registration("agent.self-configuration", self_configuration),
    )


def desktop_run_selections():
    return {"execution.model-budget": CapabilitySelection(plugin="com.sage.desktop.model-budget"), **{capability: CapabilitySelection(
        plugin="com.sage.desktop.run." + capability.replace(".", "-"), scope=ExtensionScope.RUN,
    ) for capability in (
        "model.provider", "skill.provider", "agent.tool-policy", "context.segment-provider",
        "agent.output-checker", "agent.self-configuration",
    )}}

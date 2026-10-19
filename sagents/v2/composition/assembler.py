"""Build one application from explicit options; owns initial plugin and Agent wiring."""

from __future__ import annotations

import hashlib
import inspect
import json
from functools import partial
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sagents.v2.agent.modes import ModeAwareAgentLoopFactory
from sagents.v2.agent.multi_agent import (
    AgentDescriptor,
    AgentMode,
    AgentRegistry,
    AgentRosterContextProvider,
    DelegationConcurrencyLimiter,
    WorkspaceSharingPolicy,
)
from sagents.v2.application import SAgentApplication
from sagents.v2.composition.bound_tools import BoundToolComposer
from sagents.v2.composition.agent_components import AgentComponents
from sagents.v2.composition.contracts import (
    ResolvedApplicationPlan,
    ResolvedProviderBinding,
)
from sagents.v2.composition.drivers import (
    _CompositeRunResource,
    _ExecutionBoundDriver,
)
from sagents.v2.composition.identity import _service_composition_identity
from sagents.v2.composition.state import AssemblyState
from sagents.v2.composition.providers import open_provider
from sagents.v2.composition.resolution import (
    _merge_plugin_config,
    _selection,
    _supported_locked_config,
    _validate_declared_plugin_trust,
)
from sagents.v2.composition.resolution import _resolve_package as resolve_package
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.context.sandbox_environment import SandboxEnvironmentContextProvider
from sagents.v2.goal import GoalStateService
from sagents.v2.interfaces.protocols.native import NativeProtocolAdapter
from sagents.v2.memory import (
    MemoryProvider,
    MemoryService,
    NoopMemoryProvider,
)
from sagents.v2.model import RecordingModelProvider
from sagents.v2.model.protocols import model_protocol_descriptor
from sagents.v2.package.manifest.resolver import (
    CompositionResolver,
    ResolvedSageManifest,
)
from sagents.v2.package.manifest.root import PluginDeclaration, SageManifest
from sagents.v2.package.manifest.runtime import RuntimeConfig
from sagents.v2.package.registry import InMemoryAgentPackageRegistry
from sagents.v2.runtime import HarnessRuntime
from sagents.v2.runtime.artifact import SessionArtifactStore
from sagents.v2.runtime.artifact.binding import bind_artifact_store
from sagents.v2.runtime.credentials import CredentialRef, EnvironmentCredentialProvider
from sagents.v2.runtime.execution import (
    ExecutionBindingRequest,
    LocalWorkerDispatcher,
    RunExecutionBinding,
)
from sagents.v2.runtime.execution.dispatcher import DEFAULT_LEASE_SECONDS
from sagents.v2.runtime.execution.environment import RunExecutionEnvironment, _bind_execution_environment
from sagents.v2.runtime.execution.jobs import InMemoryJobRuntime
from sagents.v2.runtime.execution.scheduler import InMemoryScheduler
from sagents.v2.runtime.extensions import (
    ExtensionHost,
    ExtensionRegistry,
    ExtensionScope,
    ExtensionScopeContext,
    validate_extension_version,
)
from sagents.v2.runtime.observability import (
    NoopDiagnosticSink,
    NoopLogSink,
    NoopTraceSink,
    StructuredLogger,
)
from sagents.v2.runtime.session import (
    AuthorizedSessionAccess,
    FilesystemSessionStore,
    LeaseFencedSessionStore,
    SessionStore,
)
from sagents.v2.sagent import SAgent
from sagents.v2.session_memory import (
    NoopSessionMemoryProvider,
    SessionMemoryProvider,
    SessionMemoryService,
    SqliteBm25SessionMemoryProvider,
)
from sagents.v2.tool import (
    ToolSelectionPolicy,
)
from sagents.v2.tool.official import OfficialToolRuntime
from sagents.v2.tool.plugins.ephemeral import (
    InMemoryToolCatalog,
    InMemoryToolExecutor,
)
from sagents.v2.tool.plugins.official import OfficialToolPlugin
from sagents.v2.tool.plugins.selection_llm import LLMToolSelectionPolicy
from sagents.v2.workspace import BareWorkspaceInitializer

_DISTRIBUTED_PROFILE_GUARANTEES: dict[str, dict[str, Any]] = {
    "session.store": {
        "durable_across_process_restart": True,
        "multi_process_writes": True,
        "cross_process_subscribe": True,
        "transactional_outbox": True,
        "atomic_session_cas": True,
    },
    "execution.scheduler": {
        "durable_across_process_restart": True,
        "supports_distributed_claims": True,
        "supports_fencing": True,
        "supports_atomic_fenced_mutations": True,
        "supports_atomic_tenant_quota": True,
    },
    "execution.job-runtime": {
        "durable_across_process_restart": True,
        "supports_reconnect": True,
        "supports_adoption": True,
    },
    "tool.executor": {
        "durable_operation_ledger": True,
        "supports_restart_reconciliation": True,
    },
    "artifact.store": {
        "durable_across_process_restart": True,
        "shared_across_processes": True,
    },
    "package.registry": {
        "durable_across_process_restart": True,
        "shared_across_processes": True,
        "supports_package_signatures": True,
    },
}


class ApplicationAssembler:
    def __init__(self, state: AssemblyState, extensions: ExtensionRegistry, *, model_resolver=None, scope_pool=None,
                 shared_process_handles=()) -> None:
        self.model_resolver = model_resolver
        self.scope_pool = scope_pool
        self.state = state
        self.extensions = extensions
        self._provider_handles = {}
        self._provider_locks = {}
        self._shared_handles = tuple(shared_process_handles)

    async def assemble(
        self,
        package: SageManifest | ResolvedSageManifest | str | Path,
        *,
        tenant_id: str | None,
        agent_id: str | None,
        scope_handles: list,
        runtime: RuntimeConfig | None = None,
    ) -> SAgentApplication:

        manifest, resolved = resolve_package(package, runtime=runtime)
        self._agent_configurations = {
            name: {"definition": definition.model_dump(mode="json"),
                   "model_routes": {binding: resolved.model_routes[route]
                                    for binding, route in definition.model_bindings.items()},
                   "package_id": definition.source_package_id or resolved.package_id,
                   "scope_agent_id": definition.source_package_id or resolved.package_id,
                   "execution_agent_id": name, "manifest_hash": resolved.manifest_hash}
            for name, definition in resolved.agents.items()
        }
        plugin_declarations = (
            manifest.plugins if manifest is not None else resolved.plugins
        )
        runtime_config = manifest.runtime if manifest is not None else resolved.runtime
        self._runtime_config = runtime_config
        self.extensions.validate_runtime(runtime_config)
        self._load_declared_plugins(
            plugin_declarations,
            trust_policy=runtime_config.plugin_trust_policy,
        )
        extension_host = ExtensionHost(
            self.extensions,
            built_in_only=runtime_config.plugin_trust_policy == "built_in_only",
        )
        process_root = await extension_host.open_scope(
            ExtensionScopeContext(
                scope=ExtensionScope.PROCESS,
                scope_id=f"application-{resolved.package_id}",
            ),
            extension_host.plan(()),
        )
        scope_handles.append(process_root)
        binding_selection = _selection(runtime_config, "execution.binding")
        if binding_selection is not None:
            if self.state.execution_binding_provider is not None:
                raise ValueError("execution.binding has conflicting configuration sources")
            self.state.execution_binding_provider = await self._create_capability(
                extension_host, process_root, scope_handles, runtime_config,
                plugin_declarations, capability="execution.binding",
                default_plugin=binding_selection.plugin,
            )
        uses_binding_tools = (
            self.state.execution_binding_provider is not None
        )
        selected_agent = agent_id or resolved.entrypoint_agent
        if selected_agent is None:
            raise ValueError("SAgentBuilder requires an Agent entrypoint")
        if selected_agent not in resolved.agents:
            raise ValueError(f"unknown Agent entrypoint {selected_agent!r}")
        for definition in resolved.agents.values():
            if (
                definition.entrypoint.type == "loop"
                and definition.entrypoint.loop != "react"
            ):
                raise ValueError(
                    "SAgentBuilder supports the react loop; custom loops require a host driver"
                )
        uses_flow = resolved.agents[selected_agent].entrypoint.type == "flow"
        if uses_flow:
            available_flow_tools = set({}) | {
                selection.name for selection in runtime_config.selections("flow.node")
            }
            from sagents.v2.flow.reachability import reachable_nodes

            flow_nodes = reachable_nodes(
                resolved.flows, resolved.agents[selected_agent].entrypoint.flow
            )
            for _, node in flow_nodes:
                if node.type == "tool" and node.tool not in available_flow_tools:
                    raise ValueError(
                        f"Flow tool node {node.tool!r} requires a registered flow.node selection"
                    )
                if (
                    node.type == "agent"
                    and resolved.agents[node.agent].entrypoint.type == "flow"
                ):
                    raise ValueError(
                        "nested Flow agents must use explicit subflow nodes"
                    )
        if (any(selection.plugin == OfficialToolPlugin.plugin_id
                for selection in runtime_config.selections("tool.catalog"))
                and self.state.execution_binding_provider is None):
            raise ValueError("sage.tool.official requires a selected execution.binding capability")
        session_store = await self._create_session_store(
            extension_host, process_root, scope_handles, runtime_config, plugin_declarations,
        )
        derived_state = None
        if _selection(runtime_config, "derived-state.store") is not None:
            if derived_state is not None:
                raise ValueError("derived-state.store has conflicting configuration sources")
            derived_state = await self._create_capability(
                extension_host, process_root, scope_handles, runtime_config,
                plugin_declarations, capability="derived-state.store",
                default_plugin="sage.derived-state.session",
            )
        if derived_state is None:
            # Built-in Session stores explicitly provide colocated derived data.
            # A host-injected authoritative store is not assumed to do so.
            selected_store = _selection(runtime_config, "session.store")
            builtin_colocated = selected_store is None or self.extensions.is_trusted_builtin(selected_store.plugin)
            derived_state = await self._create_capability(
                extension_host, process_root, scope_handles, runtime_config,
                plugin_declarations, capability="derived-state.store",
                default_plugin=("sage.derived-state.session" if builtin_colocated
                                else "sage.derived-state.ephemeral"),
            )
        # 审批记忆默认落在会话派生状态：非权威、可重建、随 Session 删除清理。
        approval_memory = await self._create_capability(
            extension_host, process_root, scope_handles, runtime_config, plugin_declarations,
            capability="agent.approval-memory", default_plugin="sage.agent.approval-memory.session",
        )
        credential_provider = await self._create_capability(
            extension_host,
            process_root,
            scope_handles,
            runtime_config,
            plugin_declarations,
            capability="credentials.provider",
            default_plugin=EnvironmentCredentialProvider.plugin_id,
            default_config={"declarations": resolved.credentials},
            default_scope=ExtensionScope.PROCESS,
        )
        services, adapters = await self._create_application_services(
            extension_host,
            process_root,
            scope_handles,
            runtime_config,
            plugin_declarations,
            resolved,
            session_store=session_store,
            credential_provider=credential_provider,
        )
        policy_selection = _selection(runtime_config, "agent.tool-policy")
        if policy_selection is not None:
            if self.state.tool_policy is not None:
                raise ValueError("agent.tool-policy has conflicting configuration sources")
            self.state.tool_policy = await self._create_capability(
                extension_host, process_root, scope_handles, runtime_config,
                plugin_declarations, capability="agent.tool-policy",
                default_plugin=policy_selection.plugin,
                default_scope=ExtensionScope.AGENT, tenant_id=tenant_id,
                agent_id=selected_agent,
            )
        management_selection = _selection(runtime_config, "agent.management")
        if management_selection is not None:
            from sagents.v2.tool.plugins.agent_management import AgentManagementToolPlugin
            if self.state.agent_management is not None:
                raise ValueError("agent.management has conflicting configuration sources")
            management = await self._create_capability(
                extension_host, process_root, scope_handles, runtime_config,
                plugin_declarations, capability="agent.management",
                default_plugin=management_selection.plugin,
                default_scope=ExtensionScope.PROCESS,
            )
            self.state.agent_management = AgentManagementToolPlugin(management)
        memory_provider = await self._create_memory_provider(
            extension_host,
            process_root,
            scope_handles,
            runtime_config,
            plugin_declarations,
        )
        memory_behavior = resolved.agents[selected_agent].memory
        memory_enabled = "search_memory" in resolved.agents[selected_agent].tools
        memory_service = MemoryService(
            memory_provider,
            scope_mode=memory_behavior.scope,
            session_store=session_store,
        )
        session_memory_provider = await self._create_session_memory_provider(
            extension_host,
            process_root,
            scope_handles,
            runtime_config,
            plugin_declarations,
        )
        session_memory_service = SessionMemoryService(session_memory_provider)
        model = (
            None
        )
        if model is None:
            model = await self._create_model(
                extension_host,
                process_root,
                scope_handles,
                resolved,
                selected_agent,
                plugin_declarations,
                credential_provider,
                tenant_id=tenant_id,
            )
        models_by_agent = {selected_agent: model}
        selected_definition = resolved.agents[selected_agent]
        if uses_flow:
            from sagents.v2.flow.reachability import reachable_agents

            composition_members = reachable_agents(
                resolved.agents, flow_nodes, selected_agent
            )
        else:
            reachable = {selected_agent}
            pending = list(selected_definition.subagents)
            while pending:
                member_id = pending.pop()
                if member_id not in reachable:
                    reachable.add(member_id)
                    pending.extend(resolved.agents[member_id].subagents)
            composition_members = tuple(
                member_id for member_id in resolved.agents
                if member_id in reachable and member_id != selected_agent
            )
        for member_id in composition_members:
            if member_id in models_by_agent:
                continue
            member_model = (
                await self._create_model(
                    extension_host,
                    process_root,
                    scope_handles,
                    resolved,
                    member_id,
                    plugin_declarations,
                    credential_provider,
                    tenant_id=tenant_id,
                )
            )
            models_by_agent[member_id] = member_model

        memory_services_by_agent = {
            member_id: MemoryService(
                memory_provider,
                scope_mode=resolved.agents[member_id].memory.scope,
                session_store=session_store,
            )
            for member_id in models_by_agent
        }
        memory_service = memory_services_by_agent[selected_agent]

        standard_skills = _selection(runtime_config, "skill.catalog") is not None

        if _selection(runtime_config, "execution.model-budget") is not None:
            if self.state.model_budget is not None:
                raise ValueError("execution.model-budget has conflicting configuration sources")
            self.state.model_budget = await self._create_capability(
                extension_host, process_root, scope_handles, runtime_config,
                plugin_declarations, capability="execution.model-budget",
                default_plugin="sage.model.concurrency-budget",
            )
        if self.state.model_budget is not None:
            models_by_agent = {
                key: self.state.model_budget.wrap(provider)
                for key, provider in models_by_agent.items()
            }

        async def resolve_session_id(run_id: str) -> str:
            return (await session_store.get_run(run_id)).session_id

        diagnostic_sink = services["observability.diagnostic-sink"]
        log_sink = services["observability.log-sink"]
        trace_sink = services["observability.trace-sink"]
        models_by_agent = {
            member_id: (
                provider
                if isinstance(provider, RecordingModelProvider)
                else RecordingModelProvider(
                    provider,
                    sink=diagnostic_sink,
                    trace_sink=trace_sink,
                    log_sink=log_sink,
                    session_id_resolver=resolve_session_id,
                    provider_metadata={"agent_id": member_id},
                )
            )
            for member_id, provider in models_by_agent.items()
        }
        tool_selection = (
            await self._create_tool_selection(
                extension_host,
                process_root,
                scope_handles,
                runtime_config,
                plugin_declarations,
                tenant_id=tenant_id,
                agent_id=selected_agent,
            )
        )
        if (
            self.state.execution_binding_provider is not None
        ):
            # The real provider pair is composed lazily from the actual Run
            # binding. These placeholders are never exposed to that driver.
            tool_catalog = InMemoryToolCatalog(())
            tool_executor = InMemoryToolExecutor({}, {})
        else:
            tool_catalog = InMemoryToolCatalog(())
            tool_executor = InMemoryToolExecutor({}, {})
        readiness = None
        if self.state.check_readiness:
            from sagents.v2.agent.management.readiness import resource_readiness

            selections = runtime_config.selections("tool.catalog")
            discoverable = tuple(choice for choice in selections
                if self._selection_scope(choice, ExtensionScope.AGENT) != ExtensionScope.RUN
                and (tenant_id is not None or self._selection_scope(choice, ExtensionScope.AGENT) == ExtensionScope.PROCESS))
            discovery_runtime = runtime_config.model_copy(update={"capabilities": {
                **runtime_config.capabilities, "tool.catalog": discoverable,
            }})
            discovery_catalog, _ = await self._create_tools(
                extension_host, process_root, scope_handles, discovery_runtime, plugin_declarations,
                tenant_id=tenant_id, agent_id=selected_agent,
            )
            discovery_skills = None
            skill_choice = _selection(runtime_config, "skill.catalog")
            if skill_choice is not None and self._selection_scope(skill_choice, ExtensionScope.AGENT) != ExtensionScope.RUN:
                skill_catalog = await self._create_capability(
                    extension_host, process_root, scope_handles, runtime_config, plugin_declarations,
                    capability="skill.catalog", default_plugin=skill_choice.plugin,
                    default_scope=ExtensionScope.AGENT, tenant_id=tenant_id, agent_id=selected_agent,
                )
                from sagents.v2.composition.providers import DeferredRunCapability
                if not isinstance(skill_catalog, DeferredRunCapability):
                    discovery_skills = (skill_catalog, None, None)
            reports = {}
            for member_id in models_by_agent:
                reports[member_id] = await resource_readiness(
                    resolved.agents[member_id],
                    discovery_catalog,
                    skill_provider=discovery_skills,
                    management=self.state.agent_management,
                    deferred_tools=uses_binding_tools or len(discoverable) != len(selections),
                )
            readiness = {
                "ready": all(report["ready"] for report in reports.values()),
                "agents": reports,
            }
        scheduler = services["execution.scheduler"]
        scheduler_capabilities = await scheduler.capabilities()
        if (
            not scheduler_capabilities.supports_fencing
            or not scheduler_capabilities.supports_atomic_fenced_mutations
            or not callable(getattr(scheduler, "execute_fenced", None))
        ):
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="scheduler.atomic_fence_unsupported",
                    category=ErrorCategory.UNSUPPORTED_SCHEMA,
                    message=(
                        "the selected Scheduler plugin must keep a validated "
                        "worker lease authoritative across each Session mutation"
                    ),
                )
            )
        driver_session_store = LeaseFencedSessionStore(session_store, scheduler)
        goal_state_service = GoalStateService(driver_session_store)
        control_runtime = HarnessRuntime(
            session_store,
            job_runtime=services["execution.job-runtime"],
            execution_binding_provider=self.state.execution_binding_provider,
            derived_state_store=derived_state,
        )
        driver_runtime = HarnessRuntime(
            driver_session_store,
            job_runtime=services["execution.job-runtime"],
            execution_binding_provider=self.state.execution_binding_provider,
            derived_state_store=derived_state,
        )

        # Selection/scope ownership belongs to the application; the Agent graph
        # only receives the opener and the runtime ports it actually consumes.
        open_agent_capability = partial(
            self._create_capability,
            extension_host,
            process_root,
            scope_handles,
            runtime_config,
            plugin_declarations,
            default_scope=ExtensionScope.AGENT,
            tenant_id=tenant_id,
        )
        component_sets = {}
        for member_id, model in models_by_agent.items():
            component_sets[member_id] = await AgentComponents.compose(
                open_capability=open_agent_capability,
                agent_id=member_id,
                model=model,
                runtime=driver_runtime,
                derived_state=derived_state,
            )
        root_components = component_sets[selected_agent]
        # Selecting a plugin is executable configuration, including auxiliary
        # capabilities consumed by other plugins. Never silently ignore a
        # selected service merely because the core loop has no direct consumer.
        for capability in runtime_config.capabilities:
            if capability in {"tool.catalog", "tool.executor", "skill.catalog", "skill.workspace", "flow.node",
                              "context.segment-provider", "agent.self-configuration", "agent.output-checker", "interface.protocol-adapter"}:
                continue
            for selection in runtime_config.selections(capability):
                descriptor = self.extensions.get(selection.plugin).descriptor
                scope = self._selection_scope(selection, ExtensionScope.PROCESS)
                if scope == ExtensionScope.RUN:
                    continue
                if any(selection.plugin in handle.graph.plugin_ids
                       and any(offer.capability == capability for offer in descriptor.provides)
                       for handle in scope_handles):
                    continue
                selected_runtime = runtime_config.model_copy(update={"capabilities": {
                    **runtime_config.capabilities, capability: selection,
                }})
                services[capability] = await self._create_capability(
                    extension_host, process_root, scope_handles, selected_runtime, plugin_declarations,
                    capability=capability, default_plugin=selection.plugin, default_scope=scope,
                    tenant_id=tenant_id, agent_id=selected_agent,
                )
        flow_tool_nodes = dict({})
        if uses_flow:
            for selection in runtime_config.selections("flow.node"):
                if selection.name in flow_tool_nodes:
                    raise ValueError(f"duplicate Flow node binding {selection.name!r}")
                descriptor = self.extensions.get(selection.plugin).descriptor
                node_scope = selection.scope or descriptor.resolved_default_scope()
                if node_scope == ExtensionScope.RUN:
                    continue
                config = _merge_plugin_config(
                    plugin_declarations, selection.plugin, dict(selection.config)
                )
                flow_tool_nodes[selection.name] = await self._instantiate(
                    extension_host,
                    process_root,
                    scope_handles,
                    selection.plugin,
                    config,
                    "flow.node",
                    scope=node_scope,
                    scope_id=f"flow-node-{selected_agent}-{selection.name}",
                    tenant_id=tenant_id,
                    agent_id=selected_agent,
                    offer_name=selection.name,
                )
        root_descriptor = AgentDescriptor(
            agent_id=selected_agent,
            name=selected_definition.name,
            description="",
            instructions=selected_definition.instructions,
            mode=AgentMode(selected_definition.mode),
            tools=selected_definition.tools,
            skills=selected_definition.skills,
            preload_skills=selected_definition.preload_skills,
            declared_subagents=selected_definition.subagents,
        )
        member_descriptors = tuple(
            AgentDescriptor(
                agent_id=member_id,
                name=resolved.agents[member_id].name,
                description="",
                instructions=resolved.agents[member_id].instructions,
                mode=AgentMode(resolved.agents[member_id].mode),
                tools=resolved.agents[member_id].tools,
                skills=resolved.agents[member_id].skills,
                preload_skills=resolved.agents[member_id].preload_skills,
                declared_subagents=resolved.agents[member_id].subagents,
                allow_delegation=(
                    resolved.agents[member_id].mode == "team"
                    and bool(resolved.agents[member_id].subagents)
                ),
            )
            for member_id in composition_members
        )

        bound_tools = BoundToolComposer(
            open_tools=partial(
                self._create_tools,
                extension_host,
                process_root,
                scope_handles,
                runtime_config,
                plugin_declarations,
                return_handle=True,
                scope_override=ExtensionScope.RUN,
            ),
            workspace_initializer=services["workspace.initializer"],
            artifact_store=services["artifact.store"],
            job_runtime=services["execution.job-runtime"],
            memory_services=memory_services_by_agent,
            default_memory_service=memory_service,
            session_memory_service=session_memory_service,
            goal_state_service=goal_state_service,
            tool_selection=tool_selection,
        )

        delegation_limiter = DelegationConcurrencyLimiter(
            max_concurrency=8,
            max_per_tenant=2,
        )
        runtime_composition_hash: str | None = None

        def register_dynamic_configuration(descriptor):
            if descriptor.agent_id in self._agent_configurations:
                return
            root = self._agent_configurations[selected_agent]
            self._agent_configurations[descriptor.agent_id] = {
                **root,
                "scope_agent_id": f"{resolved.package_id}:{descriptor.agent_id}",
                "execution_agent_id": descriptor.agent_id,
                "definition": {**root["definition"],
                               "name": descriptor.name,
                               "instructions": descriptor.instructions,
                               "tools": list(descriptor.tools),
                               "skills": list(descriptor.skills)},
            }

        async def make_loop(
            run_id,
            selected_catalog,
            selected_executor,
            continuation_runtime: OfficialToolRuntime | None,
            entry_descriptor=root_descriptor,
            *, available_scopes=(),
        ):
            owned = []
            try:
                async def open_active_capability(**kwargs):
                    value, handle = await self._create_capability(
                        extension_host, process_root, scope_handles, runtime_config,
                        plugin_declarations, default_scope=ExtensionScope.AGENT,
                        tenant_id=active_tenant, run_id=run_id, return_handle=True, available=(*available_scopes, *owned),
                        **kwargs,
                    )
                    if handle is not None and handle.context.scope == ExtensionScope.RUN:
                        scope_handles.remove(handle)
                        owned.append(handle)
                    return value

                active_context = await session_store.get_run_context(run_id)
                active_command = await session_store.get_start_command(run_id)
                active_tenant = tenant_id or active_context.actor.tenant_id
                run_models = dict(models_by_agent)
                if entry_descriptor.agent_id not in run_models:
                    run_models[entry_descriptor.agent_id] = run_models[selected_agent]
                    register_dynamic_configuration(entry_descriptor)
                model_selection = _selection(runtime_config, "model.provider")
                if model_selection is not None and (
                        self._selection_scope(model_selection, ExtensionScope.AGENT) == ExtensionScope.RUN
                        or tenant_id is None and self._selection_scope(model_selection, ExtensionScope.AGENT) != ExtensionScope.PROCESS):
                    model = await self._create_model(
                        extension_host, process_root, scope_handles, resolved,
                        entry_descriptor.agent_id, plugin_declarations, credential_provider,
                        tenant_id=active_tenant, run_id=run_id, return_handle=True, available=(*available_scopes, *owned),
                    )
                    model, model_scope = model
                    if model_scope.context.scope == ExtensionScope.RUN:
                        scope_handles.remove(model_scope)
                        owned.append(model_scope)
                    if self.state.model_budget is not None:
                        model = self.state.model_budget.wrap(model)
                    run_models[entry_descriptor.agent_id] = RecordingModelProvider(
                        model, sink=diagnostic_sink, trace_sink=trace_sink, log_sink=log_sink,
                        session_id_resolver=resolve_session_id,
                        provider_metadata={"agent_id": entry_descriptor.agent_id},
                    )
                active_components = await AgentComponents.compose(
                    open_capability=open_active_capability, agent_id=entry_descriptor.agent_id,
                    model=run_models[entry_descriptor.agent_id], runtime=driver_runtime,
                    derived_state=derived_state,
                )
                active_policy = self.state.tool_policy
                policy_selection = _selection(runtime_config, "agent.tool-policy")
                if policy_selection is not None and (
                        self._selection_scope(policy_selection, ExtensionScope.AGENT) == ExtensionScope.RUN
                        or tenant_id is None and self._selection_scope(policy_selection, ExtensionScope.AGENT) != ExtensionScope.PROCESS):
                    active_policy = await open_active_capability(
                        capability="agent.tool-policy", default_plugin=policy_selection.plugin,
                        agent_id=entry_descriptor.agent_id,
                    )
                active_tool_selection = await open_active_capability(
                    capability="tool.selection-policy", default_plugin=LLMToolSelectionPolicy.plugin_id,
                    agent_id=entry_descriptor.agent_id,
                )
                active_self_configuration = None
                selection = _selection(runtime_config, "agent.self-configuration")
                if selection is not None:
                    active_self_configuration = await open_active_capability(
                        capability="agent.self-configuration", default_plugin=selection.plugin,
                        agent_id=entry_descriptor.agent_id,
                    )
                active_context_providers = []
                for selection in runtime_config.selections("context.segment-provider"):
                    selected_runtime = runtime_config.model_copy(update={"capabilities": {
                        **runtime_config.capabilities, "context.segment-provider": selection,
                    }})
                    value, handle = await self._create_capability(
                        extension_host, process_root, scope_handles, selected_runtime,
                        plugin_declarations, capability="context.segment-provider", default_plugin=selection.plugin,
                        default_scope=ExtensionScope.AGENT, agent_id=entry_descriptor.agent_id,
                        tenant_id=active_tenant, run_id=run_id, return_handle=True, available=(*available_scopes, *owned),
                    )
                    if handle.context.scope == ExtensionScope.RUN:
                        scope_handles.remove(handle)
                        owned.append(handle)
                    active_context_providers.append(value)
                active_skills = None
                if standard_skills:
                    selection = _selection(runtime_config, "skill.catalog")
                    skill_catalog, skill_scope = await self._create_capability(
                        extension_host, process_root, scope_handles, runtime_config,
                        plugin_declarations, capability="skill.catalog", default_plugin=selection.plugin,
                        default_scope=ExtensionScope.AGENT, tenant_id=active_tenant,
                        agent_id=entry_descriptor.agent_id, run_id=run_id,
                        return_handle=True, available=(*available_scopes, *owned),
                    )
                    if skill_scope.context.scope == ExtensionScope.RUN:
                        scope_handles.remove(skill_scope)
                        owned.append(skill_scope)
                    skill_workspace = None
                    selection = _selection(runtime_config, "skill.workspace")
                    if selection is not None:
                        skill_workspace = await open_active_capability(
                            capability="skill.workspace", default_plugin=selection.plugin,
                            agent_id=entry_descriptor.agent_id,
                        )
                    active_skills = (skill_catalog, skill_scope.providers.require_unique("skill.source"), skill_workspace)
                active_continuation = active_components.continuation_policy
                selection = _selection(runtime_config, "agent.output-checker")
                if selection is not None:
                    from sagents.v2.agent.policy.output_self_check import OutputSelfCheckPolicy
                    checker = await open_active_capability(
                        capability="agent.output-checker", default_plugin=selection.plugin,
                        agent_id=entry_descriptor.agent_id,
                    )
                    active_continuation = OutputSelfCheckPolicy(active_continuation, checker)
                active_flow_tool_nodes = dict(flow_tool_nodes)
                for capability in runtime_config.capabilities:
                    if capability in {"tool.catalog", "tool.executor", "skill.catalog", "skill.workspace"}:
                        continue
                    for selection in runtime_config.selections(capability):
                        if self._selection_scope(selection, ExtensionScope.AGENT) != ExtensionScope.RUN:
                            continue
                        if any(selection.plugin in handle.graph.plugin_ids for handle in owned):
                            continue
                        selected_runtime = runtime_config.model_copy(update={"capabilities": {
                            **runtime_config.capabilities, capability: selection,
                        }})
                        value, handle = await self._create_capability(
                            extension_host, process_root, scope_handles, selected_runtime,
                            plugin_declarations, capability=capability, default_plugin=selection.plugin,
                            default_scope=ExtensionScope.RUN, tenant_id=active_tenant,
                            agent_id=entry_descriptor.agent_id, run_id=run_id, return_handle=True, available=(*available_scopes, *owned),
                        )
                        scope_handles.remove(handle)
                        owned.append(handle)
                        if capability == "flow.node":
                            active_flow_tool_nodes[selection.name] = value
                # Each loop owns its direct roster. Canonical IDs retain the frozen
                # graph identity; local aliases are what its model delegates to.
                # Dynamic Fibre members cannot leak across loops or Sessions.
                descriptors = {
                    value.agent_id: value for value in (root_descriptor, *member_descriptors)
                }
                direct_ids = entry_descriptor.declared_subagents
                if uses_flow and entry_descriptor.agent_id == selected_agent:
                    direct_ids = composition_members
                prefix = entry_descriptor.agent_id + "."
                registry = AgentRegistry(
                    tuple(descriptors[member_id] for member_id in direct_ids),
                    aliases={
                        member_id.removeprefix(prefix): member_id for member_id in direct_ids
                    },
                )

                def compose_with_runtime(
                    descriptor,
                    catalog,
                    executor,
                    active_runtime: OfficialToolRuntime | None,
                ):
                    configured_catalog_grants = getattr(catalog, "runtime_grants", ())
                    if self.state.agent_management is not None:
                        from sagents.v2.tool import (
                            CompositeToolCatalog,
                            CompositeToolExecutor,
                        )

                        catalog = CompositeToolCatalog(
                            (catalog, self.state.agent_management.catalog)
                        )
                        executor = CompositeToolExecutor(
                            (executor, self.state.agent_management.executor)
                        )
                    runtime_tools = ()
                    if descriptor.allow_delegation and descriptor.mode == AgentMode.FIBRE:
                        runtime_tools = ("sys_spawn_agent", "sys_delegate_task")
                    elif descriptor.allow_delegation and descriptor.mode == AgentMode.TEAM:
                        runtime_tools = ("sys_team_delegate_task",)
                    effective_resolved = resolved
                    definition_id = descriptor.agent_id
                    if definition_id not in resolved.agents:
                        base = resolved.agents[selected_agent]
                        dynamic = base.model_copy(
                            update={
                                "name": descriptor.name,
                                "instructions": descriptor.instructions,
                                "mode": "simple",
                                "tools": descriptor.tools,
                                "skills": descriptor.skills,
                                "preload_skills": descriptor.preload_skills,
                                "subagents": (),
                            }
                        )
                        ceiling = resolved.policy_ceilings[selected_agent].model_copy(
                            update={
                                "allowed_tools": frozenset(descriptor.tools),
                                "allowed_skills": frozenset(descriptor.skills),
                            }
                        )
                        effective_resolved = resolved.model_copy(
                            update={
                                "agents": {**resolved.agents, definition_id: dynamic},
                                "policy_ceilings": {
                                    **resolved.policy_ceilings,
                                    definition_id: ceiling,
                                },
                            }
                        )
                        run_models.setdefault(definition_id, run_models[selected_agent])
                    definition = effective_resolved.agents[definition_id]
                    member_components = active_components
                    skill_loader = None
                    self_configuration = (
                        active_self_configuration
                    )
                    if (active_skills is not None) and (
                        definition.skills
                        or "load_skill" in definition.tools
                        or self_configuration is not None
                    ):
                        from sagents.v2.skill.plugins.session import (
                            SessionDerivedSkillActivationRepository,
                        )
                        from sagents.v2.tool import (
                            CompositeToolCatalog,
                            CompositeToolExecutor,
                        )
                        from sagents.v2.tool.plugins.skill import SkillToolPlugin

                        if active_skills is not None:
                            skill_catalog, skill_source, skill_workspace = active_skills
                            if skill_workspace is None and active_runtime is None:
                                raise ValueError("standard Skills require an execution.binding sandbox")
                            from sagents.v2.skill.plugins.sandbox import SandboxSkillWorkspace
                            if skill_workspace is None:
                                skill_workspace = SandboxSkillWorkspace(active_runtime.sandbox, active_runtime.grant_issuer)
                        skill_loader = member_components.factory.create_skill_loader(
                            effective_resolved,
                            definition_id,
                            catalog=skill_catalog,
                            source=skill_source,
                            workspace=skill_workspace,
                            skill_loading=member_components.skill_loading,
                            activations=SessionDerivedSkillActivationRepository(
                                derived_state,
                                resolve_session_id,
                            ),
                            **({"workspace_root": active_runtime.sandbox.filesystem.normalize_path(".")}
                               if active_skills is not None and active_runtime is not None else {}),
                        )
                        skill_tools = SkillToolPlugin(skill_loader)
                        catalog = CompositeToolCatalog((catalog, skill_tools.catalog))
                        executor = CompositeToolExecutor((executor, skill_tools.executor))
                        runtime_tools = (*runtime_tools, "load_skill")
                    member_memory_enabled = "search_memory" in definition.tools
                    return member_components.factory.create_loop(
                        effective_resolved,
                        definition_id,
                        expected_resolved_spec_hash=(
                            None
                        ),
                        memory_recall_query_generator=member_components.memory_query_generator,
                        tool_selection_model=run_models[descriptor.agent_id],
                        artifact_store=(
                            active_runtime.artifact_store
                            if active_runtime is not None
                            else bind_artifact_store(services["artifact.store"], run_id)
                        ),
                        model=run_models[descriptor.agent_id],
                        tool_catalog=catalog,
                        tool_executor=executor,
                        tool_result_runtime=active_runtime,
                        memory_service=(
                            memory_services_by_agent.get(definition_id, memory_service)
                            if member_memory_enabled and definition.memory.recall
                            else None
                        ),
                        session_memory_service=(
                            session_memory_service if member_memory_enabled else None
                        ),
                        tool_policy=active_policy,
                        approval_memory=approval_memory,
                        continuation_policy=active_continuation,
                        continuation_signal_provider=(
                            active_runtime.consume_continuation_signals
                            if active_runtime is not None
                            else None
                        ),
                        goal_state_service=goal_state_service,
                        tool_selection_policy=active_tool_selection,
                        additional_runtime_tools=runtime_tools,
                        granted_catalogs=(*configured_catalog_grants, *(
                            pair[0] for pair in ()
                        )),
                        skill_loader=skill_loader,
                        self_configuration=self_configuration,
                        additional_context_providers=(
                            *active_context_providers,
                            *((SandboxEnvironmentContextProvider(active_runtime.sandbox),)
                              if active_runtime is not None else ()),
                            AgentRosterContextProvider(
                                registry,
                                descriptor.mode,
                                allow_delegation=descriptor.allow_delegation,
                            ),
                        ),
                        trace_sink=services["observability.trace-sink"],
                        log_sink=services["observability.log-sink"],
                    )

                def compose(descriptor, child_run_id, catalog, executor):
                    del child_run_id
                    return compose_with_runtime(
                        descriptor,
                        catalog,
                        executor,
                        continuation_runtime,
                    )

                async def compose_unbound_child(descriptor, child_run_id, child_context):
                    register_dynamic_configuration(descriptor)
                    command = await driver_runtime.session_store.get_start_command(child_run_id)
                    with _bind_execution_environment(RunExecutionEnvironment(child_run_id, command, child_context)):
                        catalog, executor, tool_scope = await self._create_tools(
                            extension_host, process_root, scope_handles, runtime_config, plugin_declarations,
                            return_handle=True, tenant_id=tenant_id or child_context.actor.tenant_id,
                            agent_id=descriptor.agent_id, run_id=child_run_id,
                        )
                        try:
                            loop, scope = await make_loop(child_run_id, catalog, executor, None, descriptor,
                                available_scopes=tool_scope.provider_scopes if tool_scope is not None else ())
                        except BaseException:
                            if tool_scope is not None:
                                await tool_scope.close()
                            raise
                        return loop, _CompositeRunResource(tool_scope, scope)

                async def compose_bound_child(descriptor, child_run_id, child_context):
                    assert self.state.execution_binding_provider is not None
                    register_dynamic_configuration(descriptor)
                    command = await driver_runtime.session_store.get_start_command(
                        child_run_id
                    )
                    request = ExecutionBindingRequest(
                        run_id=child_run_id,
                        parent_run_id=command.parent_run_id,
                        agent_id=descriptor.agent_id,
                        workspace_policy=str(
                            command.config.metadata.get("workspace_policy")
                            or "shared_parent"
                        ),
                        context=child_context,
                        configuration=command.config.execution_snapshot,
                    )
                    from sagents.v2.runtime.execution.recovery import acquire_execution_binding
                    binding = await acquire_execution_binding(self.state.execution_binding_provider, request, driver_runtime)
                    try:
                        binding.validate_for(request)
                        await driver_runtime.record_execution_binding(binding, child_context)
                        with _bind_execution_environment(RunExecutionEnvironment(
                            child_run_id, command, child_context, binding.sandbox,
                            binding.grant_issuer, binding.workspace_root,
                        )):
                            child_tools = await bound_tools.compose(
                                binding,
                                tenant_id=tenant_id or child_context.actor.tenant_id,
                                agent_id=descriptor.agent_id,
                            )
                            try:
                                child_loop, child_scope = await make_loop(
                                    child_run_id, child_tools.catalog, child_tools.executor,
                                    child_tools.runtime, descriptor, available_scopes=child_tools.scope.provider_scopes,
                                )
                            except BaseException:
                                await child_tools.scope.close()
                                raise
                            return child_loop, _CompositeRunResource(binding, child_tools.scope, child_scope)
                    except BaseException as exc:
                        try:
                            await binding.close()
                        except BaseException as close_exc:
                            raise exc from close_exc
                        raise

                child_factory = compose_unbound_child
                if uses_binding_tools:
                    child_factory = compose_bound_child

                mode_factory = ModeAwareAgentLoopFactory(
                    runtime=driver_runtime,
                    model_factory=lambda descriptor, _: run_models[
                        descriptor.agent_id
                    ],
                    base_catalog=selected_catalog,
                    base_executor=selected_executor,
                    registry=registry,
                    resolved_spec_hash=(
                        runtime_composition_hash or resolved.manifest_hash
                    ),
                    delegation_concurrency_limiter=delegation_limiter,
                    workspace_policy=WorkspaceSharingPolicy(
                        active_command.config.execution_snapshot.child_workspace_policy
                        if active_command.config.execution_snapshot is not None else "shared_parent"
                    ),
                    loop_composer=compose,
                    child_loop_factory=child_factory,
                    child_run_config_resolver=lambda descriptor, parent_command: (
                        CompositionResolver().resolve_child_run_config(
                            resolved,
                            # Dynamically spawned Fibre agents narrow the root's
                            # tools/skills and use its model policy ceiling.
                            descriptor.agent_id
                            if descriptor.agent_id in resolved.agents
                            else selected_agent,
                            parent_config=parent_command.config,
                            tools=descriptor.tools,
                            skills=descriptor.skills,
                        )
                    ),
                    trace_sink=services["observability.trace-sink"],
                    log_sink=services["observability.log-sink"],
                )
                if uses_flow and entry_descriptor.agent_id == selected_agent:
                    from sagents.v2.flow import FlowRuntime
                    from sagents.v2.flow.driver import AgentFlowDriver
                    from sagents.v2.flow.plugins.agent import NativeAgentFlowNode

                    flow_runtime = FlowRuntime(
                        runtime=driver_runtime,
                        expected_resolved_spec_hash=(
                            runtime_composition_hash or resolved.manifest_hash
                        ),
                        flows=resolved.flows,
                        agent_nodes={
                            descriptor.agent_id: NativeAgentFlowNode(
                                runtime=driver_runtime,
                                descriptor=descriptor,
                                child_executor=mode_factory.child_executor,
                            )
                            for descriptor in member_descriptors
                        },
                        tool_nodes=active_flow_tool_nodes,
                        max_node_visits=selected_definition.max_steps or 100,
                    )
                    driver = AgentFlowDriver(
                        flow_runtime, selected_definition.entrypoint.flow, mode_factory.child_executor,
                    )
                else:
                    driver = mode_factory.create_loop(entry_descriptor, run_id)
                owned.append(mode_factory.child_executor)
                return driver, _CompositeRunResource(*owned)
            except BaseException:
                await _CompositeRunResource(*owned).close()
                raise

        descriptors_by_id = {value.agent_id: value for value in (root_descriptor, *member_descriptors)}

        async def run_descriptor(command):
            if command.agent_id in descriptors_by_id:
                return descriptors_by_id[command.agent_id]
            if command.parent_run_id is None:
                return root_descriptor
            raise ValueError(f"admitted child Agent {command.agent_id!r} is unavailable in its frozen graph")

        def driver_factory(run_id):
            async def resolve_agent(command):
                return (await run_descriptor(command)).agent_id

            if not uses_binding_tools:
                async def compose_unbound(context):
                    descriptor = await run_descriptor(await session_store.get_start_command(run_id))
                    pair = await self._create_tools(extension_host, process_root, scope_handles,
                        runtime_config, plugin_declarations, return_handle=True,
                        tenant_id=tenant_id or context.actor.tenant_id, agent_id=descriptor.agent_id, run_id=run_id)
                    catalog, executor, tools_scope = pair
                    sources = tools_scope.provider_scopes if tools_scope is not None else ()
                    try:
                        loop, scope = await make_loop(run_id, catalog, executor, None, descriptor, available_scopes=sources)
                    except BaseException:
                        if tools_scope is not None:
                            await tools_scope.close()
                        raise
                    return loop, _CompositeRunResource(tools_scope, scope)
                return _ExecutionBoundDriver(runtime=control_runtime, provider=None, run_id=run_id,
                    agent_id=selected_agent, loop_builder=compose_unbound, agent_resolver=resolve_agent)

            async def loop_builder(binding: RunExecutionBinding):
                descriptor = await run_descriptor(await session_store.get_start_command(run_id))
                tools = await bound_tools.compose(
                    binding, tenant_id=tenant_id or binding.sandbox.ref.tenant_id, agent_id=descriptor.agent_id,
                )
                try:
                    loop, scope = await make_loop(
                        run_id, tools.catalog, tools.executor, tools.runtime, descriptor, available_scopes=tools.scope.provider_scopes,
                    )
                except BaseException:
                    await tools.scope.close()
                    raise
                return loop, _CompositeRunResource(tools.scope, scope)

            return _ExecutionBoundDriver(
                runtime=control_runtime,
                provider=self.state.execution_binding_provider,
                run_id=run_id,
                agent_id=selected_agent,
                loop_builder=loop_builder,
                agent_resolver=resolve_agent,
            )

        session_access = AuthorizedSessionAccess(
            session_store,
            runtime=control_runtime,
            derived_state=(
                derived_state if derived_state is not session_store else None
            ),
            derived_state_cleaners=(session_memory_service,),
        )
        agent = SAgent._from_composition(
            runtime=control_runtime,
            driver_factory=driver_factory,
            memory_service=(
                memory_service
                if memory_enabled and memory_behavior.auto_write
                else None
            ),
            memory_scope={
                **memory_behavior.model_dump(mode="json"),
                "recall": memory_enabled and memory_behavior.recall,
                "auto_write": memory_enabled and memory_behavior.auto_write,
            },
            session_access=session_access,
        )
        services = {
            **services,
            "session.store": session_store,
            "derived-state.store": derived_state,
            "session.access": session_access,
            "credentials.provider": credential_provider,
            "memory.provider": memory_provider,
            "session-memory.provider": session_memory_provider,
            "model.provider": models_by_agent[selected_agent],
            "tool.catalog": tool_catalog,
            "tool.executor": tool_executor,
            "tool.selection-policy": tool_selection,
            **root_components.services(),
            "agent.approval-memory": approval_memory,
        }
        await self._validate_required_guarantees(
            runtime_config,
            services=services,
            handles=scope_handles,
        )
        scheduler_config = _selection(runtime_config, "execution.scheduler")
        dispatcher_values = dict(
            scheduler_config.config if scheduler_config is not None else {}
        )
        scheduler_capabilities = await scheduler.capabilities()
        tenant_limit = int(dispatcher_values.get("max_concurrent_runs_per_tenant", 2))
        if not scheduler_capabilities.supports_atomic_tenant_quota:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="runtime.scheduler_tenant_quota_unsupported",
                    category=ErrorCategory.VALIDATION,
                    message=(
                        "configured tenant concurrency requires atomic Scheduler "
                        "claim quota support"
                    ),
                    safe_to_resume=False,
                    metadata={
                        "max_concurrent_runs_per_tenant": tenant_limit,
                        "supports_atomic_tenant_quota": False,
                    },
                )
            )
        dispatcher = self.state.dispatcher or LocalWorkerDispatcher(
            scheduler,
            max_concurrent_runs=int(dispatcher_values.get("max_concurrent_runs", 8)),
            max_concurrent_runs_per_tenant=tenant_limit,
            lease_seconds=float(dispatcher_values.get("lease_seconds", DEFAULT_LEASE_SECONDS)),
            lease_scope_factory=driver_session_store.lease_scope,
            preserve_runs_on_shutdown=bool(dispatcher_values.get("preserve_runs_on_shutdown", True)),
        )
        services["execution.dispatcher"] = dispatcher
        composition_hash = self._composition_hash(
            resolved.manifest_hash, scope_handles, services,
            registry=self.extensions if self.state.revision_identity else None, runtime=runtime_config,
        )
        runtime_composition_hash = composition_hash
        agent.attach_dispatcher(dispatcher)
        if self.state.dispatcher is None:
            dispatcher.attach_recovery_agent(agent)
        if not self.state.defer_dispatcher_start and not self.state.manual_dispatcher_start:
            await dispatcher.start()
        resolved_plan = self._resolved_application_plan(
            package_id=resolved.package_id,
            manifest_hash=resolved.manifest_hash,
            entrypoint_agent_id=selected_agent,
            handles=scope_handles,
            services=services,
            composition_hash=composition_hash,
            host_capabilities=frozenset(),
            unfenced_host_capabilities=(),
            deferred_plugins=(
                ((OfficialToolPlugin.plugin_id, ExtensionScope.RUN),
                 ("sage.execution.environment", ExtensionScope.RUN),
                 ("sage.execution.tool-runtime", ExtensionScope.RUN))
                if uses_binding_tools else ()
            ) + tuple((selection.plugin, self._selection_scope(selection, ExtensionScope.AGENT))
                      for capability in runtime_config.capabilities
                      for selection in runtime_config.selections(capability)
                      if not any(selection.plugin in handle.graph.plugin_ids for handle in scope_handles)),
        )
        application = SAgentApplication._from_composition(
            agents={selected_agent: agent},
            entrypoint_agent_id=selected_agent,
            scope_handles=tuple(scope_handles),
            services={
                capability: provider
                for capability, provider in services.items()
                if capability != "session.store"
            },
            adapters=adapters,
            composition_hash=composition_hash,
            resolved_plan=resolved_plan,
            owned_resources=(dispatcher,) if self.state.dispatcher is None else (),
            resource_readiness=readiness,
        )
        self._application = application
        plugins = sorted(
            {
                (binding.capability, binding.plugin_id)
                for binding in resolved_plan.providers
                if binding.plugin_id
            }
        )
        StructuredLogger(log_sink, "sagents.application").info(
            "sagents.registered",
            "sagents plugins registered",
            attributes={
                "package_id": resolved_plan.package_id,
                "entrypoint": resolved_plan.entrypoint_agent_id,
                "composition_hash": resolved_plan.composition_hash,
                "plugins": [
                    {"capability": capability, "plugin": plugin_id}
                    for capability, plugin_id in plugins
                ],
            },
        )
        return application

    def _load_declared_plugins(
        self,
        declarations: tuple[PluginDeclaration, ...],
        *,
        trust_policy: str,
    ) -> None:
        _validate_declared_plugin_trust(
            self.extensions,
            declarations,
            built_in_only=trust_policy == "built_in_only",
        )
        for declaration in declarations:
            # Declarations select/version-check code already registered by the
            # host. Missing registrations never import or install code here.
            validate_extension_version(self.extensions.get(declaration.id), declaration.version)
            self.extensions.validate_parameters(declaration.id, declaration.config)

    async def _create_session_store(
        self, host, parent, handles, runtime, declarations
    ) -> SessionStore:
        selection = _selection(runtime, "session.store")
        plugin_id = selection.plugin if selection else FilesystemSessionStore.plugin_id
        config = dict(selection.config if selection else {})
        if plugin_id == FilesystemSessionStore.plugin_id and "root" not in config:
            if self.state.session_root is None:
                raise ValueError("filesystem SessionStore requires session_root")
            config["root"] = str(self.state.session_root)
        return await self._create_capability(
            host,
            parent,
            handles,
            runtime,
            declarations,
            capability="session.store",
            default_plugin=plugin_id,
            default_config=config,
            default_scope=ExtensionScope.PROCESS,
        )

    async def _create_memory_provider(
        self, host, parent, handles, runtime, declarations
    ) -> MemoryProvider:
        return await self._create_capability(
            host,
            parent,
            handles,
            runtime,
            declarations,
            capability="memory.provider",
            default_plugin=NoopMemoryProvider.plugin_id,
            default_scope=ExtensionScope.PROCESS,
        )

    async def _create_session_memory_provider(
        self, host, parent, handles, runtime, declarations
    ) -> SessionMemoryProvider:
        selection = _selection(runtime, "session-memory.provider")
        plugin_id = (
            selection.plugin if selection else NoopSessionMemoryProvider.plugin_id
        )
        config = dict(selection.config if selection else {})
        if (
            plugin_id == SqliteBm25SessionMemoryProvider.plugin_id
            and "root" not in config
        ):
            if self.state.session_root is None:
                raise ValueError("SQLite Session Memory requires a root")
            config["root"] = str(self.state.session_root / "session-memory")
        return await self._create_capability(
            host,
            parent,
            handles,
            runtime,
            declarations,
            capability="session-memory.provider",
            default_plugin=plugin_id,
            default_config=config,
            default_scope=ExtensionScope.PROCESS,
        )

    async def _create_model(
        self,
        host,
        parent,
        handles,
        resolved,
        agent_id,
        declarations: tuple[PluginDeclaration, ...],
        credential_provider,
        *,
        tenant_id: str | None,
        run_id: str | None = None,
        return_handle: bool = False,
        available=(),
    ):
        agent = resolved.agents.get(agent_id, resolved.agents[resolved.entrypoint_agent])
        selection = _selection(resolved.runtime, "model.provider")
        if selection is not None:
            return await self._create_capability(
                host, parent, handles, resolved.runtime, declarations,
                capability="model.provider", default_plugin=selection.plugin,
                default_scope=ExtensionScope.AGENT, tenant_id=tenant_id,
                agent_id=agent_id, run_id=run_id, return_handle=return_handle, available=available,
            )
        route_id = agent.model_bindings.get("primary")
        if route_id is None:
            raise ValueError(f"agent {agent_id!r} has no primary model binding")
        route_data = resolved.model_routes[route_id]
        selected_plugin = route_data.get("plugin")
        if selected_plugin is None:
            plugin_id = model_protocol_descriptor(route_data["provider"]).plugin_id
        else:
            plugin_id = str(selected_plugin)
        config = _merge_plugin_config(
            declarations,
            plugin_id,
            {"route": route_data, "client": None},
        )
        credential_id = route_data.get("credential")
        if credential_id is not None:
            config["credential"] = await credential_provider.resolve(
                CredentialRef(
                    credential_id=credential_id,
                    purpose="model.inference",
                ),
                RequestContext(
                    actor=ActorRef(
                        principal_id="sagent-builder",
                        principal_type=PrincipalType.SERVICE,
                    )
                ),
            )
        return await self._instantiate(
            host,
            parent,
            handles,
            plugin_id,
            config,
            "model.provider",
            scope=ExtensionScope.AGENT,
            scope_id=f"agent-{agent_id}",
            tenant_id=tenant_id,
            agent_id=agent_id,
        )

    async def _create_tools(self, host, parent, handles, runtime, declarations, **kwargs):
        from sagents.v2.tool import CompositeToolCatalog, CompositeToolExecutor

        pairs = []
        owned = []
        include_runtime = kwargs.pop("include_runtime", False)
        selected_runtime = None
        runtime_scope = None
        selection_scope = None
        try:
            if include_runtime:
                _, selection_scope = await self._create_capability(
                    host, parent, handles, runtime, declarations,
                    capability="tool.selection-policy", default_plugin=LLMToolSelectionPolicy.plugin_id,
                    default_scope=ExtensionScope.AGENT, tenant_id=kwargs.get("tenant_id"),
                    agent_id=kwargs.get("agent_id"), run_id=kwargs.get("run_id"), return_handle=True,
                )
                if selection_scope.context.scope == ExtensionScope.RUN:
                    owned.append(selection_scope)
            if include_runtime:
                selected_runtime, runtime_scope = await self._create_capability(
                    host, parent, handles, runtime, declarations,
                    capability="execution.tool-runtime", default_plugin="sage.execution.tool-runtime",
                    default_scope=ExtensionScope.RUN, tenant_id=kwargs.get("tenant_id"),
                    agent_id=kwargs.get("agent_id"), run_id=kwargs.get("run_id"), return_handle=True,
                )
                owned.append(runtime_scope)
            for selection in runtime.selections("tool.catalog"):
                selected = runtime.model_copy(update={"capabilities": {
                    **runtime.capabilities, "tool.catalog": selection,
                }})
                pair = await self._create_tool_pair(
                    host, parent, handles, selected, declarations, **kwargs,
                )
                pairs.append(pair)
                if kwargs.get("return_handle") and pair[2] is not None:
                    owned.append(pair[2])
        except BaseException:
            for handle in reversed(owned):
                await handle.close()
            raise
        finally:
            for transient in (runtime_scope, selection_scope):
                if transient is not None and transient.context.scope == ExtensionScope.RUN and transient in handles:
                    handles.remove(transient)
        if include_runtime:
            catalogs = tuple(pair[0] for pair in pairs)
            executors = tuple(pair[1] for pair in pairs)
            grants = tuple(pair[0] for pair, selection in zip(pairs, runtime.selections("tool.catalog"))
                           if selection.grant_tools)
            return (CompositeToolCatalog(catalogs, runtime_grants=grants), CompositeToolExecutor(executors),
                    _CompositeRunResource(*owned), selected_runtime)
        if not pairs:
            values = (InMemoryToolCatalog(()), InMemoryToolExecutor({}, {}))
            return (*values, None) if kwargs.get("return_handle") else values
        grants = tuple(pair[0] for pair, selection in zip(pairs, runtime.selections("tool.catalog"))
                       if selection.grant_tools)
        if len(pairs) == 1 and not grants:
            if kwargs.get("return_handle"):
                return pairs[0][0], pairs[0][1], _CompositeRunResource(*owned)
            return pairs[0]
        catalog = CompositeToolCatalog(
            tuple(pair[0] for pair in pairs), runtime_grants=grants,
        )
        executor = CompositeToolExecutor(tuple(pair[1] for pair in pairs))
        return ((catalog, executor, _CompositeRunResource(*owned))
                if kwargs.get("return_handle") else (catalog, executor))

    async def _create_tool_pair(
        self,
        host,
        parent,
        handles,
        runtime: RuntimeConfig,
        declarations: tuple[PluginDeclaration, ...],
        *,
        return_handle: bool = False,
        scope_override: ExtensionScope | None = None,
        tenant_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
    ):
        selection = _selection(runtime, "tool.catalog")
        if selection is None:
            return InMemoryToolCatalog(()), InMemoryToolExecutor({}, {})
        config = _merge_plugin_config(
            declarations, selection.plugin, dict(selection.config)
        )
        catalog, handle = await self._instantiate(
            host,
            parent,
            handles,
            selection.plugin,
            config,
            "tool.catalog",
            scope=self._selection_scope(selection, scope_override or ExtensionScope.AGENT),
            scope_id="agent-tools",
            tenant_id=tenant_id,
            agent_id=agent_id,
            run_id=run_id,
            return_handle=True,
            offer_name=self._selected_offer_name(
                selection.plugin, "tool.catalog", selection.name
            ),
        )
        executor = handle.providers.require(
            "tool.executor",
            self._paired_tool_executor_name(selection.plugin, selection.name),
        )
        if not hasattr(catalog, "list_tools") or not hasattr(executor, "execute"):
            raise TypeError(
                f"extension {selection.plugin!r} did not create a Tool provider pair"
            )
        if return_handle:
            # The Run driver owns and closes this dynamic scope. Keeping it in
            # the Application build list would retain one closed handle per Run.
            if handle.context.scope == ExtensionScope.RUN:
                handles.remove(handle)
            else:
                handle = None
        return (catalog, executor, handle) if return_handle else (catalog, executor)

    async def _create_tool_selection(
        self,
        host,
        parent,
        handles,
        runtime: RuntimeConfig,
        declarations: tuple[PluginDeclaration, ...],
        *,
        tenant_id: str | None = None,
        agent_id: str | None = None,
    ) -> ToolSelectionPolicy:
        return await self._create_capability(
            host, parent, handles, runtime, declarations,
            capability="tool.selection-policy", default_plugin=LLMToolSelectionPolicy.plugin_id,
            default_scope=ExtensionScope.AGENT, tenant_id=tenant_id, agent_id=agent_id,
        )

    async def _create_capability(
        self,
        host,
        parent,
        handles,
        runtime,
        declarations,
        *,
        capability,
        default_plugin,
        default_config=None,
        default_scope=ExtensionScope.PROCESS,
        locked_config=None,
        tenant_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
        return_handle: bool = False,
        available=(),
    ):
        selection = _selection(runtime, capability)
        plugin_id = selection.plugin if selection else default_plugin
        config = {
            **dict(default_config or {}),
            **dict(selection.config if selection else {}),
        }
        config = _merge_plugin_config(declarations, plugin_id, config)
        # Host-owned runtime identities are dependencies, not user/plugin
        # configuration. Apply them last so a manifest cannot replace a model,
        # SessionStore, estimator, or another trusted composition input.
        config.update(
            _supported_locked_config(
                self.extensions, plugin_id, dict(locked_config or {})
            )
        )
        selected_scope = self._selection_scope(selection, default_scope) if selection else default_scope
        dynamic_agent_ports = {
            "model.provider", "context.summarizer", "context.reducer", "context.unit-compactor",
            "memory.recall-query", "skill.loading", "agent.continuation-policy", "agent.tool-policy",
            "agent.self-configuration", "agent.output-checker", "context.segment-provider", "skill.catalog",
            "skill.workspace", "tool.selection-policy", "tool.result-processor",
        }
        if run_id is None and (selected_scope == ExtensionScope.RUN or (
                tenant_id is None and selected_scope in {ExtensionScope.TENANT, ExtensionScope.AGENT}
                and capability in dynamic_agent_ports)):

            # Validate serializable inputs before admitting a revision, while
            # retaining actual resource creation for the allocated Run identity.
            from jsonschema import Draft202012Validator
            registration = self.extensions.get(plugin_id)
            if selected_scope not in registration.descriptor.supported_scopes:
                raise SageV2Error(RuntimeErrorInfo(code="extension.scope_unsupported", category=ErrorCategory.VALIDATION,
                    message=f"extension {plugin_id!r} does not support scope {selected_scope.value!r}"))
            try:
                Draft202012Validator(registration.descriptor.config_schema or {}).validate(config)
                if registration.config_model is not None:
                    registration.config_model.model_validate(config)
            except Exception as exc:
                raise SageV2Error(RuntimeErrorInfo(code="extension.config_invalid", category=ErrorCategory.VALIDATION,
                    message=f"invalid configuration for extension {plugin_id!r}: {exc}")) from exc
            from sagents.v2.composition.providers import DeferredRunCapability
            value = DeferredRunCapability(plugin_id, capability)
            return (value, None) if return_handle else value
        return await self._instantiate(
            host,
            parent,
            handles,
            plugin_id,
            config,
            capability,
            return_handle=return_handle, available=available,
            scope=selected_scope,
            scope_id=f"application-{capability.replace('.', '-')}",
            tenant_id=tenant_id,
            agent_id=agent_id,
            run_id=run_id,
            offer_name=self._selected_offer_name(plugin_id, capability, selection.name)
            if selection
            else None,
        )

    async def _instantiate(self, *args, **kwargs):
        import asyncio
        from sagents.v2.composition.identity import _config_identity
        if kwargs["scope"] == ExtensionScope.RUN:
            return await self._open_instance(*args, **kwargs)
        plugin_id, config = args[3:5]
        key = (plugin_id, kwargs["scope"], kwargs.get("tenant_id"),
               kwargs.get("agent_id"), _config_identity(config))
        lock = self._provider_locks.setdefault(key, asyncio.Lock())
        async with lock:
            return await self._open_instance(*args, **kwargs)

    async def _open_instance(
        self,
        host,
        parent,
        handles,
        plugin_id: str,
        config: dict[str, Any],
        capability: str,
        *,
        scope: ExtensionScope,
        scope_id: str,
        tenant_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
        return_handle: bool = False,
        offer_name: str | None = None,
        available=(),
    ):
        from sagents.v2.composition.identity import _config_identity
        agent_configuration = self._agent_configurations.get(agent_id)
        if agent_configuration is not None:
            agent_id = agent_configuration["scope_agent_id"]
        cache_key = (plugin_id, scope, tenant_id if scope != ExtensionScope.PROCESS else None,
                     agent_id if scope in {ExtensionScope.AGENT, ExtensionScope.RUN} else None,
                     _config_identity(config),
                     _config_identity(agent_configuration) if scope in {ExtensionScope.AGENT, ExtensionScope.RUN} else None)
        if scope != ExtensionScope.RUN and cache_key in self._provider_handles:
            handle = self._provider_handles[cache_key]
            if getattr(handle, "_released", False) or handle._closed:
                self._provider_handles.pop(cache_key)
            else:
                name = self._selected_offer_name(plugin_id, capability, offer_name or "default")
                value = handle.providers.require(capability, name)
                return (value, handle) if return_handle else value

        def retain(handle):
            handles.append(handle)
            if handle.context.scope != ExtensionScope.RUN:
                if handle.context.scope == scope:
                    self._provider_handles[cache_key] = handle
                if hasattr(self, "_application"):
                    self._application._retain_scope(handle)

        if scope in {ExtensionScope.PROCESS, ExtensionScope.TENANT} and self.scope_pool is not None:
            import json
            try:
                key = (plugin_id, scope, tenant_id if scope == ExtensionScope.TENANT else None,
                       json.dumps(config, sort_keys=True, allow_nan=False),
                       self.extensions.get(plugin_id).descriptor.version,
                       self._dependency_identity(plugin_id, handles))
            except (TypeError, ValueError):
                pass
            else:
                async def open_shared_scope():
                    _, scope_handle = await open_provider(
                        host, self.extensions, parent, plugin_id, config, capability,
                        scope=scope, scope_id=scope_id, tenant_id=tenant_id,
                        agent_id=agent_id, run_id=run_id, offer_name=offer_name,
                        available=(*self._shared_handles, *handles, *available), runtime=self._runtime_config,
                        agent_configuration=agent_configuration,
                    )
                    return scope_handle
                handle = await self.scope_pool.acquire(key, open_shared_scope)
                retain(handle)
                name = offer_name or next(offer.name for offer in self.extensions.get(plugin_id).descriptor.provides
                                          if offer.capability == capability)
                value = handle.providers.require(capability, name)
                return (value, handle) if return_handle else value
        value, handle = await open_provider(
            host,
            self.extensions,
            parent,
            plugin_id,
            config,
            capability,
            scope=scope,
            scope_id=scope_id,
            tenant_id=tenant_id,
            agent_id=agent_id,
            run_id=run_id,
            offer_name=offer_name,
            register=retain,
            available=(*self._shared_handles, *handles, *available), runtime=self._runtime_config,
            agent_configuration=agent_configuration,
        )
        return (value, handle) if return_handle else value

    def _dependency_identity(self, plugin_id, handles, seen=frozenset()):
        from sagents.v2.composition.identity import _config_identity
        from sagents.v2.composition.providers import _scope_sources
        if plugin_id in seen:
            return ()  # ExtensionHost reports the dependency cycle.
        result = []
        for dependency in self.extensions.get(plugin_id).descriptor.dependencies:
            choices = self._runtime_config.selections(dependency.capability)
            choices = tuple(choice for choice in choices
                            if dependency.name is None or choice.name == dependency.name)
            if len(choices) == 1:
                choice = choices[0]
                selected, config = choice.plugin, choice.config
            else:
                candidates = [(started.registration.descriptor.plugin_id, source)
                              for source in _scope_sources((*self._shared_handles, *handles)) for started in source._started
                              if any(offer.capability == dependency.capability
                                     and (dependency.name is None or offer.name == dependency.name)
                                     for offer in started.registration.descriptor.provides)]
                if len({item[0] for item in candidates}) != 1:
                    result.append((dependency.capability, None))
                    continue
                selected, source = candidates[0]
                config = source.configurations.get(selected, {})
            descriptor = self.extensions.get(selected).descriptor
            result.append((dependency.capability, dependency.name, selected, descriptor.version,
                           _config_identity(config), self._dependency_identity(
                               selected, handles, seen | {plugin_id})))
        return tuple(result)

    def _selection_scope(self, selection, fallback):
        descriptor = self.extensions.get(selection.plugin).descriptor
        if selection.scope is not None:
            return selection.scope
        if descriptor.default_scope is not None:
            return descriptor.default_scope
        return fallback if fallback in descriptor.supported_scopes else descriptor.resolved_default_scope()

    def _selected_offer_name(self, plugin_id, capability, name):
        names = [
            offer.name
            for offer in self.extensions.get(plugin_id).descriptor.provides
            if offer.capability == capability
        ]
        if name in names:
            return name
        # Preserve implicit default selection for a single implementation.
        if name == "default" and len(names) == 1:
            return names[0]
        raise ValueError(
            f"extension {plugin_id!r} has no unambiguous {capability!r} offer {name!r}"
        )

    def _paired_tool_executor_name(self, plugin_id, name):
        names = [
            offer.name
            for offer in self.extensions.get(plugin_id).descriptor.provides
            if offer.capability == "tool.executor"
        ]
        if name in names:
            return name
        if len(names) == 1:
            return names[0]
        raise ValueError(
            f"extension {plugin_id!r} has no matching tool.executor for {name!r}"
        )

    def _selected_plugin(self, runtime: RuntimeConfig, capability: str) -> str | None:
        selection = _selection(runtime, capability)
        return selection.plugin if selection else None

    async def _create_application_services(
        self,
        host,
        parent,
        handles,
        runtime,
        declarations,
        resolved,
        *,
        session_store,
        credential_provider,
    ):
        services = {
            "execution.scheduler": await self._create_capability(
                host,
                parent,
                handles,
                runtime,
                declarations,
                capability="execution.scheduler",
                default_plugin=InMemoryScheduler.plugin_id,
            ),
            "execution.job-runtime": await self._create_capability(
                host,
                parent,
                handles,
                runtime,
                declarations,
                capability="execution.job-runtime",
                default_plugin=InMemoryJobRuntime.plugin_id,
            ),
            "artifact.store": await self._create_capability(
                host,
                parent,
                handles,
                runtime,
                declarations,
                capability="artifact.store",
                default_plugin=SessionArtifactStore.plugin_id,
                locked_config={"session_store": session_store},
            ),
            "package.registry": await self._create_capability(
                host,
                parent,
                handles,
                runtime,
                declarations,
                capability="package.registry",
                default_plugin=InMemoryAgentPackageRegistry.plugin_id,
                locked_config={"resolver": self.model_resolver or CompositionResolver(models={
                    "models": resolved.model_routes,
                    "credentials": resolved.credentials,
                })},
            ),
            "observability.diagnostic-sink": (
                await self._create_capability(
                    host,
                    parent,
                    handles,
                    runtime,
                    declarations,
                    capability="observability.diagnostic-sink",
                    default_plugin=NoopDiagnosticSink.plugin_id,
                )
            ),
            "observability.log-sink": (
                await self._create_capability(
                    host,
                    parent,
                    handles,
                    runtime,
                    declarations,
                    capability="observability.log-sink",
                    default_plugin=NoopLogSink.plugin_id,
                )
            ),
            "observability.trace-sink": await self._create_capability(
                host,
                parent,
                handles,
                runtime,
                declarations,
                capability="observability.trace-sink",
                default_plugin=NoopTraceSink.plugin_id,
            ),
            "workspace.initializer": await self._create_capability(
                host,
                parent,
                handles,
                runtime,
                declarations,
                capability="workspace.initializer",
                default_plugin=BareWorkspaceInitializer.plugin_id,
            ),
        }
        adapters = {}
        interface_declarations = dict(resolved.interfaces)
        for selection in runtime.selections("interface.protocol-adapter"):
            adapter, _ = await self._create_capability(
                host, parent, handles,
                runtime.model_copy(update={"capabilities": {**runtime.capabilities, "interface.protocol-adapter": selection}}),
                declarations, capability="interface.protocol-adapter", default_plugin=selection.plugin,
                return_handle=True,
            )
            name = self._selected_offer_name(selection.plugin, "interface.protocol-adapter", selection.name)
            adapters[name] = adapter
        if "native" not in interface_declarations:
            from sagents.v2.package.manifest.root import InterfaceDeclaration

            interface_declarations["native"] = InterfaceDeclaration(
                plugin=NativeProtocolAdapter.plugin_id
            )
        for interface_id, declaration in interface_declarations.items():
            if not declaration.enabled:
                continue
            adapter = await self._instantiate(
                host,
                parent,
                handles,
                declaration.plugin,
                _merge_plugin_config(
                    declarations, declaration.plugin, dict(declaration.config)
                ),
                "interface.protocol-adapter",
                scope=declaration.scope or ExtensionScope.PROCESS,
                scope_id=f"interface-{interface_id}",
            )
            adapters[interface_id] = adapter
        return services, adapters

    async def _validate_required_guarantees(
        self,
        runtime: RuntimeConfig,
        *,
        services: Mapping[str, Any],
        handles,
    ) -> None:
        """Verify manifest guarantees against live providers or descriptors."""

        required_guarantees = self._effective_required_guarantees(runtime)
        if not required_guarantees:
            return

        descriptor_facts: dict[str, list[dict[str, Any]]] = {}
        visited: set[int] = set()

        def visit(handle) -> None:
            if id(handle) in visited:
                return
            visited.add(id(handle))
            for ancestor in handle._owned_ancestors:
                visit(ancestor)
            for started in handle._started:
                descriptor = started.registration.descriptor
                for offer in descriptor.provides:
                    descriptor_facts.setdefault(offer.capability, []).append(
                        dict(descriptor.capabilities)
                    )

        for handle in handles:
            visit(handle)

        for capability, required in required_guarantees.items():
            observed: dict[str, Any] | None = None
            provider = services.get(capability)
            capability_reader = getattr(provider, "capabilities", None)
            if isinstance(capability_reader, Mapping):
                observed = dict(capability_reader)
            elif callable(capability_reader):
                parameters = inspect.signature(capability_reader).parameters.values()
                if not any(
                    value.default is inspect.Parameter.empty
                    and value.kind
                    in {
                        inspect.Parameter.POSITIONAL_ONLY,
                        inspect.Parameter.POSITIONAL_OR_KEYWORD,
                        inspect.Parameter.KEYWORD_ONLY,
                    }
                    for value in parameters
                ):
                    facts = capability_reader()
                    if inspect.isawaitable(facts):
                        facts = await facts
                    if hasattr(facts, "model_dump"):
                        facts = facts.model_dump(mode="json")
                    if isinstance(facts, Mapping):
                        observed = dict(facts)
            declared = descriptor_facts.get(capability, [])

            if provider is not None:
                live = observed or {}
                conflicts = [
                    facts
                    for facts in declared
                    if any(
                        name in facts and name in live and facts[name] != live[name]
                        for name in required
                    )
                ]
                if conflicts:
                    raise SageV2Error(
                        RuntimeErrorInfo(
                            code="runtime.capability_descriptor_conflict",
                            category=ErrorCategory.VALIDATION,
                            message=(
                                f"declared capabilities for {capability!r} conflict "
                                "with the instantiated provider"
                            ),
                            safe_to_resume=False,
                            metadata={
                                "capability": capability,
                                "required": dict(required),
                                "declared": conflicts,
                                "observed": live,
                                "deployment_profile": runtime.deployment_profile,
                            },
                        )
                    )
                satisfied = all(
                    live.get(name) == expected for name, expected in required.items()
                )
                candidates = [live]
            else:
                satisfied = any(
                    all(
                        facts.get(name) == expected
                        for name, expected in required.items()
                    )
                    for facts in declared
                )
                candidates = declared
            if satisfied:
                continue
            reported = {
                name: sorted(
                    {
                        json.dumps(facts.get(name), sort_keys=True, default=str)
                        for facts in candidates
                        if name in facts
                    }
                )
                for name in required
            }
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="runtime.capability_guarantee_unsatisfied",
                    category=ErrorCategory.VALIDATION,
                    message=(
                        f"selected provider for {capability!r} does not satisfy "
                        "the required operational guarantees"
                    ),
                    safe_to_resume=False,
                    metadata={
                        "capability": capability,
                        "required": dict(required),
                        "declared": declared,
                        "observed": observed if provider is not None else reported,
                        "deployment_profile": runtime.deployment_profile,
                    },
                )
            )

    @staticmethod
    def _effective_required_guarantees(
        runtime: RuntimeConfig,
    ) -> dict[str, dict[str, Any]]:
        effective = {
            capability: dict(required)
            for capability, required in runtime.required_guarantees.items()
        }
        if runtime.deployment_profile != "distributed":
            return effective
        for capability, mandated in _DISTRIBUTED_PROFILE_GUARANTEES.items():
            configured = effective.setdefault(capability, {})
            conflicts = {
                name: configured[name]
                for name, expected in mandated.items()
                if name in configured and configured[name] != expected
            }
            if conflicts:
                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="runtime.deployment_profile_conflict",
                        category=ErrorCategory.VALIDATION,
                        message=(
                            "distributed deployment profile conflicts with explicit "
                            f"guarantees for {capability!r}"
                        ),
                        safe_to_resume=False,
                        metadata={
                            "capability": capability,
                            "configured": conflicts,
                            "mandated": dict(mandated),
                            "deployment_profile": runtime.deployment_profile,
                        },
                    )
                )
            configured.update(mandated)
        return effective

    @staticmethod
    def _composition_hash(manifest_hash, handles, services, *, registry=None, runtime=None) -> str:
        selected_ids = {plugin for handle in handles for plugin in handle.graph.plugin_ids}
        if registry is not None and runtime is not None:
            from sagents.v2.runtime.extensions import CapabilityRequirement
            from sagents.v2.runtime.extensions.resolver import ExtensionResolver, version_satisfies
            sources = {}
            for handle in handles:
                for offer in handle.graph.capabilities:
                    sources.setdefault(offer.capability, set()).add(offer.plugin_id)
            choices = {capability: next(iter(ids)) for capability, ids in sources.items() if len(ids) == 1}
            for capability in runtime.capabilities:
                values = runtime.selections(capability)
                if len(values) == 1:
                    choices[capability] = values[0].plugin
            resolver = ExtensionResolver(registry)
            for capability in runtime.capabilities:
                for choice in runtime.selections(capability):
                    offers = [offer for offer in registry.get(choice.plugin).descriptor.provides if offer.capability == capability]
                    name = choice.name if any(offer.name == choice.name for offer in offers) else offers[0].name
                    relevant = {capability: choice.plugin}
                    pending = [choice.plugin]
                    visited = set()
                    while pending:
                        plugin_id = pending.pop()
                        if plugin_id in visited:
                            continue
                        visited.add(plugin_id)
                        for dependency in registry.get(plugin_id).descriptor.dependencies:
                            selected = choices.get(dependency.capability)
                            if selected is None:
                                candidates = {item.descriptor.plugin_id for item in registry.registrations()
                                    if any(offer.capability == dependency.capability
                                        and (dependency.name is None or offer.name == dependency.name)
                                        and version_satisfies(offer.api_version, dependency.api_version)
                                        for offer in item.descriptor.provides)}
                                if len(candidates) == 1:
                                    selected = candidates.pop()
                            if selected is not None:
                                relevant[dependency.capability] = selected
                                pending.append(selected)
                    graph = resolver.resolve((CapabilityRequirement(capability=capability,
                        api_version="3" if capability == "execution.sandbox" else ">=2,<3", name=name),),
                        selections=relevant)
                    selected_ids.update(graph.plugin_ids)
        payload = {
            "manifest": manifest_hash,
            "plans": (sorted((item for item in registry.inventory() if item["plugin_id"] in selected_ids), key=lambda item: item["plugin_id"])
                      if registry is not None else sorted(
                          handle.composition_hash for handle in handles if handle.graph.plugin_ids
                      )),
            "services": {
                capability: _service_composition_identity(provider)
                for capability, provider in sorted(services.items())
            },
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"

    def _resolved_application_plan(
        self,
        *,
        package_id,
        manifest_hash,
        entrypoint_agent_id,
        handles,
        services,
        composition_hash,
        host_capabilities,
        deferred_plugins,
        unfenced_host_capabilities=(),
    ) -> ResolvedApplicationPlan:
        bindings: set[ResolvedProviderBinding] = set()
        dependencies: set[tuple[str, str]] = set()
        plugin_capabilities: set[str] = set()

        def visit(handle) -> None:
            for ancestor in handle._owned_ancestors:
                visit(ancestor)
            dependencies.update(handle.graph.dependencies)
            for started in handle._started:
                descriptor = started.registration.descriptor
                for offer in descriptor.provides:
                    plugin_capabilities.add(offer.capability)
                    bindings.add(
                        ResolvedProviderBinding(
                            capability=offer.capability,
                            name=offer.name,
                            api_version=offer.api_version,
                            plugin_id=descriptor.plugin_id,
                            scope=handle.context.scope.value,
                            source="plugin",
                            plugin_version=descriptor.version,
                            source_digest=str(descriptor.capabilities.get("source_sha256", "")),
                        )
                    )

        for handle in handles:
            visit(handle)
        for plugin_id, scope in deferred_plugins:
            # Deferred Run-scoped providers are selected now but instantiated
            # only after the Runtime allocates the real Run identity.
            registration = self.extensions.get(plugin_id)
            for offer in registration.descriptor.provides:
                plugin_capabilities.add(offer.capability)
                bindings.add(
                    ResolvedProviderBinding(
                        capability=offer.capability,
                        name=offer.name,
                        api_version=offer.api_version,
                        plugin_id=plugin_id,
                        scope=scope.value,
                        source="plugin-deferred",
                        plugin_version=registration.descriptor.version,
                        source_digest=str(registration.descriptor.capabilities.get("source_sha256", "")),
                    )
                )
        for capability in services:
            if (
                capability in plugin_capabilities
                and capability not in host_capabilities
            ) or capability == "execution.dispatcher":
                continue
            bindings.add(
                ResolvedProviderBinding(
                    capability=capability,
                    name="default",
                    api_version="2",
                    plugin_id=None,
                    scope="process",
                    source="host",
                )
            )
        for capability in unfenced_host_capabilities:
            # 宿主运行偏好（如审批策略）：在 plan 里可见，但不进入 composition hash。
            bindings.add(
                ResolvedProviderBinding(
                    capability=capability,
                    name="default",
                    api_version="2",
                    plugin_id=None,
                    scope="process",
                    source="host",
                )
            )
        bindings.add(
            ResolvedProviderBinding(
                capability="execution.dispatcher",
                name="local",
                api_version="2",
                plugin_id=None,
                scope="process",
                source="composition-root",
            )
        )
        return ResolvedApplicationPlan(
            package_id=package_id,
            manifest_hash=manifest_hash,
            entrypoint_agent_id=entrypoint_agent_id,
            providers=tuple(sorted(bindings)),
            dependencies=tuple(sorted(dependencies)),
            composition_hash=composition_hash,
        )

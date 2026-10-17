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
)
from sagents.v2.agent.policy import (
    SessionApprovalMemory,
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
    _OwnerValidatedCompatibilityDriver,
)
from sagents.v2.composition.identity import _service_composition_identity
from sagents.v2.composition.materializer import AgentMaterializer
from sagents.v2.composition.options import BuildOptions
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
from sagents.v2.runtime.execution.jobs import InMemoryJobRuntime
from sagents.v2.runtime.execution.scheduler import InMemoryScheduler
from sagents.v2.runtime.extensions import (
    ExtensionHost,
    ExtensionRegistry,
    ExtensionScope,
    ExtensionScopeContext,
    load_installed_extension,
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
    InMemoryDerivedStateStore,
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
    def __init__(self, options: BuildOptions, extensions: ExtensionRegistry, *, model_resolver=None) -> None:
        self.model_resolver = model_resolver
        self.options = options
        self.extensions = extensions

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
        plugin_declarations = (
            manifest.plugins if manifest is not None else resolved.plugins
        )
        runtime_config = manifest.runtime if manifest is not None else resolved.runtime
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
        uses_binding_tools = (
            self.options.execution_binding_provider is not None
            and self._selected_plugin(runtime_config, "tool.catalog")
            == OfficialToolPlugin.plugin_id
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
            available_flow_tools = set(self.options.flow_tool_nodes) | {
                selection.name for selection in runtime_config.selections("flow.node")
            }
            from sagents.v2.flow.reachability import reachable_nodes

            flow_nodes = reachable_nodes(
                resolved.flows, resolved.agents[selected_agent].entrypoint.flow
            )
            for _, node in flow_nodes:
                if node.type == "tool" and node.tool not in available_flow_tools:
                    raise ValueError(
                        f"Flow tool node {node.tool!r} needs a flow.node binding or with_flow_tool_nodes()"
                    )
                if (
                    node.type == "agent"
                    and resolved.agents[node.agent].entrypoint.type == "flow"
                ):
                    raise ValueError(
                        "nested Flow agents must use explicit subflow nodes"
                    )
        if (
            (self.options.tool_catalog is None or self.options.tool_executor is None)
            and self._selected_plugin(runtime_config, "tool.catalog")
            == OfficialToolPlugin.plugin_id
            and self.options.tool_runtime is None
            and self.options.execution_binding_provider is None
        ):
            raise ValueError(
                f"{OfficialToolPlugin.plugin_id} requires with_execution_binding_provider(provider) "
                "or the compatibility with_tool_runtime(runtime)"
            )
        session_store = self.options.session_store
        session_store_was_injected = session_store is not None
        if session_store is None:
            session_store = await self._create_session_store(
                extension_host,
                process_root,
                scope_handles,
                runtime_config,
                plugin_declarations,
            )
        derived_state = self.options.derived_state_store
        if derived_state is None:
            # Built-in Session stores explicitly provide colocated derived data.
            # A host-injected authoritative store is not assumed to do so.
            derived_state = (
                InMemoryDerivedStateStore()
                if session_store_was_injected
                else session_store
            )
        # 审批记忆默认落在会话派生状态：非权威、可重建、随 Session 删除清理。
        approval_memory = self.options.approval_memory or SessionApprovalMemory(
            derived_state
        )
        if self.options.approval_memory_layer is not None:
            approval_memory = self.options.approval_memory_layer(approval_memory)
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
        memory_provider = self.options.memory_provider
        if memory_provider is None:
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
        session_memory_provider = self.options.session_memory_provider
        if session_memory_provider is None:
            session_memory_provider = await self._create_session_memory_provider(
                extension_host,
                process_root,
                scope_handles,
                runtime_config,
                plugin_declarations,
            )
        session_memory_service = SessionMemoryService(session_memory_provider)
        model = (
            self.options.model_provider_factory(resolved, selected_agent)
            if self.options.model_provider_factory is not None
            else self.options.model_provider
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
            composition_members = selected_definition.subagents
        for member_id in composition_members:
            if member_id in models_by_agent:
                continue
            member_model = (
                self.options.model_provider_factory(resolved, member_id)
                if self.options.model_provider_factory is not None
                else self.options.model_provider
                if self.options.model_provider is not None
                else await self._create_model(
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

        if self.options.model_budget is not None:
            models_by_agent = {
                key: self.options.model_budget.wrap(provider)
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
            self.options.tool_selection
            or await self._create_tool_selection(
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
            self.options.tool_catalog is not None
            and self.options.tool_executor is not None
        ):
            tool_catalog, tool_executor = (
                self.options.tool_catalog,
                self.options.tool_executor,
            )
        elif (
            self.options.execution_binding_provider is not None
            and self._selected_plugin(runtime_config, "tool.catalog")
            == OfficialToolPlugin.plugin_id
        ):
            # The real provider pair is composed lazily from the actual Run
            # binding. These placeholders are never exposed to that driver.
            tool_catalog = InMemoryToolCatalog(())
            tool_executor = InMemoryToolExecutor({}, {})
        elif _selection(runtime_config, "tool.catalog") is not None:
            tool_catalog, tool_executor = await self._create_tools(
                extension_host,
                process_root,
                scope_handles,
                runtime_config,
                plugin_declarations,
                tenant_id=tenant_id,
                agent_id=selected_agent,
            )
        else:
            tool_catalog = InMemoryToolCatalog(())
            tool_executor = InMemoryToolExecutor({}, {})
        readiness = None
        if self.options.check_readiness:
            from sagents.v2.agent.management.readiness import resource_readiness

            reports = {}
            for member_id in models_by_agent:
                reports[member_id] = await resource_readiness(
                    resolved.agents[member_id],
                    tool_catalog,
                    skill_provider=self.options.skill_provider,
                    management=self.options.agent_management,
                    deferred_tools=uses_binding_tools,
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
        if self.options.tool_runtime is not None:
            self.options.tool_runtime.artifact_store = bind_artifact_store(
                services["artifact.store"],
                self.options.tool_runtime.sandbox.ref.owner_run_id,
            )
            self.options.tool_runtime.memory_service = memory_service
            self.options.tool_runtime.session_memory_service = session_memory_service
            self.options.tool_runtime.goal_state_service = goal_state_service
            self.options.tool_runtime.tool_selection_policy = tool_selection
        control_runtime = HarnessRuntime(
            session_store,
            job_runtime=services["execution.job-runtime"],
        )
        driver_runtime = HarnessRuntime(
            driver_session_store,
            job_runtime=services["execution.job-runtime"],
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
        flow_tool_nodes = dict(self.options.flow_tool_nodes)
        if uses_flow:
            for selection in runtime_config.selections("flow.node"):
                if selection.name in flow_tool_nodes:
                    raise ValueError(f"duplicate Flow node binding {selection.name!r}")
                descriptor = self.extensions.get(selection.plugin).descriptor
                node_scope = selection.scope or descriptor.resolved_default_scope()
                if node_scope == ExtensionScope.RUN:
                    raise ValueError(
                        "Builder flow.node bindings require process, tenant or agent scope"
                    )
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
                allow_delegation=False,
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

        def make_loop(
            run_id,
            selected_catalog,
            selected_executor,
            continuation_runtime: OfficialToolRuntime | None,
        ):
            # Each root driver receives a private mutable registry. Dynamic Fibre
            # members therefore cannot leak into another Session built here.
            registry = AgentRegistry(member_descriptors)

            def compose_with_runtime(
                descriptor,
                catalog,
                executor,
                active_runtime: OfficialToolRuntime | None,
            ):
                if self.options.extra_tools:
                    from sagents.v2.tool import (
                        CompositeToolCatalog,
                        CompositeToolExecutor,
                    )

                    catalog = CompositeToolCatalog(
                        (catalog, *(pair[0] for pair in self.options.extra_tools))
                    )
                    executor = CompositeToolExecutor(
                        (executor, *(pair[1] for pair in self.options.extra_tools))
                    )
                if self.options.agent_management is not None:
                    from sagents.v2.tool import (
                        CompositeToolCatalog,
                        CompositeToolExecutor,
                    )

                    catalog = CompositeToolCatalog(
                        (catalog, self.options.agent_management.catalog)
                    )
                    executor = CompositeToolExecutor(
                        (executor, self.options.agent_management.executor)
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
                    models_by_agent[definition_id] = models_by_agent[selected_agent]
                definition = effective_resolved.agents[definition_id]
                member_components = component_sets.get(
                    definition_id, root_components
                )
                skill_loader = None
                self_configuration = (
                    self.options.self_configuration_factory(definition_id)
                    if self.options.self_configuration_factory is not None
                    else None
                )
                if (
                    self_configuration is not None
                    and self.options.skill_provider is None
                ):
                    raise ValueError(
                        "with_self_configuration requires with_skill_provider"
                    )
                if self.options.skill_provider is not None and (
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

                    skill_catalog, skill_source, skill_workspace = (
                        self.options.skill_provider
                    )
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
                        self.options.admitted_run_contract[1]
                        if self.options.admitted_run_contract
                        and self.options.admitted_run_contract[0] == run_id
                        else None
                    ),
                    memory_recall_query_generator=member_components.memory_query_generator,
                    tool_selection_model=models_by_agent[descriptor.agent_id],
                    artifact_store=(
                        active_runtime.artifact_store
                        if active_runtime is not None
                        else bind_artifact_store(services["artifact.store"], run_id)
                    ),
                    model=models_by_agent[descriptor.agent_id],
                    tool_catalog=catalog,
                    tool_executor=executor,
                    memory_service=(
                        memory_services_by_agent.get(definition_id, memory_service)
                        if member_memory_enabled and definition.memory.recall
                        else None
                    ),
                    session_memory_service=(
                        session_memory_service if member_memory_enabled else None
                    ),
                    tool_policy=self.options.tool_policy,
                    approval_memory=approval_memory,
                    continuation_policy=member_components.continuation_policy,
                    continuation_signal_provider=(
                        active_runtime.consume_continuation_signals
                        if active_runtime is not None
                        else None
                    ),
                    goal_state_service=goal_state_service,
                    tool_selection_policy=tool_selection,
                    additional_runtime_tools=runtime_tools,
                    granted_catalogs=tuple(
                        pair[0] for pair in self.options.extra_tools
                    ),
                    skill_loader=skill_loader,
                    self_configuration=self_configuration,
                    additional_context_providers=(
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

            async def compose_bound_child(descriptor, child_run_id, child_context):
                assert self.options.execution_binding_provider is not None
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
                )
                binding = await self.options.execution_binding_provider.acquire(request)
                try:
                    binding.validate_for(request)
                    child_tools = await bound_tools.compose(
                        binding,
                        tenant_id=tenant_id or child_context.actor.tenant_id,
                        agent_id=descriptor.agent_id,
                    )
                    return (
                        compose_with_runtime(
                            descriptor,
                            child_tools.catalog,
                            child_tools.executor,
                            child_tools.runtime,
                        ),
                        _CompositeRunResource(binding, child_tools.scope),
                    )
                except BaseException as exc:
                    try:
                        await binding.close()
                    except BaseException as close_exc:
                        raise exc from close_exc
                    raise

            async def reject_prebound_child(descriptor, child_run_id, child_context):
                del descriptor, child_run_id, child_context
                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="execution.binding_owner_mismatch",
                        category=ErrorCategory.AUTHORIZATION,
                        message=(
                            "a pre-bound tool runtime cannot be reused by a child Run; "
                            "use with_execution_binding_provider"
                        ),
                    )
                )

            child_factory = None
            if uses_binding_tools:
                child_factory = compose_bound_child
            elif self.options.tool_runtime is not None:
                child_factory = reject_prebound_child

            mode_factory = ModeAwareAgentLoopFactory(
                runtime=driver_runtime,
                model_factory=lambda descriptor, _: models_by_agent[
                    descriptor.agent_id
                ],
                base_catalog=selected_catalog,
                base_executor=selected_executor,
                registry=registry,
                resolved_spec_hash=(
                    self.options.admitted_run_contract[1]
                    if self.options.admitted_run_contract
                    else runtime_composition_hash or resolved.manifest_hash
                ),
                delegation_concurrency_limiter=delegation_limiter,
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
            if uses_flow:
                from sagents.v2.flow import FlowRuntime
                from sagents.v2.flow.driver import AgentFlowDriver
                from sagents.v2.flow.plugins.agent import NativeAgentFlowNode

                flow_runtime = FlowRuntime(
                    runtime=driver_runtime,
                    flows=resolved.flows,
                    agent_nodes={
                        descriptor.agent_id: NativeAgentFlowNode(
                            runtime=driver_runtime,
                            descriptor=descriptor,
                            child_executor=mode_factory.child_executor,
                        )
                        for descriptor in member_descriptors
                    },
                    tool_nodes=flow_tool_nodes,
                    max_node_visits=selected_definition.max_steps or 100,
                )
                return AgentFlowDriver(
                    flow_runtime,
                    selected_definition.entrypoint.flow,
                    mode_factory.child_executor,
                )
            return mode_factory.create_loop(root_descriptor, run_id)

        def driver_factory(run_id):
            if not uses_binding_tools:
                loop = make_loop(
                    run_id, tool_catalog, tool_executor, self.options.tool_runtime
                )
                if self.options.tool_runtime is not None:
                    return _OwnerValidatedCompatibilityDriver(
                        loop, self.options.tool_runtime, run_id
                    )
                return loop

            async def loop_builder(binding: RunExecutionBinding):
                tools = await bound_tools.compose(
                    binding, tenant_id=tenant_id, agent_id=selected_agent,
                )
                return (
                    make_loop(
                        run_id,
                        tools.catalog,
                        tools.executor,
                        tools.runtime,
                    ),
                    tools.scope,
                )

            return _ExecutionBoundDriver(
                runtime=control_runtime,
                provider=self.options.execution_binding_provider,
                run_id=run_id,
                agent_id=selected_agent,
                loop_builder=loop_builder,
            )

        session_access = AuthorizedSessionAccess(
            session_store,
            runtime=control_runtime,
            derived_state=(
                derived_state if derived_state is not session_store else None
            ),
            derived_state_cleaners=(session_memory_service,),
        )
        agent = SAgent(
            runtime=control_runtime,
            driver_factory=self.options.run_driver_factory or driver_factory,
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
        dispatcher = self.options.dispatcher or LocalWorkerDispatcher(
            scheduler,
            max_concurrent_runs=int(dispatcher_values.get("max_concurrent_runs", 8)),
            max_concurrent_runs_per_tenant=tenant_limit,
            lease_seconds=float(dispatcher_values.get("lease_seconds", 30.0)),
            lease_scope_factory=driver_session_store.lease_scope,
        )
        services["execution.dispatcher"] = dispatcher
        composition_hash = self._composition_hash(
            resolved.manifest_hash, scope_handles, services,
            registry=self.extensions if self.options.revision_identity else None,
        )
        runtime_composition_hash = composition_hash
        agent.attach_dispatcher(dispatcher)
        if self.options.dispatcher is None:
            dispatcher.attach_recovery_agent(agent)
        if not self.options.defer_dispatcher_start:
            await dispatcher.start()
        resolved_plan = self._resolved_application_plan(
            package_id=resolved.package_id,
            manifest_hash=resolved.manifest_hash,
            entrypoint_agent_id=selected_agent,
            handles=scope_handles,
            services=services,
            composition_hash=composition_hash,
            host_capabilities=frozenset(
                capability
                for capability, injected in (
                    ("session.store", self.options.session_store),
                    ("derived-state.store", self.options.derived_state_store),
                    ("memory.provider", self.options.memory_provider),
                    ("session-memory.provider", self.options.session_memory_provider),
                    (
                        "model.provider",
                        self.options.model_provider
                        or self.options.model_provider_factory,
                    ),
                    ("execution.job-runtime", self.options.job_runtime),
                    ("execution.scheduler", self.options.scheduler),
                    ("tool.catalog", self.options.tool_catalog),
                    ("tool.executor", self.options.tool_executor),
                    ("tool.selection-policy", self.options.tool_selection),
                    (
                        "agent.approval-memory",
                        self.options.approval_memory
                        or self.options.approval_memory_layer,
                    ),
                    ("observability.log-sink", self.options.log_sink),
                    ("observability.diagnostic-sink", self.options.diagnostic_sink),
                )
                if injected is not None
            ),
            unfenced_host_capabilities=(
                ("agent.tool-policy",) if self.options.tool_policy is not None else ()
            ),
            deferred_plugins=(
                ((OfficialToolPlugin.plugin_id, ExtensionScope.RUN),)
                if uses_binding_tools
                else ()
            ),
        )
        application = SAgentApplication(
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
            owned_resources=(*reversed(self.options.owned_resources), *((dispatcher,) if self.options.dispatcher is None else ())),
            resource_readiness=readiness,
        )
        application._attach_composer(
            AgentMaterializer(
                host=extension_host,
                process_root=process_root,
                extensions=self.extensions,
                process_plan=resolved_plan,
                summary_store=root_components.context.summary_store,
                derived_state=derived_state,
                process_model=models_by_agent[selected_agent],
                models={"models": resolved.model_routes, "credentials": resolved.credentials},
                default_tenant_id=tenant_id,
                deployment_profile=runtime_config.deployment_profile,
            )
        )
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
            if not self.extensions.contains(declaration.id):
                self.extensions.register(
                    load_installed_extension(
                        declaration.id,
                        version_requirement=declaration.version,
                    )
                )
            validate_extension_version(
                self.extensions.get(declaration.id), declaration.version
            )

    async def _create_session_store(
        self, host, parent, handles, runtime, declarations
    ) -> SessionStore:
        selection = _selection(runtime, "session.store")
        plugin_id = selection.plugin if selection else FilesystemSessionStore.plugin_id
        config = dict(selection.config if selection else {})
        if plugin_id == FilesystemSessionStore.plugin_id and "root" not in config:
            if self.options.session_root is None:
                raise ValueError("filesystem SessionStore requires session_root")
            config["root"] = str(self.options.session_root)
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
            if self.options.session_root is None:
                raise ValueError("SQLite Session Memory requires a root")
            config["root"] = str(self.options.session_root / "session-memory")
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
    ):
        agent = resolved.agents[agent_id]
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
            {"route": route_data, "client": self.options.model_client},
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

    async def _create_tools(
        self,
        host,
        parent,
        handles,
        runtime: RuntimeConfig,
        declarations: tuple[PluginDeclaration, ...],
        *,
        runtime_override: OfficialToolRuntime | None = None,
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
        if selection.plugin == OfficialToolPlugin.plugin_id:
            runtime = (
                config.get("runtime") or runtime_override or self.options.tool_runtime
            )
            if runtime is not None:
                config["runtime"] = runtime
            else:
                raise ValueError(
                    f"{OfficialToolPlugin.plugin_id} requires "
                    "SAgentBuilder.with_tool_runtime(runtime)"
                )
        catalog, handle = await self._instantiate(
            host,
            parent,
            handles,
            selection.plugin,
            config,
            "tool.catalog",
            scope=scope_override or selection.scope or ExtensionScope.AGENT,
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
            handles.remove(handle)
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
        selection = _selection(runtime, "tool.selection-policy")
        plugin_id = (
            selection.plugin
            if selection is not None
            else LLMToolSelectionPolicy.plugin_id
        )
        if plugin_id in {"hybrid", "sage.tool-selection.hybrid"}:
            plugin_id = LLMToolSelectionPolicy.plugin_id
        config = _merge_plugin_config(
            declarations,
            plugin_id,
            dict(selection.config if selection is not None else {}),
        )
        return await self._instantiate(
            host,
            parent,
            handles,
            plugin_id,
            config,
            "tool.selection-policy",
            scope=selection.scope
            if selection and selection.scope
            else ExtensionScope.AGENT,
            scope_id="agent-tool-selection",
            tenant_id=tenant_id,
            agent_id=agent_id,
            offer_name=self._selected_offer_name(
                plugin_id, "tool.selection-policy", selection.name
            )
            if selection
            else None,
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
        return await self._instantiate(
            host,
            parent,
            handles,
            plugin_id,
            config,
            capability,
            scope=selection.scope if selection and selection.scope else default_scope,
            scope_id=f"application-{capability.replace('.', '-')}",
            tenant_id=tenant_id,
            agent_id=agent_id,
            run_id=run_id,
            offer_name=self._selected_offer_name(plugin_id, capability, selection.name)
            if selection
            else None,
        )

    async def _instantiate(
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
    ):
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
            register=handles.append,
        )
        return (value, handle) if return_handle else value

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
            "execution.scheduler": self.options.scheduler
            if self.options.scheduler is not None
            else await self._create_capability(
                host,
                parent,
                handles,
                runtime,
                declarations,
                capability="execution.scheduler",
                default_plugin=InMemoryScheduler.plugin_id,
            ),
            "execution.job-runtime": self.options.job_runtime
            if self.options.job_runtime is not None
            else await self._create_capability(
                host,
                parent,
                handles,
                runtime,
                declarations,
                capability="execution.job-runtime",
                default_plugin=InMemoryJobRuntime.plugin_id,
                default_config={"runners": {}},
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
                self.options.diagnostic_sink
                if self.options.diagnostic_sink is not None
                else await self._create_capability(
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
                self.options.log_sink
                if self.options.log_sink is not None
                else await self._create_capability(
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
    def _composition_hash(manifest_hash, handles, services, *, registry=None) -> str:
        payload = {
            "manifest": manifest_hash,
            "plans": (sorted(registry.inventory(), key=lambda item: item["plugin_id"])
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

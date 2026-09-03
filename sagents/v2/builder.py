"""Public composition root for SAgents v2.

``SAgentBuilder`` is the only place that selects concrete plugins. The Kernel
and Agent loop receive frozen interfaces and never discover global providers.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from sagents.v2.agent.factory import AgentCompositionFactory
from sagents.v2.agent.policy import CompositeContinuationPolicy
from sagents.v2.context import (
    ExtractiveConversationSummarizer,
    JsonHeuristicTokenEstimator,
    PersistentSummaryContextReducer,
    ReferenceContextUnitCompactor,
    SessionDerivedConversationSummaryStore,
)
from sagents.v2.interfaces.protocols.native import NativeProtocolAdapter
from sagents.v2.package.registry import InMemoryAgentPackageRegistry
from sagents.v2.runtime.artifact import InMemoryArtifactStore
from sagents.v2.runtime.credentials import EnvironmentCredentialProvider
from sagents.v2.runtime.execution.jobs import InMemoryJobRuntime
from sagents.v2.runtime.execution.scheduler import InMemoryScheduler
from sagents.v2.tool.plugins.official import OfficialToolPlugin
from sagents.v2.tool.plugins.selection_llm import LLMToolSelectionPolicy
from sagents.v2.workspace import BareWorkspaceInitializer
from sagents.v2.agent.modes import ModeAwareAgentLoopFactory
from sagents.v2.agent.multi_agent import (
    AgentDescriptor,
    AgentMode,
    AgentRegistry,
    AgentRosterContextProvider,
    DelegationConcurrencyLimiter,
)
from sagents.v2.model import ModelProvider, RecordingModelProvider
from sagents.v2.goal import GoalStateService
from sagents.v2.tool import (
    ToolCatalog,
    ToolExecutor,
    ToolSelectionPolicy,
)
from sagents.v2.runtime import HarnessRuntime
from sagents.v2.runtime.execution import (
    ExecutionBindingProvider,
    ExecutionBindingRequest,
    LocalWorkerDispatcher,
    RunExecutionBinding,
)
from sagents.v2.package.manifest.resolver import ResolvedSageManifest
from sagents.v2.package.manifest.resolver import CompositionResolver
from sagents.v2.package.manifest.root import PluginDeclaration
from sagents.v2.package.manifest.runtime import CapabilitySelection, RuntimeConfig
from sagents.v2.context.components import ContextComponentBundle
from sagents.v2.memory import (
    DirectMemoryRecallQueryGenerator,
    MemoryProvider,
    MemoryService,
    NoopMemoryProvider,
)
from sagents.v2.model.protocols import model_protocol_descriptor
from sagents.v2.package.manifest.loader import SageManifestLoader
from sagents.v2.package.manifest.root import SageManifest
from sagents.v2.runtime.credentials import CredentialRef
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.runtime.extensions import (
    CapabilityRequirement,
    ExtensionHost,
    ExtensionRegistration,
    ExtensionRegistry,
    ExtensionScope,
    ExtensionScopeContext,
    load_installed_extension,
    validate_extension_version,
)
from sagents.v2.runtime.extensions.official import builtin_extension_registry
from sagents.v2.runtime.session import (
    AuthorizedSessionAccess,
    DerivedStateStore,
    FilesystemSessionStore,
    InMemoryDerivedStateStore,
    LeaseFencedSessionStore,
    SessionStore,
)
from sagents.v2.session_memory import (
    NoopSessionMemoryProvider,
    SessionMemoryProvider,
    SessionMemoryService,
    SqliteBm25SessionMemoryProvider,
)
from sagents.v2.sagent import SAgent
from sagents.v2.application import (
    MaterializedAgentPorts,
    ResolvedApplicationPlan,
    ResolvedProviderBinding,
    SAgentApplication,
)
from sagents.v2.tool.plugins.ephemeral import (
    InMemoryToolCatalog,
    InMemoryToolExecutor,
)
from sagents.v2.tool.official import OfficialToolRuntime
from sagents.v2.runtime.observability import (
    DiagnosticSink,
    LogSink,
    NoopDiagnosticSink,
    NoopLogSink,
    NoopTraceSink,
)


class _ExecutionBoundDriver:
    """Lazily compose a loop after the Runtime has allocated its Run ID."""

    def __init__(
        self,
        *,
        runtime,
        provider: ExecutionBindingProvider,
        run_id: str,
        agent_id: str,
        loop_builder,
    ) -> None:
        self.runtime = runtime
        self.provider = provider
        self.run_id = run_id
        self.agent_id = agent_id
        self.loop_builder = loop_builder
        self.binding: RunExecutionBinding | None = None
        self.scope_handle = None
        self.loop = None
        self._lock = None

    async def _ensure_loop(self, context):
        if self.loop is not None:
            return self.loop
        if self._lock is None:
            import asyncio

            self._lock = asyncio.Lock()
        async with self._lock:
            if self.loop is not None:
                return self.loop
            command = await self.runtime.session_store.get_start_command(self.run_id)
            policy = str(
                command.config.metadata.get("workspace_policy") or "shared_parent"
            )
            request = ExecutionBindingRequest(
                run_id=self.run_id,
                parent_run_id=command.parent_run_id,
                agent_id=self.agent_id,
                workspace_policy=policy,
                context=context,
            )
            binding = await self.provider.acquire(request)
            try:
                binding.validate_for(request)
                loop = self.loop_builder(binding)
                if hasattr(loop, "__await__"):
                    loop = await loop
                if isinstance(loop, tuple):
                    loop, self.scope_handle = loop
            except BaseException as exc:
                try:
                    await binding.close()
                except BaseException as close_exc:
                    raise exc from close_exc
                raise
            self.binding = binding
            self.loop = loop
            return self.loop

    async def execute(self, run_id, context):
        return await (await self._ensure_loop(context)).execute(run_id, context)

    async def resume(self, run_id, context):
        return await (await self._ensure_loop(context)).resume(run_id, context)

    async def recover_interrupted(self, run_id, context):
        loop = await self._ensure_loop(context)
        recover = getattr(loop, "recover_interrupted", None)
        return None if recover is None else await recover(run_id, context)

    async def on_suspended(self, context) -> None:
        if self.binding is not None:
            await self.binding.on_suspended(context)

    async def close(self) -> None:
        if self.scope_handle is not None:
            await self.scope_handle.close()
        if self.binding is not None:
            await self.binding.close()


class _OwnerValidatedCompatibilityDriver:
    """Fail closed when a pre-bound Tool runtime belongs to another Run."""

    def __init__(self, loop, tool_runtime: OfficialToolRuntime, run_id: str) -> None:
        self.loop = loop
        self.tool_runtime = tool_runtime
        self.run_id = run_id

    def _validate(self) -> None:
        if self.tool_runtime.sandbox.ref.owner_run_id != self.run_id:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="execution.binding_owner_mismatch",
                    category=ErrorCategory.AUTHORIZATION,
                    message=(
                        "with_tool_runtime sandbox owner does not match the actual "
                        "Run; use with_execution_binding_provider"
                    ),
                    safe_to_resume=False,
                )
            )

    async def execute(self, run_id, context):
        self._validate()
        return await self.loop.execute(run_id, context)

    async def resume(self, run_id, context):
        self._validate()
        return await self.loop.resume(run_id, context)

    async def recover_interrupted(self, run_id, context):
        self._validate()
        recover = getattr(self.loop, "recover_interrupted", None)
        return None if recover is None else await recover(run_id, context)


class _CompositeRunResource:
    def __init__(self, *resources) -> None:
        self.resources = resources

    async def close(self) -> None:
        for resource in reversed(self.resources):
            closed = resource.close()
            if hasattr(closed, "__await__"):
                await closed


class SAgentBuilder:
    """Select plugins once and build a fully injected in-process SAgent.

    Hosts may supply concrete providers directly or register additional
    factories. Direct injection is useful when a provider owns an existing
    client connection; registered factories remain the source of inventory and
    normal manifest-driven selection.
    """

    def __init__(self) -> None:
        self.extensions = builtin_extension_registry()
        self._session_root: Path | None = None
        self._session_store: SessionStore | None = None
        self._derived_state_store: DerivedStateStore | None = None
        self._memory_provider: MemoryProvider | None = None
        self._session_memory_provider: SessionMemoryProvider | None = None
        self._model_provider: ModelProvider | None = None
        self._tool_catalog: ToolCatalog | None = None
        self._tool_executor: ToolExecutor | None = None
        self._tool_runtime: OfficialToolRuntime | None = None
        self._tool_selection: ToolSelectionPolicy | None = None
        self._execution_binding_provider: ExecutionBindingProvider | None = None
        self._log_sink: LogSink | None = None
        self._diagnostic_sink: DiagnosticSink | None = None
        self._model_client: Any | None = None

    def with_defaults(self, *, session_root: str | Path) -> "SAgentBuilder":
        self._session_root = Path(session_root).expanduser().resolve()
        return self

    def register(self, registration: ExtensionRegistration) -> "SAgentBuilder":
        self.extensions.register(registration)
        return self

    def with_session_store(self, value: SessionStore) -> "SAgentBuilder":
        self._session_store = value
        return self

    def with_derived_state_store(self, value: DerivedStateStore) -> "SAgentBuilder":
        """Inject rebuildable state independently from authoritative Sessions."""

        self._derived_state_store = value
        return self

    def with_memory_provider(self, value: MemoryProvider) -> "SAgentBuilder":
        self._memory_provider = value
        return self

    def with_session_memory_provider(
        self, value: SessionMemoryProvider
    ) -> "SAgentBuilder":
        self._session_memory_provider = value
        return self

    def with_model_provider(self, value: ModelProvider) -> "SAgentBuilder":
        self._model_provider = value
        return self

    def with_model_client(self, value: Any) -> "SAgentBuilder":
        self._model_client = value
        return self

    def with_tool_provider(
        self, catalog: ToolCatalog, executor: ToolExecutor
    ) -> "SAgentBuilder":
        self._tool_catalog = catalog
        self._tool_executor = executor
        return self

    def with_tool_runtime(self, runtime: OfficialToolRuntime) -> "SAgentBuilder":
        """Inject the V2-native runtime used by the official Tool plugin."""

        self._tool_runtime = runtime
        return self

    def with_execution_binding_provider(
        self, provider: ExecutionBindingProvider
    ) -> "SAgentBuilder":
        """Inject the Host port that allocates resources for actual Run IDs."""

        self._execution_binding_provider = provider
        return self

    def with_tool_selection(self, value: ToolSelectionPolicy) -> "SAgentBuilder":
        """Inject the model-visible Tool projection policy."""

        self._tool_selection = value
        return self

    def with_log_sink(self, value: LogSink) -> "SAgentBuilder":
        """Inject a process log sink the host already owns."""

        self._log_sink = value
        return self

    def with_diagnostic_sink(self, value: DiagnosticSink) -> "SAgentBuilder":
        """Inject a process diagnostic sink the host already owns."""

        self._diagnostic_sink = value
        return self

    def inventory(self) -> tuple[dict, ...]:
        return self.extensions.inventory()

    async def build(
        self,
        package: SageManifest | ResolvedSageManifest | str | Path,
        *,
        tenant_id: str | None = None,
        agent_id: str | None = None,
    ) -> SAgentApplication:
        """Resolve one composition and open all provider scopes asynchronously."""

        scope_handles = []
        try:
            return await self._build_application(
                package,
                tenant_id=tenant_id,
                agent_id=agent_id,
                scope_handles=scope_handles,
            )
        except BaseException as exc:
            for handle in reversed(scope_handles):
                try:
                    await handle.close()
                except BaseException as close_exc:
                    exc.add_note(f"scope rollback also failed: {close_exc}")
            raise

    async def _build_application(
        self,
        package: SageManifest | ResolvedSageManifest | str | Path,
        *,
        tenant_id: str | None,
        agent_id: str | None,
        scope_handles: list,
    ) -> SAgentApplication:

        manifest, resolved = self._resolve_package(package)
        plugin_declarations = (
            manifest.plugins if manifest is not None else resolved.plugins
        )
        runtime_config = manifest.runtime if manifest is not None else resolved.runtime
        self._load_declared_plugins(plugin_declarations)
        extension_host = ExtensionHost(self.extensions)
        process_root = await extension_host.open_scope(
            ExtensionScopeContext(
                scope=ExtensionScope.PROCESS,
                scope_id=f"application-{resolved.package_id}",
            ),
            extension_host.plan(()),
        )
        scope_handles.append(process_root)
        uses_binding_tools = (
            self._execution_binding_provider is not None
            and self._selected_plugin(runtime_config, "tool.catalog")
            == OfficialToolPlugin.plugin_id
        )
        selected_agent = agent_id or resolved.entrypoint_agent
        if selected_agent is None:
            raise ValueError("SAgentBuilder requires an Agent entrypoint")
        if selected_agent not in resolved.agents:
            raise ValueError(f"unknown Agent entrypoint {selected_agent!r}")
        if (
            (self._tool_catalog is None or self._tool_executor is None)
            and self._selected_plugin(runtime_config, "tool.catalog")
            == OfficialToolPlugin.plugin_id
            and self._tool_runtime is None
            and self._execution_binding_provider is None
        ):
            raise ValueError(
                f"{OfficialToolPlugin.plugin_id} requires with_execution_binding_provider(provider) "
                "or the compatibility with_tool_runtime(runtime)"
            )
        session_store = self._session_store
        session_store_was_injected = session_store is not None
        if session_store is None:
            session_store = await self._create_session_store(
                extension_host,
                process_root,
                scope_handles,
                runtime_config,
                plugin_declarations,
            )
        derived_state = self._derived_state_store
        if derived_state is None:
            # Built-in Session stores explicitly provide colocated derived data.
            # A host-injected authoritative store is not assumed to do so.
            derived_state = (
                InMemoryDerivedStateStore()
                if session_store_was_injected
                else session_store
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
        memory_provider = self._memory_provider
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
        )
        session_memory_provider = self._session_memory_provider
        if session_memory_provider is None:
            session_memory_provider = await self._create_session_memory_provider(
                extension_host,
                process_root,
                scope_handles,
                runtime_config,
                plugin_declarations,
            )
        session_memory_service = SessionMemoryService(session_memory_provider)
        model = self._model_provider
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
        for member_id in selected_definition.subagents:
            if member_id in models_by_agent:
                continue
            member_model = (
                self._model_provider
                if self._model_provider is not None
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
        tool_selection = self._tool_selection or await self._create_tool_selection(
            extension_host,
            process_root,
            scope_handles,
            runtime_config,
            plugin_declarations,
            tenant_id=tenant_id,
            agent_id=selected_agent,
        )
        if self._tool_catalog is not None and self._tool_executor is not None:
            tool_catalog, tool_executor = self._tool_catalog, self._tool_executor
        elif (
            self._execution_binding_provider is not None
            and self._selected_plugin(runtime_config, "tool.catalog")
            == OfficialToolPlugin.plugin_id
        ):
            # The real provider pair is composed lazily from the actual Run
            # binding. These placeholders are never exposed to that driver.
            tool_catalog = InMemoryToolCatalog(())
            tool_executor = InMemoryToolExecutor({}, {})
        elif self._selection(runtime_config, "tool.catalog") is not None:
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
        if self._tool_runtime is not None:
            self._tool_runtime.memory_service = memory_service
            self._tool_runtime.session_memory_service = session_memory_service
            self._tool_runtime.goal_state_service = goal_state_service
            self._tool_runtime.tool_selection_policy = tool_selection
        control_runtime = HarnessRuntime(
            session_store,
            job_runtime=services["execution.job-runtime"],
        )
        driver_runtime = HarnessRuntime(
            driver_session_store,
            job_runtime=services["execution.job-runtime"],
        )
        token_estimator = await self._create_capability(
            extension_host,
            process_root,
            scope_handles,
            runtime_config,
            plugin_declarations,
            capability="context.token-estimator",
            default_plugin=JsonHeuristicTokenEstimator.plugin_id,
            default_scope=ExtensionScope.AGENT,
            tenant_id=tenant_id,
            agent_id=selected_agent,
        )
        summary_store = await self._create_capability(
            extension_host,
            process_root,
            scope_handles,
            runtime_config,
            plugin_declarations,
            capability="context.summary-store",
            default_plugin=SessionDerivedConversationSummaryStore.plugin_id,
            default_scope=ExtensionScope.AGENT,
            locked_config={"derived_state": derived_state},
            tenant_id=tenant_id,
            agent_id=selected_agent,
        )
        summarizer = await self._create_capability(
            extension_host,
            process_root,
            scope_handles,
            runtime_config,
            plugin_declarations,
            capability="context.summarizer",
            default_plugin=ExtractiveConversationSummarizer.plugin_id,
            default_scope=ExtensionScope.AGENT,
            locked_config={"model": models_by_agent[selected_agent]},
            tenant_id=tenant_id,
            agent_id=selected_agent,
        )
        unit_compactor = await self._create_capability(
            extension_host,
            process_root,
            scope_handles,
            runtime_config,
            plugin_declarations,
            capability="context.unit-compactor",
            default_plugin=ReferenceContextUnitCompactor.plugin_id,
            default_scope=ExtensionScope.AGENT,
            locked_config={"estimator": token_estimator},
            tenant_id=tenant_id,
            agent_id=selected_agent,
        )
        context_reducer = await self._create_capability(
            extension_host,
            process_root,
            scope_handles,
            runtime_config,
            plugin_declarations,
            capability="context.reducer",
            default_plugin=PersistentSummaryContextReducer.plugin_id,
            default_scope=ExtensionScope.AGENT,
            locked_config={
                "store": summary_store,
                "summarizer": summarizer,
                "estimator": token_estimator,
                "unit_compactor": unit_compactor,
            },
            tenant_id=tenant_id,
            agent_id=selected_agent,
        )
        continuation_policy = await self._create_capability(
            extension_host,
            process_root,
            scope_handles,
            runtime_config,
            plugin_declarations,
            capability="agent.continuation-policy",
            default_plugin=CompositeContinuationPolicy.plugin_id,
            default_scope=ExtensionScope.AGENT,
            locked_config={"model": models_by_agent[selected_agent]},
            tenant_id=tenant_id,
            agent_id=selected_agent,
        )
        components = ContextComponentBundle(
            token_estimator=token_estimator,
            summary_store=summary_store,
            summarizer=summarizer,
            reducer=context_reducer,
        )
        factory = AgentCompositionFactory(driver_runtime, context_components=components)
        root_descriptor = AgentDescriptor(
            agent_id=selected_agent,
            name=selected_definition.name,
            description="",
            instructions=selected_definition.instructions,
            mode=AgentMode(selected_definition.mode),
            tools=selected_definition.tools,
            skills=selected_definition.skills,
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
                allow_delegation=False,
            )
            for member_id in selected_definition.subagents
        )

        def configure_official_runtime(value: OfficialToolRuntime) -> None:
            value.memory_service = memory_service
            value.session_memory_service = session_memory_service
            value.goal_state_service = goal_state_service
            value.tool_selection_policy = tool_selection
            value.bind_job_runtime(services["execution.job-runtime"])

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
                member_memory_enabled = "search_memory" in definition.tools
                return factory.create_loop(
                    effective_resolved,
                    definition_id,
                    model=models_by_agent[descriptor.agent_id],
                    tool_catalog=catalog,
                    tool_executor=executor,
                    memory_service=(
                        memory_service
                        if member_memory_enabled and definition.memory.recall
                        else None
                    ),
                    session_memory_service=(
                        session_memory_service if member_memory_enabled else None
                    ),
                    continuation_policy=continuation_policy,
                    continuation_signal_provider=(
                        active_runtime.consume_continuation_signals
                        if active_runtime is not None
                        else None
                    ),
                    goal_state_service=goal_state_service,
                    tool_selection_policy=tool_selection,
                    additional_runtime_tools=runtime_tools,
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
                assert self._execution_binding_provider is not None
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
                binding = await self._execution_binding_provider.acquire(request)
                try:
                    binding.validate_for(request)
                    child_runtime = OfficialToolRuntime(
                        binding.sandbox,
                        binding.grant_issuer,
                        job_runtime=services["execution.job-runtime"],
                    )
                    configure_official_runtime(child_runtime)
                    (
                        child_catalog,
                        child_executor,
                        child_scope,
                    ) = await self._create_tools(
                        extension_host,
                        process_root,
                        scope_handles,
                        runtime_config,
                        plugin_declarations,
                        runtime_override=child_runtime,
                        return_handle=True,
                        scope_override=ExtensionScope.RUN,
                        tenant_id=tenant_id or child_context.actor.tenant_id,
                        agent_id=descriptor.agent_id,
                        run_id=child_run_id,
                    )
                    return (
                        compose_with_runtime(
                            descriptor,
                            child_catalog,
                            child_executor,
                            child_runtime,
                        ),
                        _CompositeRunResource(binding, child_scope),
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
            elif self._tool_runtime is not None:
                child_factory = reject_prebound_child

            mode_factory = ModeAwareAgentLoopFactory(
                runtime=driver_runtime,
                model_factory=lambda descriptor, _: models_by_agent[
                    descriptor.agent_id
                ],
                base_catalog=selected_catalog,
                base_executor=selected_executor,
                registry=registry,
                resolved_spec_hash=(runtime_composition_hash or resolved.manifest_hash),
                delegation_concurrency_limiter=delegation_limiter,
                loop_composer=compose,
                child_loop_factory=child_factory,
                trace_sink=services["observability.trace-sink"],
                log_sink=services["observability.log-sink"],
            )
            return mode_factory.create_loop(root_descriptor, run_id)

        def driver_factory(run_id):
            if not uses_binding_tools:
                loop = make_loop(
                    run_id, tool_catalog, tool_executor, self._tool_runtime
                )
                if self._tool_runtime is not None:
                    return _OwnerValidatedCompatibilityDriver(
                        loop, self._tool_runtime, run_id
                    )
                return loop

            async def loop_builder(binding: RunExecutionBinding):
                official_runtime = OfficialToolRuntime(
                    binding.sandbox,
                    binding.grant_issuer,
                    job_runtime=services["execution.job-runtime"],
                )
                configure_official_runtime(official_runtime)
                bound_catalog, bound_executor, run_scope = await self._create_tools(
                    extension_host,
                    process_root,
                    scope_handles,
                    runtime_config,
                    plugin_declarations,
                    runtime_override=official_runtime,
                    return_handle=True,
                    scope_override=ExtensionScope.RUN,
                    tenant_id=tenant_id,
                    agent_id=selected_agent,
                    run_id=run_id,
                )
                return (
                    make_loop(
                        run_id,
                        bound_catalog,
                        bound_executor,
                        official_runtime,
                    ),
                    run_scope,
                )

            return _ExecutionBoundDriver(
                runtime=control_runtime,
                provider=self._execution_binding_provider,
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
            "context.token-estimator": token_estimator,
            "context.summary-store": summary_store,
            "context.summarizer": summarizer,
            "context.unit-compactor": unit_compactor,
            "context.reducer": context_reducer,
            "agent.continuation-policy": continuation_policy,
        }
        await self._validate_required_guarantees(
            runtime_config,
            services=services,
            handles=scope_handles,
        )
        scheduler_config = self._selection(runtime_config, "execution.scheduler")
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
        dispatcher = LocalWorkerDispatcher(
            scheduler,
            max_concurrent_runs=int(dispatcher_values.get("max_concurrent_runs", 8)),
            max_concurrent_runs_per_tenant=tenant_limit,
            lease_seconds=float(dispatcher_values.get("lease_seconds", 30.0)),
            lease_scope_factory=driver_session_store.lease_scope,
        )
        services["execution.dispatcher"] = dispatcher
        composition_hash = self._composition_hash(
            resolved.manifest_hash, scope_handles, services
        )
        runtime_composition_hash = composition_hash
        agent.attach_dispatcher(dispatcher)
        dispatcher.attach_recovery_agent(agent)
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
                    ("session.store", self._session_store),
                    ("derived-state.store", self._derived_state_store),
                    ("memory.provider", self._memory_provider),
                    ("session-memory.provider", self._session_memory_provider),
                    ("model.provider", self._model_provider),
                    ("tool.catalog", self._tool_catalog),
                    ("tool.executor", self._tool_executor),
                    ("tool.selection-policy", self._tool_selection),
                    ("observability.log-sink", self._log_sink),
                    ("observability.diagnostic-sink", self._diagnostic_sink),
                )
                if injected is not None
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
            owned_resources=(dispatcher,),
        )
        application._attach_composer(
            _ApplicationComposer(
                host=extension_host,
                process_root=process_root,
                extensions=self.extensions,
                process_plan=resolved_plan,
                summary_store=summary_store,
                derived_state=derived_state,
                process_model=models_by_agent[selected_agent],
                default_tenant_id=tenant_id,
            )
        )
        return application

    def _resolve_package(self, package):
        if isinstance(package, ResolvedSageManifest):
            return None, package
        if isinstance(package, (str, Path)):
            package = SageManifestLoader().load(package)
        if not isinstance(package, SageManifest):
            raise TypeError(
                "package must be SageManifest, ResolvedSageManifest, or sage.yaml"
            )
        return package, CompositionResolver().resolve(package)

    def _load_declared_plugins(
        self, declarations: tuple[PluginDeclaration, ...]
    ) -> None:
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

    @staticmethod
    def _merge_plugin_config(
        declarations: tuple[PluginDeclaration, ...],
        plugin_id: str,
        selection_config: dict[str, Any],
    ) -> dict[str, Any]:
        defaults = next(
            (
                declaration.config
                for declaration in declarations
                if declaration.id == plugin_id
            ),
            {},
        )
        return {**defaults, **selection_config}

    async def _create_session_store(
        self, host, parent, handles, runtime, declarations
    ) -> SessionStore:
        selection = self._selection(runtime, "session.store")
        plugin_id = selection.plugin if selection else FilesystemSessionStore.plugin_id
        config = dict(selection.config if selection else {})
        if plugin_id == FilesystemSessionStore.plugin_id and "root" not in config:
            if self._session_root is None:
                raise ValueError("filesystem SessionStore requires session_root")
            config["root"] = str(self._session_root)
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
        selection = self._selection(runtime, "session-memory.provider")
        plugin_id = (
            selection.plugin if selection else NoopSessionMemoryProvider.plugin_id
        )
        config = dict(selection.config if selection else {})
        if (
            plugin_id == SqliteBm25SessionMemoryProvider.plugin_id
            and "root" not in config
        ):
            if self._session_root is None:
                raise ValueError("SQLite Session Memory requires a root")
            config["root"] = str(self._session_root / "session-memory")
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
        config = self._merge_plugin_config(
            declarations,
            plugin_id,
            {"route": route_data, "client": self._model_client},
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
        selection = self._selection(runtime, "tool.catalog")
        if selection is None:
            return InMemoryToolCatalog(()), InMemoryToolExecutor({}, {})
        config = self._merge_plugin_config(
            declarations, selection.plugin, dict(selection.config)
        )
        if selection.plugin == OfficialToolPlugin.plugin_id:
            runtime = config.get("runtime") or runtime_override or self._tool_runtime
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
        )
        executor = handle.providers.require(
            "tool.executor",
            self._offer_name(selection.plugin, "tool.executor"),
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
        selection = self._selection(runtime, "tool.selection-policy")
        plugin_id = (
            selection.plugin
            if selection is not None
            else LLMToolSelectionPolicy.plugin_id
        )
        if plugin_id in {"hybrid", "sage.tool-selection.hybrid"}:
            plugin_id = LLMToolSelectionPolicy.plugin_id
        config = self._merge_plugin_config(
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
        selection = self._selection(runtime, capability)
        plugin_id = selection.plugin if selection else default_plugin
        config = {
            **dict(default_config or {}),
            **dict(selection.config if selection else {}),
        }
        config = self._merge_plugin_config(declarations, plugin_id, config)
        # Host-owned runtime identities are dependencies, not user/plugin
        # configuration. Apply them last so a manifest cannot replace a model,
        # SessionStore, estimator, or another trusted composition input.
        config.update(
            self._supported_locked_config(
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
    ):
        registration = self.extensions.get(plugin_id)
        if capability not in {
            offer.capability for offer in registration.descriptor.provides
        }:
            raise ValueError(f"extension {plugin_id!r} does not provide {capability!r}")
        name = self._offer_name(plugin_id, capability)
        plan = host.plan(
            (
                CapabilityRequirement(
                    capability=capability,
                    api_version=(
                        "3" if capability == "execution.sandbox" else ">=2,<3"
                    ),
                    name=name,
                ),
            ),
            selections={capability: plugin_id},
            configs={plugin_id: config},
            scope_overrides={plugin_id: scope},
        )
        handle = await host.open_scope_hierarchy(
            ExtensionScopeContext(
                scope=scope,
                scope_id=scope_id,
                tenant_id=tenant_id,
                agent_id=(
                    agent_id
                    if scope in {ExtensionScope.AGENT, ExtensionScope.RUN}
                    else None
                ),
                run_id=run_id if scope == ExtensionScope.RUN else None,
            ),
            plan,
            parent=parent if scope != ExtensionScope.PROCESS else None,
        )
        handles.append(handle)
        value = handle.providers.require(capability, name)
        return (value, handle) if return_handle else value

    def _offer_name(self, plugin_id: str, capability: str) -> str:
        registration = self.extensions.get(plugin_id)
        return next(
            offer.name
            for offer in registration.descriptor.provides
            if offer.capability == capability
        )

    @staticmethod
    def _supported_locked_config(
        extensions: ExtensionRegistry,
        plugin_id: str,
        locked_config: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Inject host-owned values only when the selected plugin declares them."""

        schema = extensions.get(plugin_id).descriptor.config_schema or {}
        if schema.get("additionalProperties", True) is not False:
            return dict(locked_config)
        properties = set((schema.get("properties") or {}).keys())
        return {key: value for key, value in locked_config.items() if key in properties}

    @staticmethod
    def _selection(
        runtime: RuntimeConfig, capability: str
    ) -> CapabilitySelection | None:
        values = runtime.selections(capability)
        if len(values) > 1:
            raise ValueError(
                f"capability {capability!r} does not allow multiple selections here"
            )
        return values[0] if values else None

    def _selected_plugin(self, runtime: RuntimeConfig, capability: str) -> str | None:
        selection = self._selection(runtime, capability)
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
                default_config={"runners": {}},
            ),
            "artifact.store": await self._create_capability(
                host,
                parent,
                handles,
                runtime,
                declarations,
                capability="artifact.store",
                default_plugin=InMemoryArtifactStore.plugin_id,
            ),
            "package.registry": await self._create_capability(
                host,
                parent,
                handles,
                runtime,
                declarations,
                capability="package.registry",
                default_plugin=InMemoryAgentPackageRegistry.plugin_id,
            ),
            "observability.diagnostic-sink": (
                self._diagnostic_sink
                if self._diagnostic_sink is not None
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
                self._log_sink
                if self._log_sink is not None
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
                self._merge_plugin_config(
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

        if not runtime.required_guarantees:
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

        for capability, required in runtime.required_guarantees.items():
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
                    },
                )
            )

    @staticmethod
    def _composition_hash(manifest_hash, handles, services) -> str:
        payload = {
            "manifest": manifest_hash,
            "plans": sorted(
                handle.composition_hash for handle in handles if handle.graph.plugin_ids
            ),
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


class _ApplicationComposer:
    """Rematerialize Agent/Run ports on a live process Application."""

    def __init__(
        self,
        *,
        host,
        process_root,
        extensions,
        process_plan: ResolvedApplicationPlan,
        summary_store,
        derived_state,
        process_model=None,
        default_tenant_id: str | None = None,
    ) -> None:
        self.host = host
        self.process_root = process_root
        self.extensions = extensions
        self.process_plan = process_plan
        self.summary_store = summary_store
        self.derived_state = derived_state
        self.process_model = process_model
        self.default_tenant_id = default_tenant_id
        self.application: SAgentApplication | None = None
        self._cache: dict[tuple[str, ...], tuple[Any, Any]] = {}
        self._lock = None

    async def materialize_agent(
        self,
        package,
        *,
        tenant_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
        model: Any | None = None,
        tool_catalog: Any | None = None,
        tool_executor: Any | None = None,
        locked_configs: Mapping[str, Mapping[str, Any]] | None = None,
        cache_identities: Mapping[str, Any] | None = None,
    ) -> MaterializedAgentPorts:
        import asyncio

        if self._lock is None:
            self._lock = asyncio.Lock()
        tenant_id = tenant_id or self.default_tenant_id
        manifest, resolved = SAgentBuilder()._resolve_package(package)
        declarations = manifest.plugins if manifest is not None else resolved.plugins
        runtime = manifest.runtime if manifest is not None else resolved.runtime
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
        selected_agent = (
            agent_id
            or resolved.entrypoint_agent
            or self.process_plan.entrypoint_agent_id
        )
        locks = {
            capability: dict(config)
            for capability, config in dict(locked_configs or {}).items()
        }
        identities = dict(cache_identities or {})
        effective_model = model if model is not None else self.process_model
        run_handles: list[Any] = []
        selected_handles: list[Any] = []
        async with self._lock, self._close_run_handles_on_error(run_handles):
            estimator = await self._port(
                runtime,
                declarations,
                capability="context.token-estimator",
                default_plugin=JsonHeuristicTokenEstimator.plugin_id,
                default_scope=ExtensionScope.AGENT,
                scope_id=f"materialize-estimator:{selected_agent}",
                identities=identities,
                run_handles=run_handles,
                selected_handles=selected_handles,
                tenant_id=tenant_id,
                agent_id=selected_agent,
            )
            summarizer_lock = dict(locks.get("context.summarizer") or {})
            if effective_model is not None and "model" not in summarizer_lock:
                summarizer_lock["model"] = effective_model
            summarizer = await self._port(
                runtime,
                declarations,
                capability="context.summarizer",
                default_plugin=ExtractiveConversationSummarizer.plugin_id,
                default_scope=ExtensionScope.AGENT,
                scope_id=f"materialize-summarizer:{selected_agent}",
                locked_config=summarizer_lock,
                identities=identities,
                run_handles=run_handles,
                selected_handles=selected_handles,
                tenant_id=tenant_id,
                agent_id=selected_agent,
            )
            unit_compactor = await self._port(
                runtime,
                declarations,
                capability="context.unit-compactor",
                default_plugin=ReferenceContextUnitCompactor.plugin_id,
                default_scope=ExtensionScope.AGENT,
                scope_id=f"materialize-unit-compactor:{selected_agent}",
                locked_config={"estimator": estimator},
                identities=identities,
                run_handles=run_handles,
                selected_handles=selected_handles,
                tenant_id=tenant_id,
                agent_id=selected_agent,
            )
            reducer_lock = {
                "estimator": estimator,
                "store": self.summary_store,
                "summarizer": summarizer,
                "unit_compactor": unit_compactor,
                **dict(locks.get("context.reducer") or {}),
            }
            context_reducer = await self._port(
                runtime,
                declarations,
                capability="context.reducer",
                default_plugin=PersistentSummaryContextReducer.plugin_id,
                default_scope=ExtensionScope.AGENT,
                scope_id=f"materialize-reducer:{selected_agent}",
                locked_config=reducer_lock,
                identities=identities,
                run_handles=run_handles,
                selected_handles=selected_handles,
                tenant_id=tenant_id,
                agent_id=selected_agent,
            )
            tool_selection = await self._port(
                runtime,
                declarations,
                capability="tool.selection-policy",
                default_plugin=LLMToolSelectionPolicy.plugin_id,
                default_scope=ExtensionScope.AGENT,
                scope_id=f"materialize-tool-selection:{selected_agent}",
                locked_config=dict(locks.get("tool.selection-policy") or {}),
                identities=identities,
                run_handles=run_handles,
                selected_handles=selected_handles,
                tenant_id=tenant_id,
                agent_id=selected_agent,
            )
            continuation_lock = {"repeat_threshold": 3}
            if effective_model is not None:
                continuation_lock["model"] = effective_model
            continuation_lock.update(dict(locks.get("agent.continuation-policy") or {}))
            continuation_scope = (
                ExtensionScope.RUN if run_id is not None else ExtensionScope.AGENT
            )
            continuation = await self._port(
                runtime,
                declarations,
                capability="agent.continuation-policy",
                default_plugin=CompositeContinuationPolicy.plugin_id,
                default_scope=continuation_scope,
                scope_id=(
                    f"materialize-continuation:{selected_agent}:{run_id or 'agent'}"
                ),
                locked_config=continuation_lock,
                identities=identities,
                run_handles=run_handles,
                selected_handles=selected_handles,
                tenant_id=tenant_id,
                agent_id=selected_agent,
                run_id=run_id,
            )
            recall_lock = dict(locks.get("memory.recall-query") or {})
            if effective_model is not None and "model" not in recall_lock:
                recall_lock["model"] = effective_model
            memory_query = await self._port(
                runtime,
                declarations,
                capability="memory.recall-query",
                default_plugin=DirectMemoryRecallQueryGenerator.plugin_id,
                default_scope=ExtensionScope.AGENT,
                scope_id=f"materialize-recall-query:{selected_agent}",
                locked_config=recall_lock,
                identities=identities,
                run_handles=run_handles,
                selected_handles=selected_handles,
                tenant_id=tenant_id,
                agent_id=selected_agent,
            )
            workspace_lock = dict(locks.get("workspace.initializer") or {})
            workspace_initializer = await self._port(
                runtime,
                declarations,
                capability="workspace.initializer",
                default_plugin=BareWorkspaceInitializer.plugin_id,
                default_scope=ExtensionScope.AGENT,
                scope_id=f"materialize-workspace:{selected_agent}",
                locked_config=workspace_lock,
                identities=identities,
                run_handles=run_handles,
                selected_handles=selected_handles,
                tenant_id=tenant_id,
                agent_id=selected_agent,
            )
        resolved_plan = self._materialized_plan(
            resolved,
            selected_agent,
            selected_handles,
            model=model,
            tool_catalog=tool_catalog,
            tool_executor=tool_executor,
        )
        return MaterializedAgentPorts(
            token_estimator=estimator,
            summarizer=summarizer,
            context_reducer=context_reducer,
            continuation_policy=continuation,
            tool_selection_policy=tool_selection,
            tool_catalog=tool_catalog,
            tool_executor=tool_executor,
            memory_query_generator=memory_query,
            workspace_initializer=workspace_initializer,
            resolved_plan=resolved_plan,
            scope_handles=tuple(run_handles),
        )

    @asynccontextmanager
    async def _close_run_handles_on_error(self, handles):
        try:
            yield
        except BaseException as exc:
            failed_handles = []
            for handle in reversed(handles):
                try:
                    await handle.close()
                except BaseException as close_exc:
                    failed_handles.append(handle)
                    exc.add_note(f"materialization rollback also failed: {close_exc}")
            if self.application is not None:
                for handle in reversed(failed_handles):
                    if all(
                        handle is not existing
                        for existing in self.application._scope_handles
                    ):
                        self.application._scope_handles.append(handle)
            handles.clear()
            raise

    async def _port(
        self,
        runtime,
        declarations,
        *,
        capability,
        default_plugin,
        default_scope=ExtensionScope.AGENT,
        scope_id: str,
        locked_config=None,
        identities,
        run_handles,
        selected_handles,
        tenant_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
    ):
        selection = SAgentBuilder._selection(runtime, capability)
        plugin_id = selection.plugin if selection is not None else default_plugin
        if capability == "agent.continuation-policy" and plugin_id in {
            "hybrid",
            "sage.agent.continuation.hybrid",
        }:
            plugin_id = "sage.agent.continuation.llm-judge"
        if capability == "tool.selection-policy" and plugin_id in {
            "hybrid",
            "sage.tool-selection.hybrid",
        }:
            plugin_id = LLMToolSelectionPolicy.plugin_id
        config = {
            **dict(selection.config if selection is not None else {}),
        }
        config = SAgentBuilder._merge_plugin_config(declarations, plugin_id, config)
        config.update(
            SAgentBuilder._supported_locked_config(
                self.extensions, plugin_id, dict(locked_config or {})
            )
        )
        scope = (
            selection.scope
            if selection is not None and selection.scope is not None
            else default_scope
        )
        cacheable = scope != ExtensionScope.RUN
        identity = identities.get(capability)
        cache_tenant_id = (
            tenant_id
            if scope in {ExtensionScope.TENANT, ExtensionScope.AGENT}
            else None
        )
        cache_agent_id = agent_id if scope == ExtensionScope.AGENT else None
        cache_key = (
            capability,
            plugin_id,
            scope.value,
            scope_id,
            cache_tenant_id or "",
            cache_agent_id or "",
            _config_identity(identity if identity is not None else config),
        )
        if cacheable and cache_key in self._cache:
            handle, value = self._cache[cache_key]
            selected_handles.append(handle)
            return value
        parent = self.process_root
        if scope == ExtensionScope.RUN:
            parent = await self._agent_parent(tenant_id, agent_id or "default")
        value, handle = await self._instantiate(
            plugin_id,
            config,
            capability,
            scope=scope,
            scope_id=scope_id,
            parent=parent,
            tenant_id=tenant_id,
            agent_id=agent_id,
            run_id=run_id,
        )
        if cacheable:
            self._cache[cache_key] = (handle, value)
            if self.application is not None:
                self.application._scope_handles.append(handle)
        else:
            run_handles.append(handle)
        selected_handles.append(handle)
        return value

    async def _agent_parent(self, tenant_id: str | None, agent_id: str):
        cache_key = ("__agent_parent__", tenant_id or "", agent_id)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached[0]
        handle = await self.host.open_scope(
            ExtensionScopeContext(
                scope=ExtensionScope.AGENT,
                scope_id=f"materialize-agent:{tenant_id or 'default'}:{agent_id}",
                tenant_id=tenant_id,
                agent_id=agent_id,
            ),
            self.host.plan(()),
            parent=self.process_root,
        )
        self._cache[cache_key] = (handle, None)
        if self.application is not None:
            self.application._scope_handles.append(handle)
        return handle

    async def _instantiate(
        self,
        plugin_id: str,
        config: dict[str, Any],
        capability: str,
        *,
        scope: ExtensionScope,
        scope_id: str,
        parent,
        tenant_id: str | None,
        agent_id: str | None,
        run_id: str | None,
    ):
        registration = self.extensions.get(plugin_id)
        if capability not in {
            offer.capability for offer in registration.descriptor.provides
        }:
            raise ValueError(f"extension {plugin_id!r} does not provide {capability!r}")
        name = next(
            offer.name
            for offer in registration.descriptor.provides
            if offer.capability == capability
        )
        plan = self.host.plan(
            (
                CapabilityRequirement(
                    capability=capability,
                    api_version=(
                        "3" if capability == "execution.sandbox" else ">=2,<3"
                    ),
                    name=name,
                ),
            ),
            selections={capability: plugin_id},
            configs={plugin_id: config},
            scope_overrides={plugin_id: scope},
        )
        handle = await self.host.open_scope_hierarchy(
            ExtensionScopeContext(
                scope=scope,
                scope_id=scope_id,
                tenant_id=tenant_id,
                agent_id=(
                    agent_id
                    if scope in {ExtensionScope.AGENT, ExtensionScope.RUN}
                    else None
                ),
                run_id=run_id if scope == ExtensionScope.RUN else None,
            ),
            plan,
            parent=parent if scope != ExtensionScope.PROCESS else None,
        )
        return handle.providers.require(capability, name), handle

    def _materialized_plan(
        self,
        resolved,
        selected_agent: str,
        selected_handles,
        *,
        model,
        tool_catalog,
        tool_executor,
    ) -> ResolvedApplicationPlan:
        replaced_capabilities = {
            "agent.continuation-policy",
            "context.reducer",
            "context.summarizer",
            "context.token-estimator",
            "context.unit-compactor",
            "memory.recall-query",
            "tool.selection-policy",
            "workspace.initializer",
        }
        if model is not None:
            replaced_capabilities.add("model.provider")
        if tool_catalog is not None:
            replaced_capabilities.add("tool.catalog")
        if tool_executor is not None:
            replaced_capabilities.add("tool.executor")
        bindings = {
            (value.capability, value.name, value.scope): value
            for value in self.process_plan.providers
            if value.capability not in replaced_capabilities
        }
        dependencies = set(self.process_plan.dependencies)

        def visit(handle) -> None:
            for ancestor in getattr(handle, "_owned_ancestors", ()):
                visit(ancestor)
            dependencies.update(getattr(handle.graph, "dependencies", ()))
            for started in getattr(handle, "_started", ()):
                descriptor = started.registration.descriptor
                for offer in descriptor.provides:
                    bindings[
                        (offer.capability, offer.name, handle.context.scope.value)
                    ] = ResolvedProviderBinding(
                        capability=offer.capability,
                        name=offer.name,
                        api_version=offer.api_version,
                        plugin_id=descriptor.plugin_id,
                        scope=handle.context.scope.value,
                        source="plugin",
                    )

        for handle in selected_handles:
            visit(handle)
        if model is not None:
            bindings[("model.provider", "default", "agent")] = ResolvedProviderBinding(
                capability="model.provider",
                name="default",
                api_version="2",
                plugin_id=None,
                scope="agent",
                source="host",
            )
        injected_scope = (
            "run"
            if any(
                handle.context.scope == ExtensionScope.RUN
                for handle in selected_handles
            )
            else "agent"
        )
        for capability, provider in (
            ("tool.catalog", tool_catalog),
            ("tool.executor", tool_executor),
        ):
            if provider is not None:
                bindings[(capability, "default", injected_scope)] = (
                    ResolvedProviderBinding(
                        capability=capability,
                        name="default",
                        api_version="2",
                        plugin_id=None,
                        scope=injected_scope,
                        source="host",
                    )
                )
        providers = tuple(sorted(bindings.values()))
        payload = {
            "process": self.process_plan.composition_hash,
            "manifest": resolved.manifest_hash,
            "scope_compositions": sorted(
                {handle.composition_hash for handle in selected_handles}
            ),
            "host_ports": {
                capability: _service_composition_identity(provider)
                for capability, provider in (
                    ("model.provider", model),
                    ("tool.catalog", tool_catalog),
                    ("tool.executor", tool_executor),
                )
                if provider is not None
            },
            "providers": [
                (value.capability, value.plugin_id, value.scope, value.source)
                for value in providers
            ],
        }
        composition_hash = (
            "sha256:"
            + hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        )
        return ResolvedApplicationPlan(
            package_id=resolved.package_id,
            manifest_hash=resolved.manifest_hash,
            entrypoint_agent_id=selected_agent,
            providers=providers,
            dependencies=tuple(sorted(dependencies)),
            composition_hash=composition_hash,
        )


def _config_identity(value: Any) -> str:
    def normalize(candidate: Any, seen: set[int]) -> Any:
        if candidate is None or isinstance(candidate, (str, int, float, bool)):
            return candidate
        if isinstance(candidate, SecretStr):
            return {
                "secret_sha256": hashlib.sha256(
                    candidate.get_secret_value().encode()
                ).hexdigest()
            }
        marker = id(candidate)
        if marker in seen:
            return {"cycle": True}
        if isinstance(candidate, (bytes, bytearray)):
            return {"bytes_sha256": hashlib.sha256(bytes(candidate)).hexdigest()}
        if isinstance(candidate, Path):
            return str(candidate)
        if isinstance(candidate, Mapping):
            seen.add(marker)
            return {
                str(key): normalize(item, seen)
                for key, item in sorted(
                    candidate.items(), key=lambda pair: str(pair[0])
                )
            }
        if isinstance(candidate, (list, tuple)):
            seen.add(marker)
            return [normalize(item, seen) for item in candidate]
        return {
            "type": f"{type(candidate).__module__}.{type(candidate).__qualname__}",
            "id": marker,
        }

    return hashlib.sha256(
        json.dumps(normalize(value, set()), sort_keys=True).encode()
    ).hexdigest()


def _service_composition_identity(provider: Any) -> dict[str, Any]:
    identity = getattr(provider, "composition_identity", None)
    if callable(identity):
        identity = identity()
    if identity is None:
        root = getattr(provider, "root", None)
        identity = str(root) if root is not None else None
    return {
        "type": f"{type(provider).__module__}.{type(provider).__qualname__}",
        "identity": identity,
    }

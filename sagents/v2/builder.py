"""Public fluent configuration entry point for SAgents v2.

BuildOptions records injections; ApplicationAssembler owns construction.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from sagents.v2.agent.policy import (
    ApprovalMemory,
    DefaultToolPolicy,
)
from sagents.v2.application import (
    ApplicationResource,
    SAgentApplication,
)
from sagents.v2.composition.assembler import ApplicationAssembler
from sagents.v2.composition.options import BuildOptions
from sagents.v2.composition.inputs import RuntimeInput
from sagents.v2.memory import (
    MemoryProvider,
)
from sagents.v2.model import ModelProvider
from sagents.v2.package.manifest.resolver import ResolvedSageManifest
from sagents.v2.package.manifest.root import SageManifest
from sagents.v2.package.manifest.runtime import RuntimeConfig
from sagents.v2.runtime.execution import (
    ExecutionBindingProvider,
)
from sagents.v2.runtime.extensions import (
    ExtensionRegistration,
)
from sagents.v2.runtime.extensions.official import builtin_extension_registry
from sagents.v2.runtime.observability import (
    DiagnosticSink,
    LogSink,
)
from sagents.v2.runtime.session import (
    DerivedStateStore,
    SessionStore,
)
from sagents.v2.sagent import DriverFactory
from sagents.v2.session_memory import (
    SessionMemoryProvider,
)
from sagents.v2.tool import (
    ToolCatalog,
    ToolExecutor,
    ToolSelectionPolicy,
)
from sagents.v2.tool.official import OfficialToolRuntime


class SAgentBuilder:
    """Configure plugins and borrowed host ports, then build an owned Application."""

    def __init__(self) -> None:
        self.extensions = builtin_extension_registry()
        self._options = BuildOptions()

    def with_models(self, models=None, *, models_config_text=None):
        """Configure the App model catalog before build; App owns updates."""
        from sagents.v2.model.catalog import model_catalog_input
        self._models = model_catalog_input(models, config_text=models_config_text)
        return self

    def with_shared_runtime(self, application: SAgentApplication) -> "SAgentBuilder":
        """Borrow a process application's durable/runtime services for a Run.

        The original application retains ownership. Model routes, tools, policy
        and observability logging remain explicit host choices for this package.
        """
        return (
            self.with_session_store(application.runtime.session_store)
            .with_derived_state_store(application.service("derived-state.store"))
            .with_scheduler(application.service("execution.scheduler"))
            .with_job_runtime(application.service("execution.job-runtime"))
            .with_memory_provider(application.service("memory.provider"))
            .with_session_memory_provider(
                application.service("session-memory.provider")
            )
            .with_diagnostic_sink(application.service("observability.diagnostic-sink"))
        )

    def with_scheduler(self, scheduler) -> "SAgentBuilder":
        """Inject a host-owned scheduler with this Application's own work queue."""
        self._options.scheduler = scheduler
        return self

    def with_job_runtime(self, runtime) -> "SAgentBuilder":
        """Use a host-owned JobRuntime shared across Applications; host closes it."""
        self._options.job_runtime = runtime
        return self

    def with_admitted_run_contract(
        self, run_id: str, spec_hash: str
    ) -> "SAgentBuilder":
        """Bind one already-admitted Run to its owning application's contract.

        The Package plan retains its own identity. Only this Run uses the outer
        admission hash; child Runs inherit this execution contract.
        """
        self._options.admitted_run_contract = (run_id, spec_hash)
        self._options.defer_dispatcher_start = True
        return self

    def with_run_driver_factory(self, factory: DriverFactory) -> "SAgentBuilder":
        """Select the entrypoint Run driver before the Application is built."""
        self._options.run_driver_factory = factory
        return self

    def with_owned_resources(self, *resources: ApplicationResource) -> "SAgentBuilder":
        """Close a host-created resource after the Application's own resources.

        Resources are closed in registration order after the dispatcher.
        Ownership transfers when the Application is built successfully.
        """
        for resource in resources:
            if not any(value is resource for value in self._options.owned_resources):
                self._options.owned_resources.append(resource)
        return self

    def with_model_budget(self, budget) -> "SAgentBuilder":
        """Share a host-owned ModelConcurrencyBudget across Applications."""
        self._options.model_budget = budget
        return self

    def with_readiness_check(self) -> "SAgentBuilder":
        """Discover declared resources and attach a report without executing them."""
        self._options.check_readiness = True
        return self

    def with_skill_provider(self, catalog, source, workspace) -> "SAgentBuilder":
        """Bind standard Skill ports; preserve per-agent allowlists and lazy loading."""
        self._options.skill_provider = (catalog, source, workspace)
        return self

    def with_flow_tool_nodes(self, nodes) -> "SAgentBuilder":
        """Bind tool-named Flow nodes implementing the public RunnableNode protocol."""
        self._options.flow_tool_nodes = dict(nodes)
        return self

    def with_self_configuration(self, factory) -> "SAgentBuilder":
        """Enable one self-configure tool with a private host-authorized service.

        factory(agent_id) returns SelfConfigurationService. Requires explicit
        with_skill_provider ports, even when the Agent initially has no Skills.
        Services must not be shared between loops or Runs.
        """
        if not callable(factory):
            raise TypeError("self configuration factory must be callable")
        self._options.self_configuration_factory = factory
        return self

    def with_agent_management(self, service) -> "SAgentBuilder":
        """Expose full-package tools when explicitly granted in agent.tools.

        The host owns this shared service and closes it after its applications.
        Managed builders may inject the same service to permit further creation.
        """
        from sagents.v2.tool.plugins.agent_management import AgentManagementToolPlugin

        self._options.agent_management = AgentManagementToolPlugin(service)
        return self

    def with_defaults(self, *, session_root: str | Path) -> "SAgentBuilder":
        self._options.session_root = Path(session_root).expanduser().resolve()
        return self

    def register(self, registration: ExtensionRegistration) -> "SAgentBuilder":
        self.extensions.register(registration)
        return self

    def with_session_store(self, value: SessionStore) -> "SAgentBuilder":
        self._options.session_store = value
        return self

    def with_derived_state_store(self, value: DerivedStateStore) -> "SAgentBuilder":
        """Inject rebuildable state independently from authoritative Sessions."""

        self._options.derived_state_store = value
        return self

    def with_memory_provider(self, value: MemoryProvider) -> "SAgentBuilder":
        self._options.memory_provider = value
        return self

    def with_session_memory_provider(
        self, value: SessionMemoryProvider
    ) -> "SAgentBuilder":
        self._options.session_memory_provider = value
        return self

    def with_model_provider(self, value: ModelProvider) -> "SAgentBuilder":
        self._options.model_provider = value
        self._options.model_provider_factory = None
        return self

    def with_model_provider_factory(self, factory) -> "SAgentBuilder":
        """Supply a host provider for each resolved Agent's model bindings.

        The callable receives (resolved_package, agent_id). Providers remain
        host-owned, just like values passed to with_model_provider.
        """
        self._options.model_provider_factory = factory
        self._options.model_provider = None
        return self

    def with_model_client(self, value: Any) -> "SAgentBuilder":
        self._options.model_client = value
        return self

    def with_tool_provider(
        self, catalog: ToolCatalog, executor: ToolExecutor
    ) -> "SAgentBuilder":
        self._options.tool_catalog = catalog
        self._options.tool_executor = executor
        return self

    def with_additional_tools(self, catalog, executor) -> "SAgentBuilder":
        """Extend every run's catalog without replacing host-bound official tools.

        These Tools are granted as a catalog rather than per Agent: an external
        provider declares its own Tools at runtime, so an Agent's ``tools`` list
        could not name them even if the host wanted it to.
        """
        self._options.extra_tools.append((catalog, executor))
        return self

    def with_tool_runtime(self, runtime: OfficialToolRuntime) -> "SAgentBuilder":
        """Inject the V2-native runtime used by the official Tool plugin."""

        self._options.tool_runtime = runtime
        return self

    def with_execution_binding_provider(
        self, provider: ExecutionBindingProvider
    ) -> "SAgentBuilder":
        """Inject the Host port that allocates resources for actual Run IDs."""

        self._options.execution_binding_provider = provider
        return self

    def with_tool_selection(self, value: ToolSelectionPolicy) -> "SAgentBuilder":
        """Inject the model-visible Tool projection policy."""

        self._options.tool_selection = value
        return self

    def with_tool_policy(self, value: DefaultToolPolicy) -> "SAgentBuilder":
        """Inject the host-owned Tool approval policy used by every Loop.

        审批策略（何时向宿主请求确认）属于产品层决定，Kernel 只负责执行。
        未注入时沿用引擎默认的 ``DefaultToolPolicy()``；注入后 root 与
        子 Run 的 Loop 共用同一实例。它在 ``resolved_plan`` 里以 host 来源
        可见，但不参与 composition hash：审批模式是宿主的运行偏好，
        换一档不该让上个进程挂起的 Run 因 resolved_spec 不兼容而无法续跑。
        """

        self._options.tool_policy = value
        return self

    def with_approval_memory(self, value: ApprovalMemory) -> "SAgentBuilder":
        """Inject a host-owned approval memory (e.g. one that adds workspace scope).

        未注入时使用 ``SessionApprovalMemory``：记在 Session 的派生状态里，
        随 Session 删除而清理。宿主实现至少要支持 ``session`` 作用域。
        """

        self._options.approval_memory = value
        return self

    def with_approval_memory_layer(
        self, factory: Callable[[ApprovalMemory], ApprovalMemory]
    ) -> "SAgentBuilder":
        """Layer a host-owned approval memory over the kernel session memory.

        ``with_approval_memory`` 整个替换记忆实现，宿主就得自己重做 ``session``
        作用域；这里则把 Kernel 的 ``SessionApprovalMemory``（或已注入的记忆）交给
        ``factory``，宿主只叠加更宽的作用域（例如 ``workspace``），``session`` 仍由
        Kernel 记在会话派生状态里、随 Session 删除清理。``factory`` 在 ``build()``
        内调用一次。
        """

        self._options.approval_memory_layer = factory
        return self

    def with_log_sink(self, value: LogSink) -> "SAgentBuilder":
        """Inject a process log sink the host already owns."""

        self._options.log_sink = value
        return self

    def with_diagnostic_sink(self, value: DiagnosticSink) -> "SAgentBuilder":
        """Inject a process diagnostic sink the host already owns."""

        self._options.diagnostic_sink = value
        return self

    def inventory(self) -> tuple[dict, ...]:
        return self.extensions.inventory()

    async def _build_package(
        self,
        package: SageManifest | ResolvedSageManifest | str | Path,
        *,
        tenant_id: str | None = None,
        agent_id: str | None = None,
        runtime: RuntimeConfig | dict | None = None,
    ) -> SAgentApplication:
        """Resolve one composition and open all provider scopes asynchronously."""

        runtime = RuntimeConfig.model_validate(runtime) if runtime is not None else None
        from sagents.v2.composition.resolution import _resolve_package
        _, package = _resolve_package(package, runtime=runtime, models=getattr(self, "_models", None))
        scope_handles = []
        try:
            return await ApplicationAssembler(
                self._options, self.extensions,
                model_resolver=getattr(self, "_model_resolver", None),
            ).assemble(
                package,
                tenant_id=tenant_id,
                agent_id=agent_id,
                scope_handles=scope_handles,
                runtime=runtime,
            )
        except BaseException as exc:
            for handle in reversed(scope_handles):
                try:
                    await handle.close()
                except BaseException as close_exc:
                    exc.add_note(f"scope rollback also failed: {close_exc}")
            raise

    async def build(
        self,
        *,
        tenant_id: str | None = None,
        runtime: RuntimeInput | None = None,
        runtime_config_text: str | None = None,
        models=None,
        models_config_text: str | None = None,
    ) -> SAgentApplication:
        """Create an App, then load Agent Packages with app.load_agent().

        """
        from copy import copy, deepcopy
        from sagents.v2.composition.inputs import runtime_input
        from sagents.v2.composition.defaults import default_runtime
        from sagents.v2.composition.loaded_agents import LoadedAgents

        from sagents.v2.model.catalog import model_catalog_input
        models = model_catalog_input(
            models if models is not None or models_config_text is not None else getattr(self, "_models", None),
            config_text=models_config_text,
        )
        runtime = runtime_input(runtime, config_text=runtime_config_text)
        if runtime is None:
            runtime = default_runtime(self._options.session_root or ".runtime/sagents")
        snapshot = copy(self)
        snapshot._options = copy(self._options)
        snapshot.extensions = deepcopy(self.extensions)
        snapshot._options.owned_resources = []
        snapshot._options.extra_tools = list(self._options.extra_tools)
        snapshot._options.flow_tool_nodes = dict(self._options.flow_tool_nodes)
        application = SAgentApplication(
            agents={},
            entrypoint_agent_id=None,
            scope_handles=(),
            services={},
            adapters={},
            composition_hash="",
            owned_resources=tuple(reversed(self._options.owned_resources)),
        )
        application._loaded_agents = LoadedAgents(
            application, snapshot, runtime, tenant_id, models
        )
        return application

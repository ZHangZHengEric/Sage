"""Initialize App process scopes without creating a placeholder Agent or model."""
from types import SimpleNamespace
import hashlib

from sagents.v2.composition.assembler import ApplicationAssembler
from sagents.v2.composition.resolution import _selection
from sagents.v2.contracts.common import new_id
from sagents.v2.runtime import HarnessRuntime
from sagents.v2.runtime.credentials import EnvironmentCredentialProvider
from sagents.v2.runtime.execution import LocalWorkerDispatcher
from sagents.v2.runtime.execution.dispatcher import DEFAULT_LEASE_SECONDS
from sagents.v2.runtime.extensions import ExtensionHost, ExtensionScope, ExtensionScopeContext
from sagents.v2.runtime.session import AuthorizedSessionAccess, LeaseFencedSessionStore


async def initialize_process(catalog):
    app, builder, runtime = catalog.application, catalog.builder, catalog.runtime
    handles = []
    assembler = ApplicationAssembler(builder._state, builder._registry,
        model_resolver=catalog.model_resolver, scope_pool=catalog.scope_pool)
    assembler._runtime_config = runtime
    assembler._agent_configurations = {}
    assembler._application = app
    host = ExtensionHost(builder._registry, built_in_only=runtime.plugin_trust_policy == "built_in_only")
    root = await host.open_scope(ExtensionScopeContext(scope=ExtensionScope.PROCESS,
        scope_id=new_id("app")), host.plan(()))
    handles.append(root)
    app._retain_scope(root)
    async def open_capability(capability, plugin, *, locked=None, config=None):
        return await assembler._create_capability(host, root, handles, runtime, (),
            capability=capability, default_plugin=plugin, default_config=config,
            locked_config=locked, tenant_id=catalog.tenant_id)
    store = await assembler._create_session_store(host, root, handles, runtime, ())
    store_choice = _selection(runtime, "session.store")
    colocated = store_choice is None or builder._registry.is_trusted_builtin(store_choice.plugin)
    derived = await open_capability("derived-state.store",
        "sage.derived-state.session" if colocated else "sage.derived-state.ephemeral")
    credentials = await open_capability("credentials.provider", EnvironmentCredentialProvider.plugin_id,
                                       config={"declarations": catalog.models.credentials})
    services, adapters = await assembler._create_application_services(host, root, handles, runtime, (),
        SimpleNamespace(interfaces={}, model_routes={}, credentials={}),
        session_store=store, credential_provider=credentials)
    services.update({"session.store": store, "derived-state.store": derived,
                     "credentials.provider": credentials})
    services["memory.provider"] = await assembler._create_memory_provider(host, root, handles, runtime, ())
    services["session-memory.provider"] = await assembler._create_session_memory_provider(host, root, handles, runtime, ())
    # These capabilities require an Agent definition or the actual Run binding.
    agent_capabilities = {"tool.catalog", "tool.executor", "tool.selection-policy", "skill.catalog",
        "skill.workspace", "skill.loading", "flow.node", "context.reducer", "context.summarizer",
        "context.unit-compactor", "context.segment-provider", "agent.continuation-policy",
        "agent.self-configuration", "agent.output-checker", "memory.recall-query"}
    for capability in runtime.capabilities:
        if capability in services or capability in agent_capabilities or capability == "interface.protocol-adapter":
            continue
        for choice in runtime.selections(capability):
            if assembler._selection_scope(choice, ExtensionScope.PROCESS) != ExtensionScope.PROCESS:
                continue
            locked = {"derived_state": derived} if capability == "context.summary-store" else None
            services[capability] = await open_capability(capability, choice.plugin, locked=locked)
    binding = services.get("execution.binding")
    control = HarnessRuntime(store, job_runtime=services["execution.job-runtime"],
                             execution_binding_provider=binding, derived_state_store=derived)
    access = AuthorizedSessionAccess(store, runtime=control, derived_state=derived if derived is not store else None)
    scheduler = services["execution.scheduler"]
    capabilities = await scheduler.capabilities()
    if not capabilities.supports_fencing or not capabilities.supports_atomic_fenced_mutations:
        raise ValueError("execution.scheduler must support atomic fenced mutations")
    values = (_selection(runtime, "execution.scheduler").config
              if _selection(runtime, "execution.scheduler") is not None else {})
    dispatcher = LocalWorkerDispatcher(scheduler,
        max_concurrent_runs=int(values.get("max_concurrent_runs", 8)),
        max_concurrent_runs_per_tenant=int(values.get("max_concurrent_runs_per_tenant", 2)),
        lease_seconds=float(values.get("lease_seconds", DEFAULT_LEASE_SECONDS)),
        lease_scope_factory=LeaseFencedSessionStore(store, scheduler).lease_scope,
        preserve_runs_on_shutdown=bool(values.get("preserve_runs_on_shutdown", True)))
    services.update({"runtime.kernel": control, "session.access": access, "execution.dispatcher": dispatcher})
    app._services = services
    app._adapters = adapters
    app._owned_resources.append(dispatcher)
    catalog.process_handles = tuple(handles)
    catalog.process_dispatcher = dispatcher
    catalog.process_runtime = control
    catalog.process_assembler = assembler
    from sagents.v2.composition.loaded_agents import RevisionRecovery
    dispatcher.attach_recovery_agent(RevisionRecovery(catalog))
    app.composition_hash = assembler._composition_hash(
        "sha256:" + hashlib.sha256(runtime.model_dump_json().encode()).hexdigest(),
        handles, services, registry=builder._registry, runtime=runtime,
    )
    pending = tuple((choice.plugin, assembler._selection_scope(choice, ExtensionScope.AGENT))
        for capability in runtime.capabilities for choice in runtime.selections(capability)
        if not any(choice.plugin in handle.graph.plugin_ids for handle in handles))
    app.resolved_plan = assembler._resolved_application_plan(
        package_id="sage.application", manifest_hash=app.composition_hash,
        entrypoint_agent_id="", handles=handles, services=services,
        composition_hash=app.composition_hash, host_capabilities=frozenset(), deferred_plugins=pending,
    )

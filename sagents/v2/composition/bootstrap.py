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
    from sagents.v2.composition.model_providers import observed_model_registry
    assembler.extensions = observed_model_registry(builder._registry,
        with_budget=bool(runtime.selections("execution.model-budget")))
    host = ExtensionHost(assembler.extensions, built_in_only=runtime.plugin_trust_policy == "built_in_only")
    root = await host.open_scope(ExtensionScopeContext(scope=ExtensionScope.PROCESS,
        scope_id=new_id("app")), host.plan(()))
    handles.append(root)
    app._retain_scope(root)
    async def open_capability(capability, plugin, *, config=None):
        return await assembler._create_capability(host, root, handles, runtime, (),
            capability=capability, default_plugin=plugin, default_config=config,
            tenant_id=catalog.tenant_id)
    store = await assembler._create_session_store(host, root, handles, runtime, ())
    derived = await assembler._create_storage_capability(host, root, handles, runtime, (),
        capability="derived-state.store")
    credentials = await open_capability("credentials.provider", EnvironmentCredentialProvider.plugin_id,
                                       config={"declarations": {key: value.model_dump(mode="json") for key, value in catalog.models.credentials.items()}})
    services, adapters = await assembler._create_application_services(host, root, handles, runtime, (),
        SimpleNamespace(interfaces={}, model_routes={}, credentials={}))
    services.update({"session.store": store, "derived-state.store": derived,
                     "credentials.provider": credentials})
    services["memory.provider"] = await assembler._create_memory_provider(host, root, handles, runtime, ())
    services["session-memory.provider"] = await assembler._create_session_memory_provider(host, root, handles, runtime, ())
    # These capabilities require an Agent definition or the actual Run binding.
    agent_capabilities = {"tool.provider", "tool.selection-policy", "tool.result-processor", "skill.provider",
        "skill.workspace", "skill.loading", "flow.node", "context.reducer", "context.summarizer",
        "context.segment-provider", "agent.continuation-policy",
        "agent.self-configuration", "agent.output-checker", "memory.recall-query"}
    for capability in runtime.capabilities:
        if capability in services or capability in agent_capabilities or capability == "interface.protocol-adapter":
            continue
        for choice in runtime.selections(capability):
            if assembler._selection_scope(choice, ExtensionScope.PROCESS) != ExtensionScope.PROCESS:
                continue
            services[capability] = await open_capability(capability, choice.plugin)
    binding = services.get("execution.binding")
    control = HarnessRuntime(store, job_runtime=services["execution.job-runtime"],
                             execution_binding_provider=binding, derived_state_store=derived)
    access = AuthorizedSessionAccess(store, runtime=control, derived_state=derived if derived is not store else None)
    scheduler = services["execution.scheduler"]
    capabilities = await scheduler.capabilities()
    from sagents.v2.runtime.session.fencing import validate_distributed_pair
    validate_distributed_pair(store, scheduler, capabilities)
    await assembler._validate_required_guarantees(runtime, services=services, handles=handles,
        only_capabilities=frozenset(services))
    if not capabilities.supports_fencing or not capabilities.supports_atomic_fenced_mutations:
        raise ValueError("execution.scheduler must support atomic fenced mutations")
    values = (_selection(runtime, "execution.scheduler").config
              if _selection(runtime, "execution.scheduler") is not None else {})
    dispatcher = LocalWorkerDispatcher(scheduler,
        max_concurrent_runs=int(values.get("max_concurrent_runs", 8)),
        max_concurrent_runs_per_tenant=int(values.get("max_concurrent_runs_per_tenant", 2)),
        lease_seconds=float(values.get("lease_seconds", getattr(scheduler, "default_lease_seconds", DEFAULT_LEASE_SECONDS))),
        distributed_claims=capabilities.supports_distributed_claims,
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
    dispatcher.recovery_filter = lambda run: any(
        handle.composition_hash == run.resolved_spec_hash
        for handle in catalog.revisions.values()
    )
    app.composition_hash = assembler._composition_hash(
        "sha256:" + hashlib.sha256(runtime.model_dump_json().encode()).hexdigest(),
        handles, services, registry=assembler.extensions, runtime=runtime,
    )
    pending = tuple((choice.plugin, assembler._selection_scope(choice, ExtensionScope.AGENT))
        for capability in runtime.capabilities for choice in runtime.selections(capability)
        if not any(choice.plugin in handle.graph.plugin_ids for handle in handles))
    app.resolved_plan = assembler._resolved_application_plan(
        package_id="sage.application", manifest_hash=app.composition_hash,
        entrypoint_agent_id="", handles=handles, services=services,
        composition_hash=app.composition_hash, host_capabilities=frozenset(), deferred_plugins=pending,
    )

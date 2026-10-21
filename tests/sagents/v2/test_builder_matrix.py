from sagents.v2.runtime.observability.provider import ObservabilityProvider
from tests.sagents.v2.sdk_fixture import build_registered_package
from tests.sagents.v2.sdk_fixture import fixture_configuration
from tests.sagents.v2.model_fixture import TEST_MODELS
from sagents.v2.model.catalog import ModelCatalogConfig
from pathlib import Path
from types import SimpleNamespace

import pytest

from sagents.v2 import RunExecutionBinding, SAgentApplication, SAgentBuilder
from sagents.v2.composition.assembler import ApplicationAssembler
from sagents.v2.contracts.commands import InputItem, StartRun
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.run_state import RunState
from sagents.v2.model.contracts import (
    ModelEventKind,
    ModelResponse,
    ModelStreamEvent,
    ModelToolCall,
)
from sagents.v2.package.presets import BuiltinPackageFactory
from sagents.v2.package.manifest.root import PluginDeclaration
from sagents.v2.package.manifest.runtime import CapabilitySelection
from sagents.v2.package.manifest.runtime import RuntimeConfig
from sagents.v2.package.manifest.agents import AgentMemoryBehavior
from sagents.v2.memory import NoopMemoryProvider
from sagents.v2.session_memory import SessionMemoryCapabilities
from sagents.v2.runtime.extensions import (
    CapabilityOffer,
    ExtensionDescriptor,
    ExtensionRegistration,
    ExtensionScope,
)
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.agent.policy import (
    ApprovalStrategy,
    DefaultToolPolicy,
    SessionApprovalMemory,
)
from sagents.v2.contracts.commands import ReplyInteraction
from sagents.v2.runtime.execution.scheduler import InMemoryScheduler
from sagents.v2.runtime.observability import NoopDiagnosticSink, NoopLogSink
from sagents.v2.runtime.session import EphemeralSessionStore
from sagents.v2.runtime.session import InMemoryDerivedStateStore
from sagents.v2.runtime.execution.sandbox import (
    SandboxGrantIssuer,
)
from sagents.v2.testing.plugins.scripted_model import (
    ScriptedModelProvider,
    ScriptedModelStep,
)
from sagents.v2.tool.contracts import (
    SideEffectLevel,
    ToolDefinition,
    ToolExecutionResult,
)
from sagents.v2.tool.plugins.ephemeral import (
    InMemoryToolCatalog,
    InMemoryToolExecutor,
)


class _AuthoritativeOnlySessionStore:
    """Expose the authoritative port while deliberately hiding derived storage."""

    def __init__(self) -> None:
        self.store = EphemeralSessionStore()

    def __getattr__(self, name):
        if name in {
            "get_derived_state",
            "put_derived_state",
            "delete_derived_state",
            "forget_session",
        }:
            raise AttributeError(name)
        return getattr(self.store, name)


class _RecordingDerivedStateStore:
    def __init__(self) -> None:
        self.values = {}

    async def get_derived_state(self, session_id, namespace, key):
        return self.values.get((session_id, namespace, key))

    async def put_derived_state(self, session_id, namespace, key, value):
        self.values[(session_id, namespace, key)] = value

    async def delete_derived_state(self, session_id, namespace, key):
        self.values.pop((session_id, namespace, key), None)

    async def forget_session(self, session_id):
        self.values = {
            key: value for key, value in self.values.items() if key[0] != session_id
        }


class _RecordingSessionMemoryProvider:
    def __init__(self) -> None:
        self.forgotten = []

    async def capabilities(self):
        return SessionMemoryCapabilities(durable=False)

    async def sync(self, records):
        del records

    async def recall(self, query):
        del query
        return ()

    async def forget_session(self, session_id):
        self.forgotten.append(session_id)

    async def health(self):
        return {"ok": True}


@pytest.mark.asyncio
async def test_public_builder_is_the_composition_entrypoint(tmp_path: Path):
    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.builder",
    )
    application = await (
        build_registered_package(tmp_path / 'session-store', models=TEST_MODELS, model=ScriptedModelProvider(()), package=package)
    )

    assert isinstance(application, SAgentApplication)
    agent = application.entrypoint()
    assert agent.runtime.session_store.capabilities["global_session_index"] is False
    await application.close()


@pytest.mark.asyncio
async def test_builder_transfers_host_resources_in_close_order(tmp_path: Path):
    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.builder-owned-resources",
    )
    closed = []

    class Resource:
        def __init__(self, name):
            self.name = name

        async def close(self):
            closed.append(self.name)

    scheduler = Resource("scheduler")
    models = Resource("models")
    application = await (
        build_registered_package(tmp_path / 'session-store', models=TEST_MODELS, model=ScriptedModelProvider(()), package=package, resources=(scheduler, models,))
    )

    await application.close()
    assert closed == ["scheduler", "models"]


@pytest.mark.asyncio
async def test_builder_injects_derived_state_independently_from_session_store(
    tmp_path: Path,
):
    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.builder-derived-state",
    )
    session_store = _AuthoritativeOnlySessionStore()
    derived_state = _RecordingDerivedStateStore()

    application = await (
        build_registered_package(tmp_path / 'unused-session-store', models=TEST_MODELS, model=ScriptedModelProvider(()), package=package, providers={'session.store': session_store, 'derived-state.store': derived_state})
    )

    summary_store = application.service("context.summary-store")
    assert summary_store.derived_state is derived_state
    assert application.service("derived-state.store") is derived_state
    await application.close()


@pytest.mark.asyncio
async def test_builder_does_not_require_injected_session_store_to_hold_derived_state(
    tmp_path: Path,
):
    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.builder-default-derived-state",
    )

    application = await (
        build_registered_package(tmp_path / 'unused-session-store', models=TEST_MODELS, model=ScriptedModelProvider(()), package=package, providers={'session.store': _AuthoritativeOnlySessionStore()})
    )

    derived_state = application.service("derived-state.store")
    assert isinstance(derived_state, InMemoryDerivedStateStore)
    assert application.service("context.summary-store").derived_state is derived_state
    await application.close()


@pytest.mark.asyncio
async def test_builder_wires_session_deletion_to_session_memory_cleanup(tmp_path: Path):
    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.builder-session-memory-cleanup",
    )
    session_memory = _RecordingSessionMemoryProvider()
    application = await (
        build_registered_package(tmp_path / 'unused-session-store', models=TEST_MODELS, model=ScriptedModelProvider(()), package=package, providers={'session-memory.provider': session_memory})
    )
    store = application.entrypoint().runtime.session_store
    context = RequestContext(
        actor=ActorRef(
            principal_id="owner",
            principal_type=PrincipalType.USER,
            tenant_id="tenant",
        )
    )
    created = await store.create_run(
        StartRun(
            agent_id="agent",
            input=(InputItem(role="user", content=(TextBlock(text="hello"),)),),
            resolved_spec_hash="sha256:cleanup",
            idempotency_key="cleanup-start",
        ),
        context,
    )
    run = await store.get_run(created.handle.run_id)
    await store.commit_run(
        run_id=run.run_id,
        expected_revision=run.revision,
        expected_states={run.state},
        new_state=RunState.CANCELLED,
        drafts=(),
        context=context,
        idempotency_key="cleanup-cancel",
    )

    await application.service("session.access").delete_session(
        created.handle.session_id, context
    )

    assert session_memory.forgotten == [created.handle.session_id]
    await application.close()


@pytest.mark.asyncio
async def test_builder_fails_when_selected_provider_cannot_meet_required_guarantee(
    tmp_path: Path,
):
    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.builder-required-guarantees",
    )
    package = package.model_copy(
        update={
            "runtime": package.runtime.model_copy(
                update={
                    "required_guarantees": {
                        "execution.scheduler": {"durable_across_process_restart": True}
                    }
                }
            )
        }
    )

    with pytest.raises(SageV2Error) as unsatisfied:
        await (
            build_registered_package(tmp_path / 'session-store', models=TEST_MODELS, model=ScriptedModelProvider(()), package=package)
        )

    assert unsatisfied.value.info.code == "runtime.capability_guarantee_unsatisfied"
    assert unsatisfied.value.info.metadata["capability"] == "execution.scheduler"


@pytest.mark.asyncio
async def test_distributed_profile_automatically_rejects_single_host_plugins(
    tmp_path: Path,
):
    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.builder-distributed-profile",
    )
    package = package.model_copy(
        update={
            "runtime": package.runtime.model_copy(
                update={"deployment_profile": "distributed"}
            )
        }
    )

    with pytest.raises(SageV2Error) as unsatisfied:
        await (
            build_registered_package(tmp_path / 'session-store', models=TEST_MODELS, model=ScriptedModelProvider(()), package=package)
        )

    assert unsatisfied.value.info.code == "runtime.capability_guarantee_unsatisfied"
    assert unsatisfied.value.info.metadata["capability"] == "session.store"
    assert unsatisfied.value.info.metadata["deployment_profile"] == "distributed"
    assert unsatisfied.value.info.metadata["required"]["multi_process_writes"] is True


def test_distributed_profile_rejects_weaker_explicit_guarantee():
    runtime = RuntimeConfig(
        deployment_profile="distributed",
        required_guarantees={
            "session.store": {"multi_process_writes": False},
        },
    )

    with pytest.raises(SageV2Error) as conflict:
        ApplicationAssembler._effective_required_guarantees(runtime)

    assert conflict.value.info.code == "runtime.deployment_profile_conflict"
    assert conflict.value.info.metadata["capability"] == "session.store"

    effective = ApplicationAssembler._effective_required_guarantees(
        RuntimeConfig(deployment_profile="distributed")
    )
    assert effective["artifact.store"]["shared_across_processes"] is True
    assert effective["package.registry"]["supports_package_signatures"] is True
    assert effective["execution.job-runtime"]["supports_adoption"] is True
    assert effective["tool.provider"]["durable_operation_ledger"] is True
    assert effective["tool.provider"]["supports_restart_reconciliation"] is True
    # Workload isolation is a separate Host policy. It must not prevent a
    # server from using SAgents as an async conversation engine with its own
    # execution implementation (or no process tools at all).
    assert "execution.sandbox" not in effective


@pytest.mark.asyncio
async def test_builtin_only_policy_rejects_external_declaration_before_import(tmp_path):
    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.builder-builtin-only",
    )
    package = package.model_copy(
        update={
            "plugins": (PluginDeclaration(id="acme.untrusted"),),
            "runtime": package.runtime.model_copy(
                update={"plugin_trust_policy": "built_in_only"}
            ),
        }
    )

    with pytest.raises(SageV2Error) as rejected:
        await build_registered_package(tmp_path, models=TEST_MODELS, package=package)

    assert rejected.value.info.code == "extension.plugin_trust_policy_violation"
    assert rejected.value.info.metadata == {
        "plugin_id": "acme.untrusted",
        "plugin_trust_policy": "built_in_only",
    }


@pytest.mark.asyncio
async def test_runtime_update_cannot_weaken_application_security_profile(tmp_path):
    package = BuiltinPackageFactory.create("assistant", package_id="test.security")
    runtime = package.runtime.model_copy(update={"plugin_trust_policy": "built_in_only"})
    app = await SAgentBuilder().build(runtime=runtime, models=TEST_MODELS)
    try:
        for changes in ({"plugin_trust_policy": "trusted_declared"}, {"deployment_profile": "distributed"}):
            with pytest.raises(ValueError, match="security profile"):
                await app.update_runtime(app.runtime_configuration.model_copy(update=changes))
    finally:
        await app.close()



@pytest.mark.asyncio
async def test_builder_reads_mapping_capabilities_from_an_injected_provider(
    tmp_path: Path,
):
    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.builder-live-mapping-guarantees",
    )
    package = package.model_copy(
        update={
            "runtime": package.runtime.model_copy(
                update={
                    "required_guarantees": {
                        "session.store": {"durable_across_process_restart": False}
                    }
                }
            )
        }
    )
    application = await (
        build_registered_package(tmp_path / 'unused-store', models=TEST_MODELS, model=ScriptedModelProvider(()), package=package, providers={'session.store': EphemeralSessionStore()})
    )

    await application.close()


@pytest.mark.asyncio
async def test_live_capability_conflict_cannot_be_masked_by_descriptor(tmp_path: Path):
    class ContradictoryScheduler(InMemoryScheduler):
        async def capabilities(self):
            observed = await super().capabilities()
            return observed.model_copy(update={"supports_priority": False})

    registration = ExtensionRegistration(
        descriptor=ExtensionDescriptor(
            plugin_id="test.scheduler.contradictory",
            version="2.0.0",
            name="Contradictory Scheduler",
            provides=(
                CapabilityOffer(capability="execution.scheduler", api_version="2"),
            ),
            supported_scopes=frozenset({ExtensionScope.PROCESS}),
            capabilities={
                "supports_priority": True,
                "supports_atomic_tenant_quota": True,
            },
        ),
        factory=lambda context, dependencies: ContradictoryScheduler(),
    )
    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.builder-capability-conflict",
    )
    package = package.model_copy(
        update={
            "runtime": package.runtime.model_copy(
                update={
                    "capabilities": {
                        **package.runtime.capabilities,
                        "execution.scheduler": CapabilitySelection(
                            plugin="test.scheduler.contradictory"
                        ),
                    },
                    "required_guarantees": {
                        "execution.scheduler": {"supports_priority": True}
                    },
                }
            )
        }
    )

    with pytest.raises(SageV2Error) as conflict:
        await (
            build_registered_package(tmp_path / 'sessions', models=TEST_MODELS, model=ScriptedModelProvider(()), package=package, registrations=(registration,))
        )

    assert conflict.value.info.code == "runtime.capability_descriptor_conflict"
    assert conflict.value.info.metadata["declared"]
    assert conflict.value.info.metadata["observed"]["supports_priority"] is False


@pytest.mark.asyncio
async def test_application_composition_hash_includes_builder_storage_config(
    tmp_path: Path,
):
    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.builder-hash",
    )
    provider = ScriptedModelProvider(())
    first = await (
        build_registered_package(tmp_path / 'first', models=TEST_MODELS, model=provider, package=package)
    )
    first_hash = first.composition_hash
    await first.close()
    second = await (
        build_registered_package(tmp_path / 'second', models=TEST_MODELS, model=provider, package=package)
    )

    assert second.composition_hash != first_hash
    await second.close()


@pytest.mark.asyncio
async def test_standard_entrypoint_rejects_wrong_loaded_revision_identity(tmp_path):
    package = BuiltinPackageFactory.create("assistant", package_id="test.fenced")
    app = await build_registered_package(tmp_path, models=TEST_MODELS, model=ScriptedModelProvider(()), package=package)
    try:
        agent = app.loaded_agents[-1]
        with pytest.raises(ValueError, match="identity"):
            await app.entrypoint().run_stream(StartRun(agent_id=agent.id, input=(),
                resolved_spec_hash="sha256:wrong", idempotency_key="wrong"), _POLICY_USER, agent=agent)
    finally:
        await app.close()



@pytest.mark.asyncio
async def test_builtin_runtime_cannot_supply_sdk_service_objects(tmp_path):
    package = BuiltinPackageFactory.create("assistant", package_id="test.context-config")
    for capability, plugin, parameter in (
        ("context.summary-store", "sage.context.summary-store.session-derived", "derived_state"),
        ("context.summarizer", "sage.context.summarizer.model", "model"),
        ("context.reducer", "sage.context.reducer.persistent-summary", "summarizer"),
    ):
        runtime = package.runtime.model_copy(update={"capabilities": {
            capability: CapabilitySelection(plugin=plugin, config={parameter: "untrusted-value"})}})
        with pytest.raises(SageV2Error) as error:
            await build_registered_package(tmp_path / capability, models=TEST_MODELS, package=package, runtime=runtime)
        assert error.value.info.code == "extension.config_invalid"



@pytest.mark.parametrize(
    ("preset", "memory_enabled"),
    [("assistant", False), ("coder", True)],
)
@pytest.mark.asyncio
async def test_search_memory_assignment_controls_real_recall(tmp_path, preset, memory_enabled):
    from tests.sagents.v2.test_standard_execution_configuration import response, run
    class Memory(NoopMemoryProvider):
        def __init__(self):
            self.queries = []
        async def recall(self, query):
            self.queries.append(query)
            return ()
    memory = Memory()
    package = BuiltinPackageFactory.create(preset, package_id="test.memory." + preset)
    agent_id = package.entrypoint.agent
    definition = package.agents[agent_id].model_copy(update={"subagents": (),
        "memory": AgentMemoryBehavior(recall=True, auto_write=True, scope="agent")})
    package = package.model_copy(update={"agents": {agent_id: definition}})
    runtime = package.runtime.model_copy(update={"capabilities": {**package.runtime.capabilities,
        "tool.provider": CapabilitySelection(plugin="sage.tool.official"),
        "execution.binding": CapabilitySelection(plugin="sage.execution.binding.local-workspace", config={
            "workspace": str(tmp_path / "workspace"), "policy": {"process": {"enabled": False}}})}})
    app = await build_registered_package(tmp_path / "state", models=TEST_MODELS,
        model=ScriptedModelProvider((response(), response())), package=package, runtime=runtime,
        providers={"memory.provider": memory})
    try:
        result, events = await run(app, app.loaded_agents[-1], "recall")
        assert result.state.value == "completed", events
        assert bool(memory.queries) is memory_enabled
    finally:
        await app.close()



@pytest.mark.asyncio
async def test_registered_third_party_model_plugin_is_selected_by_model_route(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("SAGE_MODEL_API_KEY", "test-key")
    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.custom-model",
    )
    route = (
        ModelCatalogConfig.model_validate(TEST_MODELS)
        .models["primary"]
        .model_copy(update={"plugin": "acme.model.private-gateway"})
    )
    models = ModelCatalogConfig.model_validate(TEST_MODELS)
    models.models["primary"] = route
    provider = ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(
                    ModelStreamEvent(
                        kind=ModelEventKind.COMPLETED,
                        response=ModelResponse(
                            response_id="response_1",
                            text="done",
                            finish_reason="stop",
                        ),
                    ),
                )
            ),
        )
    )
    registration = ExtensionRegistration(
        descriptor=ExtensionDescriptor(
            plugin_id="acme.model.private-gateway",
            version="1.0.0",
            name="Private model gateway",
            provides=(
                CapabilityOffer(
                    capability="model.provider",
                    api_version="2",
                    name="private-gateway",
                ),
            ),
            supported_scopes=frozenset({ExtensionScope.AGENT}),
        ),
        factory=lambda context, dependencies: provider,
    )

    application = await (
        build_registered_package(tmp_path / 'session-store', models=models, package=package, registrations=(registration,))
    )

    from tests.sagents.v2.test_standard_execution_configuration import run
    try:
        result, events = await run(application, application.loaded_agents[-1], "custom-route")
        assert result.state.value == "completed", events
        assert provider.requests and provider.requests[0].run_id == result.run_id
    finally:
        await application.close()


@pytest.mark.asyncio
async def test_official_tools_are_selected_with_standard_execution_binding(tmp_path):
    package = BuiltinPackageFactory.create("assistant", package_id="test.official-tools")
    config = package.runtime.model_copy(update={"capabilities": {
        **package.runtime.capabilities,
        "tool.provider": CapabilitySelection(plugin="sage.tool.official"),
        "execution.binding": CapabilitySelection(plugin="sage.execution.binding.local-workspace", config={
            "workspace": str(tmp_path / "workspace"), "policy": {"process": {"enabled": False}},
        }),
    }})
    app = await build_registered_package(tmp_path / "state", models=TEST_MODELS,
        model=ScriptedModelProvider(()), package=package, runtime=config)
    try:
        plan = app.loaded_agents[-1].resolved_plan
        assert any(item.plugin_id == "sage.execution.binding.local-workspace" for item in plan.providers)
        assert any(item.plugin_id == "sage.tool.official" for item in plan.providers)
    finally:
        await app.close()



@pytest.mark.asyncio
async def test_registered_binding_receives_accepted_actual_run_and_releases_lease(tmp_path):
    from sagents.v2.runtime.execution.plugins.local_binding import LocalWorkspaceExecutionBindingProvider
    from tests.sagents.v2.test_standard_execution_configuration import response, run, CONTEXT
    class Binding(LocalWorkspaceExecutionBindingProvider):
        def __init__(self):
            super().__init__(tmp_path / "workspace", process_enabled=False)
            self.requests = []
        async def acquire(self, request):
            self.requests.append(request)
            return await super().acquire(request)
    binding = Binding()
    package = BuiltinPackageFactory.create("assistant", package_id="test.binding")
    runtime = package.runtime.model_copy(update={"capabilities": {
        "tool.provider": CapabilitySelection(plugin="sage.tool.official")}})
    model = ScriptedModelProvider((response(),))
    app = await build_registered_package(tmp_path / "state", models=TEST_MODELS, model=model,
        package=package, runtime=runtime, providers={"execution.binding": binding})
    try:
        result, events = await run(app, app.loaded_agents[-1], "binding")
        assert result.state.value == "completed", events
        assert binding.requests[0].run_id == result.run_id
        assert binding.requests[0].configuration == await app.execution_configuration(result.run_id, CONTEXT)
        assert binding.bindings[0].closed
        facts = await app.execution_diagnostics(result.run_id, CONTEXT)
        assert facts["sandbox"]["owner_run_id"] == result.run_id
        assert "<sandbox_environment>" in str(model.requests[0].messages)
        assert "XDG_CACHE_HOME" in str(model.requests[0].messages)
    finally:
        await app.close()
        await binding.close()



@pytest.mark.asyncio
async def test_standard_run_rejects_invalid_registered_binding_and_closes_it(tmp_path):
    from sagents.v2.runtime.execution.plugins.local_binding import LocalWorkspaceExecutionBindingProvider
    from tests.sagents.v2.test_standard_execution_configuration import response, run
    class InvalidBinding(LocalWorkspaceExecutionBindingProvider):
        async def acquire(self, request):
            binding = await super().acquire(request)
            binding.workspace_policy = "private_child"
            return binding
    binding = InvalidBinding(tmp_path / "workspace", process_enabled=False)
    package = BuiltinPackageFactory.create("assistant", package_id="test.binding.invalid")
    model = ScriptedModelProvider((response(),))
    app = await build_registered_package(tmp_path / "state", models=TEST_MODELS, model=model,
        package=package, providers={"execution.binding": binding})
    try:
        result, events = await run(app, app.loaded_agents[-1], "invalid-binding")
        assert result.state.value in {"failed", "suspended"}
        assert any("execution.workspace_policy_unsupported" in event.model_dump_json() for event in events)
        assert binding.bindings[0].closed
        assert model.requests == []
    finally:
        await app.close()
        await binding.close()



@pytest.mark.asyncio
async def test_execution_binding_invokes_failing_close_only_once():
    class FailingSandbox:
        def __init__(self):
            self.ref = SimpleNamespace(owner_run_id="run_1", tenant_id=None)
            self.calls = 0

        async def close(self):
            self.calls += 1
            raise RuntimeError("close failed")

    sandbox = FailingSandbox()
    binding = RunExecutionBinding(
        run_id="run_1",
        agent_id="agent_1",
        workspace_root="/workspace",
        workspace_policy="shared_parent",
        sandbox=sandbox,
        grant_issuer=SandboxGrantIssuer(),
    )

    for _ in range(2):
        with pytest.raises(RuntimeError, match="close failed"):
            await binding.close()
    assert sandbox.calls == 1


def _host_binding(plan, capability: str):
    return next(
        provider for provider in plan.providers if provider.capability == capability
    )


@pytest.mark.asyncio
async def test_builder_injects_host_log_and_diagnostic_sinks(tmp_path: Path):
    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.builder-host-sinks",
    )
    log_sink = NoopLogSink()
    diagnostic_sink = NoopDiagnosticSink()

    application = await (
        build_registered_package(tmp_path / 'session-store', models=TEST_MODELS, model=ScriptedModelProvider(()), package=package, providers={'observability.provider': ObservabilityProvider(plugin_id='test.observation', outputs=(log_sink,), diagnostics=diagnostic_sink)})
    )

    assert application.service("observability.provider").logs.outputs[0] is log_sink
    assert application.service("observability.provider").diagnostics is diagnostic_sink
    assert _host_binding(
        application.resolved_plan, "observability.provider"
    ).source == "plugin"
    assert (
        _host_binding(application.resolved_plan, "observability.provider").source
        == "plugin"
    )
    await application.close()


@pytest.mark.asyncio
async def test_builder_logs_resolved_application_registration(tmp_path: Path):
    class RecordingLogSink:
        format_version = "sage.log/v1"

        def __init__(self):
            self.records = []

        def write(self, record):
            self.records.append(record)

        def close(self):
            pass

    sink = RecordingLogSink()
    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.builder-registration",
    )
    application = await (
        build_registered_package(tmp_path / 'session-store', models=TEST_MODELS, model=ScriptedModelProvider(()), package=package, providers={'observability.provider': ObservabilityProvider(plugin_id='test.observation', outputs=(sink,))})
    )
    try:
        registration = next(
            record for record in sink.records if record.event == "sagents.registered"
        )
        assert (
            registration.attributes["package_id"]
            == application.resolved_plan.package_id
        )
        assert (
            registration.attributes["composition_hash"] == application.composition_hash
        )
        assert registration.attributes["plugins"]
    finally:
        await application.close()


@pytest.mark.asyncio
async def test_builder_keeps_plugin_sinks_when_host_does_not_inject(
    tmp_path: Path,
):
    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.builder-default-sinks",
    )

    application = await (
        build_registered_package(tmp_path / 'session-store', models=TEST_MODELS, model=ScriptedModelProvider(()), package=package)
    )

    assert not application.service("observability.provider").logs.outputs
    assert isinstance(
        application.service("observability.provider").diagnostics, NoopDiagnosticSink
    )
    assert _host_binding(
        application.resolved_plan, "observability.provider"
    ).source == ("plugin")
    assert (
        _host_binding(application.resolved_plan, "observability.provider").source
        == "plugin"
    )
    await application.close()


def _with_runtime_capabilities(package, **capabilities):
    current = dict(package.runtime.capabilities)
    current.update(
        {
            capability: CapabilitySelection(plugin=plugin_id)
            for capability, plugin_id in capabilities.items()
        }
    )
    return package.model_copy(
        update={"runtime": package.runtime.model_copy(update={"capabilities": current})}
    )


@pytest.mark.asyncio
async def test_updated_agent_uses_new_selection_with_one_app_dispatcher(tmp_path):
    from tests.sagents.v2.test_standard_execution_configuration import response, run, CONTEXT
    package = BuiltinPackageFactory.create("assistant", package_id="test.updated-context")
    app = await build_registered_package(tmp_path, models=TEST_MODELS,
        model=ScriptedModelProvider((response(), response())), package=package)
    try:
        original = app.loaded_agents[-1]
        dispatcher = app.service("execution.dispatcher")
        config = app.runtime_configuration
        await app.update_runtime(config.model_copy(update={"capabilities": {**config.capabilities,
            "context.reducer": CapabilitySelection(plugin="sage.context.reducer.window")}}))
        updated = await app.update_agent(agent=original, package=package)
        assert original.composition_hash != updated.composition_hash
        assert app.service("execution.dispatcher") is dispatcher
        result, events = await run(app, updated, "updated-context")
        assert result.state.value == "completed", events
        report = await app.run_configuration(result.run_id, CONTEXT)
        assert report["runtime"]["capabilities"]["context.reducer"]["plugin"] == "sage.context.reducer.window"
        assert any(item["plugin_id"] == "sage.context.reducer.window" for item in report["plugins"])
    finally:
        await app.close()











# ---------- with_tool_policy：宿主注入审批策略 ----------

_POLICY_USER = RequestContext(
    actor=ActorRef(principal_id="user_1", principal_type=PrincipalType.USER)
)
_POLICY_READ_TOOL = ToolDefinition(
    name="read_value",
    description="read a value",
    input_schema={
        "type": "object",
        "properties": {"key": {"type": "string"}},
        "required": ["key"],
        "additionalProperties": False,
    },
    side_effect_level=SideEffectLevel.READ,
)
_POLICY_WRITE_TOOL = ToolDefinition(
    name="write_value",
    description="write a value",
    input_schema={
        "type": "object",
        "properties": {"key": {"type": "string"}, "value": {"type": "string"}},
        "required": ["key", "value"],
        "additionalProperties": False,
    },
    side_effect_level=SideEffectLevel.WRITE,
    requires_approval=True,
)


def _policy_package(package_id: str):
    """assistant 预设换成两个内存工具，避免依赖官方工具沙箱。"""

    package = BuiltinPackageFactory.create(
        "assistant",
        package_id=package_id,
    )
    agent_id = package.entrypoint.agent
    definition = package.agents[agent_id].model_copy(
        update={"tools": (_POLICY_READ_TOOL.name, _POLICY_WRITE_TOOL.name)}
    )
    return package.model_copy(
        update={"agents": {**package.agents, agent_id: definition}}
    )


def _tool_calling_model(tool_name: str) -> ScriptedModelProvider:
    """第一步调用指定工具，拿到结果后第二步给出最终文本。"""

    arguments = (
        {"key": "answer"}
        if tool_name == _POLICY_READ_TOOL.name
        else {"key": "answer", "value": "1"}
    )
    return ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(
                    ModelStreamEvent(
                        kind=ModelEventKind.COMPLETED,
                        response=ModelResponse(
                            response_id="step_1",
                            text="",
                            tool_calls=(
                                ModelToolCall(
                                    tool_call_id="call_1",
                                    name=tool_name,
                                    arguments=arguments,
                                ),
                            ),
                            finish_reason="tool_calls",
                        ),
                    ),
                )
            ),
            ScriptedModelStep(
                events=(
                    ModelStreamEvent(
                        kind=ModelEventKind.COMPLETED,
                        response=ModelResponse(
                            response_id="step_2", text="done", finish_reason="stop"
                        ),
                    ),
                )
            ),
        )
    )


async def _policy_tool_handler(call, context):
    del context
    return ToolExecutionResult(
        tool_call_id=call.tool_call_id,
        operation_id=call.operation_id,
        content=(TextBlock(text="ok"),),
    )


async def _build_with_tool_policy(session_root: Path, package, policy, model):
    tools = (_POLICY_READ_TOOL, _POLICY_WRITE_TOOL)
    builder = (
        fixture_configuration(session_root, models=TEST_MODELS, model=model, tools=(InMemoryToolCatalog(tools), InMemoryToolExecutor({tool.name: tool for tool in tools}, {tool.name: _policy_tool_handler for tool in tools}),))
    )
    if policy is not None:
        from dataclasses import replace
        additional = fixture_configuration(session_root, providers={"agent.tool-policy": policy})
        builder = replace(builder, registrations=(*builder.registrations, *additional.registrations),
            runtime=builder.runtime.model_copy(update={"capabilities": {
                **builder.runtime.capabilities, "agent.tool-policy": additional.runtime.capabilities["agent.tool-policy"]}}))
    return await build_registered_package(configuration=builder, package=package)


async def _run_to_boundary(application: SAgentApplication, package, *, key: str):
    stream = await application.entrypoint().run_stream(
        (StartRun(
            agent_id=package.entrypoint.agent,
            input=(InputItem(role="user", content=(TextBlock(text="go"),)),),
            resolved_spec_hash=application.composition_hash,
            idempotency_key=key,
        )).model_copy(update={"agent_id": application.loaded_agents[-1].id, "resolved_spec_hash": application.loaded_agents[-1].composition_hash}),
        _POLICY_USER, agent=application.loaded_agents[-1],
    )
    event_types = [event.type async for event in stream.events]
    return event_types, await stream.wait()


@pytest.mark.parametrize(
    ("strategy", "tool_name", "expects_approval"),
    [
        # 未注入：沿用引擎默认 CONFIGURED，写工具必须审批。
        pytest.param(None, "write_value", True, id="default-write-asks"),
        pytest.param(
            ApprovalStrategy.AUTO_APPROVE, "write_value", False, id="auto-write-runs"
        ),
        pytest.param(
            ApprovalStrategy.CONFIGURED, "read_value", False, id="configured-read-runs"
        ),
        pytest.param(
            ApprovalStrategy.ALWAYS_ASK, "read_value", True, id="always-ask-read-asks"
        ),
    ],
)
@pytest.mark.asyncio
async def test_builder_applies_host_injected_tool_policy_to_the_loop(
    tmp_path: Path, strategy, tool_name: str, expects_approval: bool
):
    package = _policy_package("test.tool-policy")
    policy = (
        DefaultToolPolicy(approval_strategy=strategy) if strategy is not None else None
    )
    application = await _build_with_tool_policy(
        tmp_path / "session-store", package, policy, _tool_calling_model(tool_name)
    )
    try:
        event_types, result = await _run_to_boundary(
            application, package, key=f"policy-{tool_name}"
        )
    finally:
        await application.close()

    if expects_approval:
        assert "tool.call.awaiting_approval" in event_types
        assert "tool.call.succeeded" not in event_types
        assert result.state == RunState.SUSPENDED
    else:
        assert "tool.call.awaiting_approval" not in event_types
        assert "tool.call.succeeded" in event_types
        assert result.state == RunState.COMPLETED


@pytest.mark.asyncio
async def test_registered_tool_policy_is_part_of_frozen_composition_identity(tmp_path):
    package = _policy_package("test.policy-identity")
    identities = []
    for strategy in (ApprovalStrategy.AUTO_APPROVE, ApprovalStrategy.ALWAYS_ASK):
        runtime = package.runtime.model_copy(update={"capabilities": {**package.runtime.capabilities,
            "agent.tool-policy": CapabilitySelection(plugin="sage.agent.tool-policy.default",
                config={"approval_strategy": strategy.value})}})
        app = await build_registered_package(tmp_path, models=TEST_MODELS, model=ScriptedModelProvider(()),
            package=package, runtime=runtime)
        try:
            identities.append(app.loaded_agents[-1].composition_hash)
            binding = _host_binding(app.loaded_agents[-1].resolved_plan, "agent.tool-policy")
            assert binding.source == "plugin"
            assert binding.plugin_id == "sage.agent.tool-policy.default"
            assert app.service("agent.tool-policy").approval_strategy == strategy
        finally:
            await app.close()
    assert identities[0] != identities[1]


# ---------- 审批记忆接线 ----------


def _write_steps(*calls: tuple[str, dict]) -> ScriptedModelProvider:
    steps = [
        ScriptedModelStep(
            events=(
                ModelStreamEvent(
                    kind=ModelEventKind.COMPLETED,
                    response=ModelResponse(
                        response_id=call_id,
                        text="",
                        tool_calls=(
                            ModelToolCall(
                                tool_call_id=call_id,
                                name=_POLICY_WRITE_TOOL.name,
                                arguments=arguments,
                            ),
                        ),
                        finish_reason="tool_calls",
                    ),
                ),
            )
        )
        for call_id, arguments in calls
    ]
    steps.append(
        ScriptedModelStep(
            events=(
                ModelStreamEvent(
                    kind=ModelEventKind.COMPLETED,
                    response=ModelResponse(
                        response_id="final", text="done", finish_reason="stop"
                    ),
                ),
            )
        )
    )
    return ScriptedModelProvider(tuple(steps))


@pytest.mark.asyncio
async def test_builder_wires_registered_borrowed_approval_memory(tmp_path):
    package = _policy_package("test.approval-memory")
    host_memory = SessionApprovalMemory(InMemoryDerivedStateStore())
    app = await build_registered_package(tmp_path / "state", models=TEST_MODELS,
        model=ScriptedModelProvider(()), package=package,
        providers={"agent.approval-memory": host_memory})
    try:
        assert app.service("agent.approval-memory") is host_memory
        assert any(item.plugin_id == "test.fixture.agent.approval-memory" for item in app.loaded_agents[-1].resolved_plan.providers)
    finally:
        await app.close()



@pytest.mark.asyncio
async def test_registered_approval_memory_layer_receives_declared_store(tmp_path):
    from sagents.v2.runtime.extensions import ExtensionDependency
    class Layer:
        supported_scopes = frozenset({"session", "workspace"})
        def __init__(self, inner):
            self.inner = inner
        async def lookup(self, **kwargs):
            return await self.inner.lookup(**kwargs)
        async def remember(self, **kwargs):
            return await self.inner.remember(**kwargs)
        async def forget(self, **kwargs):
            return await self.inner.forget(**kwargs)
        async def list_remembered(self, **kwargs):
            return await self.inner.list_remembered(**kwargs)
    registration = ExtensionRegistration(
        descriptor=ExtensionDescriptor(plugin_id="test.approval.layer", name="Layer", version="1",
            provides=(CapabilityOffer(capability="agent.approval-memory", api_version="2"),),
            dependencies=(ExtensionDependency(capability="derived-state.store"),),
            supported_scopes=frozenset({ExtensionScope.PROCESS}),
            config_schema={"type": "object", "additionalProperties": False}),
        factory=lambda scope, deps: Layer(SessionApprovalMemory(deps.require("derived-state.store"))))
    package = _policy_package("test.approval-memory-layer")
    runtime = package.runtime.model_copy(update={"capabilities": {**package.runtime.capabilities,
        "agent.approval-memory": CapabilitySelection(plugin="test.approval.layer")}})
    app = await build_registered_package(tmp_path / "state", models=TEST_MODELS,
        model=ScriptedModelProvider(()), package=package, runtime=runtime, registrations=(registration,))
    try:
        memory = app.service("agent.approval-memory")
        assert isinstance(memory, Layer)
        assert isinstance(memory.inner, SessionApprovalMemory)
    finally:
        await app.close()



@pytest.mark.asyncio
async def test_builder_remembers_approvals_in_the_session_derived_state(
    tmp_path: Path,
):
    package = _policy_package("test.approval-memory-e2e")
    arguments = {"key": "answer", "value": "1"}
    application = await _build_with_tool_policy(
        tmp_path / "session-store",
        package,
        DefaultToolPolicy(allow_persistent_approval=True),
        _write_steps(("call_1", arguments), ("call_2", arguments)),
    )
    try:
        agent = application.entrypoint()
        store = agent.runtime.session_store
        event_types, suspended = await _run_to_boundary(
            application, package, key="remember-e2e"
        )
        assert suspended.state == RunState.SUSPENDED
        assert event_types.count("tool.call.awaiting_approval") == 1
        suspension = await store.get_suspension(suspended.suspension_id)
        interaction = await store.get_interaction(suspension.interaction_id)
        assert "approve_and_remember" in interaction.allowed_decisions

        await agent.runtime.reply_interaction(
            ReplyInteraction(
                run_id=suspended.run_id,
                suspension_id=suspension.suspension_id,
                interaction_id=interaction.interaction_id,
                expected_revision=suspended.revision,
                expected_suspension_revision=suspension.expected_revision,
                expected_interaction_revision=interaction.expected_revision,
                decision="approve_and_remember",
                idempotency_key="remember-e2e-reply",
            ),
            _POLICY_USER,
        )
        final = await (await agent.continue_run(suspended.run_id, _POLICY_USER, agent=application.loaded_agents[-1]))

        assert final.state == RunState.COMPLETED
        types = [event.type for event in await store.read_events(suspended.run_id)]
        assert types.count("tool.call.awaiting_approval") == 1
        assert types.count("tool.call.succeeded") == 2
        assert types.count("policy.approval.remembered") == 1
        memory = application.services["agent.approval-memory"]
        remembered = await memory.list_remembered(session_id=final.session_id)
        assert [value.matcher.tool_name for value in remembered] == ["write_value"]
        # 记忆真的落在 Session 存储的派生状态里，重开进程后同一 Session 仍可复用。
        raw = await store.get_derived_state(
            final.session_id,
            SessionApprovalMemory.NAMESPACE,
            SessionApprovalMemory.KEY,
        )
        assert raw["version"] == 1
        assert list(raw["entries"]) == [remembered[0].matcher.key]
    finally:
        await application.close()











# Scope reuse, concurrent tenant/Agent isolation, failed Run rollback and actual
# Skill/configuration behavior are covered through public standard execution in
# test_standard_capability_scopes.py; the removed materializer is not reintroduced.

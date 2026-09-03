from pathlib import Path
import hashlib
from types import SimpleNamespace

import pytest

from sagents.v2 import RunExecutionBinding, SAgentApplication, SAgentBuilder
from sagents.v2.builder import _ExecutionBoundDriver
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
    ExplicitStatusContinuationPolicy,
)
from sagents.v2.context import (
    ModelConversationSummarizer,
    PersistentSummaryContextReducer,
    ReferenceContextUnitCompactor,
    SessionDerivedConversationSummaryStore,
    UnicodeHeuristicTokenEstimator,
    WindowContextReducer,
)
from sagents.v2.runtime.execution import ExecutionBindingRequest
from sagents.v2.runtime.execution.scheduler import InMemoryScheduler
from sagents.v2.runtime.observability import NoopDiagnosticSink, NoopLogSink
from sagents.v2.runtime.session import EphemeralSessionStore
from sagents.v2.runtime.session import InMemoryDerivedStateStore
from sagents.v2.runtime.execution.sandbox import (
    FileOperation,
    FileSystemPolicy,
    LocalWorkspaceSandboxProvider,
    NetworkPolicy,
    ProcessPolicy,
    ResolvedSandboxSpec,
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
from sagents.v2.tool.official import OfficialToolRuntime
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
        model="test-model",
        base_url="https://model.invalid/v1",
    )
    application = await (
        SAgentBuilder()
        .with_defaults(session_root=tmp_path / "session-store")
        .with_model_provider(ScriptedModelProvider(()))
        .build(package)
    )

    assert isinstance(application, SAgentApplication)
    agent = application.entrypoint()
    assert agent.runtime.session_store.capabilities["global_session_index"] is False
    await application.close()


@pytest.mark.asyncio
async def test_builder_injects_derived_state_independently_from_session_store(
    tmp_path: Path,
):
    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.builder-derived-state",
        model="test-model",
        base_url="https://model.invalid/v1",
    )
    session_store = _AuthoritativeOnlySessionStore()
    derived_state = _RecordingDerivedStateStore()

    application = await (
        SAgentBuilder()
        .with_defaults(session_root=tmp_path / "unused-session-store")
        .with_session_store(session_store)
        .with_derived_state_store(derived_state)
        .with_model_provider(ScriptedModelProvider(()))
        .build(package)
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
        model="test-model",
        base_url="https://model.invalid/v1",
    )

    application = await (
        SAgentBuilder()
        .with_defaults(session_root=tmp_path / "unused-session-store")
        .with_session_store(_AuthoritativeOnlySessionStore())
        .with_model_provider(ScriptedModelProvider(()))
        .build(package)
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
        model="test-model",
        base_url="https://model.invalid/v1",
    )
    session_memory = _RecordingSessionMemoryProvider()
    application = await (
        SAgentBuilder()
        .with_defaults(session_root=tmp_path / "unused-session-store")
        .with_session_memory_provider(session_memory)
        .with_model_provider(ScriptedModelProvider(()))
        .build(package)
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
        model="test-model",
        base_url="https://model.invalid/v1",
    )
    package = package.model_copy(
        update={
            "runtime": package.runtime.model_copy(
                update={
                    "required_guarantees": {
                        "execution.scheduler": {
                            "durable_across_process_restart": True
                        }
                    }
                }
            )
        }
    )

    with pytest.raises(SageV2Error) as unsatisfied:
        await (
            SAgentBuilder()
            .with_defaults(session_root=tmp_path / "session-store")
            .with_model_provider(ScriptedModelProvider(()))
            .build(package)
        )

    assert (
        unsatisfied.value.info.code
        == "runtime.capability_guarantee_unsatisfied"
    )
    assert unsatisfied.value.info.metadata["capability"] == "execution.scheduler"


@pytest.mark.asyncio
async def test_distributed_profile_automatically_rejects_single_host_plugins(
    tmp_path: Path,
):
    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.builder-distributed-profile",
        model="test-model",
        base_url="https://model.invalid/v1",
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
            SAgentBuilder()
            .with_defaults(session_root=tmp_path / "session-store")
            .with_model_provider(ScriptedModelProvider(()))
            .build(package)
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
        SAgentBuilder._effective_required_guarantees(runtime)

    assert conflict.value.info.code == "runtime.deployment_profile_conflict"
    assert conflict.value.info.metadata["capability"] == "session.store"

    effective = SAgentBuilder._effective_required_guarantees(
        RuntimeConfig(deployment_profile="distributed")
    )
    assert effective["artifact.store"]["shared_across_processes"] is True
    assert effective["package.registry"]["supports_package_signatures"] is True
    assert effective["execution.job-runtime"]["supports_adoption"] is True
    assert effective["tool.executor"]["durable_operation_ledger"] is True
    assert effective["tool.executor"]["supports_restart_reconciliation"] is True
    # Workload isolation is a separate Host policy. It must not prevent a
    # server from using SAgents as an async conversation engine with its own
    # execution implementation (or no process tools at all).
    assert "execution.sandbox" not in effective


@pytest.mark.asyncio
async def test_builtin_only_policy_rejects_external_declaration_before_import():
    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.builder-builtin-only",
        model="test-model",
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
        await SAgentBuilder().build(package)

    assert rejected.value.info.code == "extension.plugin_trust_policy_violation"
    assert rejected.value.info.metadata == {
        "plugin_id": "acme.untrusted",
        "plugin_trust_policy": "built_in_only",
    }


@pytest.mark.asyncio
async def test_materialization_cannot_weaken_application_trust_or_change_profile(
    tmp_path: Path,
):
    root = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.builder-materialize-policy-root",
        model="test-model",
    )
    root = root.model_copy(
        update={
            "runtime": root.runtime.model_copy(
                update={"plugin_trust_policy": "built_in_only"}
            )
        }
    )
    application = await (
        SAgentBuilder()
        .with_defaults(session_root=tmp_path / "sessions")
        .with_model_provider(ScriptedModelProvider(()))
        .build(root)
    )
    external = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.builder-materialize-policy-external",
        model="test-model",
    ).model_copy(update={"plugins": (PluginDeclaration(id="acme.untrusted"),)})
    distributed = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.builder-materialize-policy-distributed",
        model="test-model",
    )
    distributed = distributed.model_copy(
        update={
            "runtime": distributed.runtime.model_copy(
                update={"deployment_profile": "distributed"}
            )
        }
    )

    try:
        with pytest.raises(SageV2Error) as trust:
            await application.materialize_agent(external)
        with pytest.raises(SageV2Error) as profile:
            await application.materialize_agent(distributed)
    finally:
        await application.close()

    assert trust.value.info.code == "extension.plugin_trust_policy_violation"
    assert profile.value.info.code == "runtime.deployment_profile_mismatch"


@pytest.mark.asyncio
async def test_builder_reads_mapping_capabilities_from_an_injected_provider(
    tmp_path: Path,
):
    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.builder-live-mapping-guarantees",
        model="test-model",
        base_url="https://model.invalid/v1",
    )
    package = package.model_copy(
        update={
            "runtime": package.runtime.model_copy(
                update={
                    "required_guarantees": {
                        "session.store": {
                            "durable_across_process_restart": False
                        }
                    }
                }
            )
        }
    )
    application = await (
        SAgentBuilder()
        .with_defaults(session_root=tmp_path / "unused-store")
        .with_session_store(EphemeralSessionStore())
        .with_model_provider(ScriptedModelProvider(()))
        .build(package)
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
        model="test-model",
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
            SAgentBuilder()
            .with_defaults(session_root=tmp_path / "sessions")
            .register(registration)
            .with_model_provider(ScriptedModelProvider(()))
            .build(package)
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
        model="test-model",
        base_url="https://model.invalid/v1",
    )
    provider = ScriptedModelProvider(())
    first = await (
        SAgentBuilder()
        .with_defaults(session_root=tmp_path / "first")
        .with_model_provider(provider)
        .build(package)
    )
    first_hash = first.composition_hash
    await first.close()
    second = await (
        SAgentBuilder()
        .with_defaults(session_root=tmp_path / "second")
        .with_model_provider(provider)
        .build(package)
    )

    assert second.composition_hash != first_hash
    await second.close()


@pytest.mark.asyncio
async def test_builder_loop_fences_on_the_full_application_composition_hash(
    tmp_path: Path,
):
    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.builder-loop-composition-hash",
        model="test-model",
        base_url="https://model.invalid/v1",
    )
    application = await (
        SAgentBuilder()
        .with_defaults(session_root=tmp_path / "session-store")
        .with_model_provider(ScriptedModelProvider(()))
        .build(package)
    )

    loop = application.entrypoint().driver_factory("run_1")
    assert loop.expected_resolved_spec_hash == application.composition_hash
    await application.close()


@pytest.mark.asyncio
async def test_builder_composes_selected_context_and_continuation_plugins(
    tmp_path: Path,
):
    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.selected-components",
        model="test-model",
        base_url="https://model.invalid/v1",
    )
    capabilities = {
        **package.runtime.capabilities,
        "context.token-estimator": CapabilitySelection(
            plugin="sage.context.token-estimator.unicode-heuristic"
        ),
        "context.summary-store": CapabilitySelection(
            plugin="sage.context.summary-store.session-derived",
            config={"derived_state": "untrusted-manifest-value"},
        ),
        "context.summarizer": CapabilitySelection(
            plugin="sage.context.summarizer.model",
            config={"model": "untrusted-manifest-value"},
        ),
        "context.reducer": CapabilitySelection(
            plugin="sage.context.reducer.persistent-summary",
            config={
                "estimator": "untrusted-manifest-value",
                "store": "untrusted-manifest-value",
                "summarizer": "untrusted-manifest-value",
            },
        ),
        "agent.continuation-policy": CapabilitySelection(
            plugin="sage.agent.continuation.explicit-status"
        ),
    }
    route = package.models["primary"]
    route = route.model_copy(
        update={
            "limits": route.limits.model_copy(update={"context_window": 32_000})
        }
    )
    package = package.model_copy(
        update={
            "models": {**package.models, "primary": route},
            "runtime": package.runtime.model_copy(
                update={"capabilities": capabilities}
            )
        }
    )
    application = await (
        SAgentBuilder()
        .with_defaults(session_root=tmp_path / "session-store")
        .with_model_provider(ScriptedModelProvider(()))
        .build(package)
    )

    loop = application.entrypoint().driver_factory("run_1")
    reducer = loop.context_assembler.reducer
    continuation = loop.continuation_policy.base.base

    assert isinstance(
        loop.context_assembler.estimator, UnicodeHeuristicTokenEstimator
    )
    assert isinstance(reducer, PersistentSummaryContextReducer)
    assert reducer.estimator is loop.context_assembler.estimator
    assert isinstance(reducer.unit_compactor, ReferenceContextUnitCompactor)
    assert reducer.unit_compactor.estimator is loop.context_assembler.estimator
    assert isinstance(reducer.store, SessionDerivedConversationSummaryStore)
    assert reducer.store.derived_state is application.service("derived-state.store")
    assert isinstance(reducer.summarizer, ModelConversationSummarizer)
    assert reducer.summarizer.model is loop.model
    assert isinstance(continuation, ExplicitStatusContinuationPolicy)
    await application.close()


@pytest.mark.parametrize(
    ("preset", "memory_enabled"),
    [("assistant", False), ("coder", True)],
)
@pytest.mark.asyncio
async def test_search_memory_assignment_controls_recall_and_auto_write(
    tmp_path: Path, preset: str, memory_enabled: bool
):
    package = BuiltinPackageFactory.create(
        preset,
        package_id=f"test.memory-gate.{preset}",
        model="test-model",
        base_url="https://model.invalid/v1",
    )
    agent_id = package.entrypoint.agent
    assert agent_id is not None
    definition = package.agents[agent_id].model_copy(
        update={
            "memory": AgentMemoryBehavior(
                recall=True,
                auto_write=True,
                scope="agent",
            )
        }
    )
    package = package.model_copy(
        update={"agents": {**package.agents, agent_id: definition}}
    )
    application = await (
        SAgentBuilder()
        .with_defaults(session_root=tmp_path / preset / "session-store")
        .with_memory_provider(NoopMemoryProvider())
        .with_model_provider(ScriptedModelProvider(()))
        .build(package)
    )
    agent = application.entrypoint()
    loop = agent.driver_factory("run_1")

    assert loop.automatic_memory_recall is memory_enabled
    assert all(
        value.__class__.__name__ != "MemoryContextSource"
        for value in loop.context_assembler.providers
    )
    assert (agent.memory_service is not None) is memory_enabled
    assert agent.memory_scope["recall"] is memory_enabled
    assert agent.memory_scope["auto_write"] is memory_enabled
    await application.close()


@pytest.mark.asyncio
async def test_registered_third_party_model_plugin_is_selected_by_model_route(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("SAGE_MODEL_API_KEY", "test-key")
    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.custom-model",
        model="test-model",
        base_url="https://model.invalid/v1",
    )
    route = package.models["primary"].model_copy(
        update={"plugin": "acme.model.private-gateway"}
    )
    package = package.model_copy(update={"models": {"primary": route}})
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
        SAgentBuilder()
        .with_defaults(session_root=tmp_path / "session-store")
        .register(registration)
        .build(package)
    )

    model = application.entrypoint().driver_factory("run_1").model
    assert model.provider is provider
    await application.close()


@pytest.mark.asyncio
async def test_official_tools_are_explicit_and_never_auto_discovered(tmp_path: Path):
    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.official-tools",
        model="test-model",
        base_url="https://model.invalid/v1",
    )
    package = package.model_copy(
        update={
            "runtime": package.runtime.model_copy(
                update={
                    "capabilities": {
                        "tool.catalog": CapabilitySelection(
                            plugin="sage.tool.official", name="official"
                        )
                    }
                }
            )
        }
    )

    builder = (
        SAgentBuilder()
        .with_defaults(session_root=tmp_path / "session-store")
        .with_model_provider(ScriptedModelProvider(()))
    )
    with pytest.raises(ValueError, match="with_tool_runtime"):
        await builder.build(package)

    issuer = SandboxGrantIssuer()
    provider = LocalWorkspaceSandboxProvider(issuer.verification_key)
    digest = hashlib.sha256(str(tmp_path).encode()).hexdigest()
    handle = await provider.provision(
        ResolvedSandboxSpec(
            spec_hash=f"sha256:{digest}",
            architecture="native",
            filesystem=FileSystemPolicy(allowed_operations=frozenset(FileOperation)),
            process=ProcessPolicy(enabled=False),
            network=NetworkPolicy(),
            policy_hash=f"sha256:{digest}",
            metadata={"host_workspace": str(tmp_path)},
        ),
        RequestContext(
            actor=ActorRef(principal_id="user_1", principal_type=PrincipalType.USER)
        ),
        run_id="run_1",
    )
    application = await builder.with_tool_runtime(
        OfficialToolRuntime(handle, issuer)
    ).build(package)
    assert isinstance(application, SAgentApplication)
    await application.close()


@pytest.mark.asyncio
async def test_execution_binding_provider_receives_actual_run_and_closes_once(
    tmp_path: Path,
):
    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.run-binding",
        model="test-model",
        base_url="https://model.invalid/v1",
    )
    package = package.model_copy(
        update={
            "runtime": package.runtime.model_copy(
                update={
                    "capabilities": {
                        "tool.catalog": CapabilitySelection(
                            plugin="sage.tool.official", name="official"
                        )
                    }
                }
            )
        }
    )

    class BindingProvider:
        def __init__(self):
            self.requests = []
            self.bindings = []

        async def acquire(self, request):
            self.requests.append(request)
            issuer = SandboxGrantIssuer()
            sandbox_provider = LocalWorkspaceSandboxProvider(issuer.verification_key)
            digest = hashlib.sha256(request.run_id.encode()).hexdigest()
            handle = await sandbox_provider.provision(
                ResolvedSandboxSpec(
                    spec_hash=f"sha256:{digest}",
                    architecture="native",
                    filesystem=FileSystemPolicy(
                        allowed_operations=frozenset(FileOperation)
                    ),
                    process=ProcessPolicy(enabled=False),
                    network=NetworkPolicy(),
                    policy_hash=f"sha256:{digest}",
                    metadata={"host_workspace": str(tmp_path)},
                ),
                request.context,
                run_id=request.run_id,
            )
            binding = RunExecutionBinding(
                run_id=request.run_id,
                parent_run_id=request.parent_run_id,
                agent_id=request.agent_id,
                workspace_root=str(tmp_path),
                workspace_policy=request.workspace_policy,
                sandbox=handle,
                grant_issuer=issuer,
            )
            self.bindings.append(binding)
            return binding

        async def close(self):
            return None

    bindings = BindingProvider()
    model = ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(
                    ModelStreamEvent(
                        kind=ModelEventKind.COMPLETED,
                        response=ModelResponse(
                            response_id="done",
                            text="done",
                            finish_reason="stop",
                        ),
                    ),
                )
            ),
        )
    )
    application = await (
        SAgentBuilder()
        .with_defaults(session_root=tmp_path / "session-store")
        .with_model_provider(model)
        .with_execution_binding_provider(bindings)
        .build(package)
    )
    deferred = {
        (value.capability, value.plugin_id, value.scope, value.source)
        for value in application.resolved_plan.providers
        if value.source == "plugin-deferred"
    }
    assert (
        "tool.catalog",
        "sage.tool.official",
        "run",
        "plugin-deferred",
    ) in deferred
    assert (
        "tool.executor",
        "sage.tool.official",
        "run",
        "plugin-deferred",
    ) in deferred
    agent = application.entrypoint()
    agent_id = package.entrypoint.agent
    stream = await agent.run_stream(
        StartRun(
            agent_id=agent_id,
            input=(InputItem(role="user", content=(TextBlock(text="hello"),)),),
            resolved_spec_hash="sha256:test",
            idempotency_key="binding-run",
        ),
        RequestContext(
            actor=ActorRef(principal_id="user_1", principal_type=PrincipalType.USER)
        ),
    )
    result = await stream.wait()

    assert bindings.requests[0].run_id == result.run_id
    assert bindings.bindings[0].sandbox.ref.owner_run_id == result.run_id
    assert bindings.bindings[0].closed is True
    await application.close()


@pytest.mark.asyncio
async def test_execution_bound_driver_rejects_mismatched_policy_and_closes(
    tmp_path: Path,
):
    context = RequestContext(
        actor=ActorRef(principal_id="user_1", principal_type=PrincipalType.USER)
    )
    issuer = SandboxGrantIssuer()
    sandbox_provider = LocalWorkspaceSandboxProvider(issuer.verification_key)
    handle = await sandbox_provider.provision(
        ResolvedSandboxSpec(
            spec_hash="sha256:mismatch",
            architecture="native",
            filesystem=FileSystemPolicy(allowed_operations=frozenset(FileOperation)),
            process=ProcessPolicy(enabled=False),
            network=NetworkPolicy(),
            policy_hash="sha256:mismatch",
            metadata={"host_workspace": str(tmp_path)},
        ),
        context,
        run_id="run_mismatch",
    )
    binding = RunExecutionBinding(
        run_id="run_mismatch",
        parent_run_id=None,
        agent_id="agent_1",
        workspace_root=str(tmp_path),
        workspace_policy="private_child",
        sandbox=handle,
        grant_issuer=issuer,
    )

    class Provider:
        async def acquire(self, request: ExecutionBindingRequest):
            return binding

    class Store:
        async def get_start_command(self, run_id):
            return SimpleNamespace(
                parent_run_id=None,
                config=SimpleNamespace(metadata={"workspace_policy": "shared_parent"}),
            )

    driver = _ExecutionBoundDriver(
        runtime=SimpleNamespace(session_store=Store()),
        provider=Provider(),
        run_id="run_mismatch",
        agent_id="agent_1",
        loop_builder=lambda _binding: pytest.fail("loop must not be composed"),
    )
    with pytest.raises(SageV2Error) as mismatch:
        await driver._ensure_loop(context)
    assert mismatch.value.info.code == "execution.workspace_policy_unsupported"
    assert binding.closed is True


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
        provider
        for provider in plan.providers
        if provider.capability == capability
    )


@pytest.mark.asyncio
async def test_builder_injects_host_log_and_diagnostic_sinks(tmp_path: Path):
    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.builder-host-sinks",
        model="test-model",
        base_url="https://model.invalid/v1",
    )
    log_sink = NoopLogSink()
    diagnostic_sink = NoopDiagnosticSink()

    application = await (
        SAgentBuilder()
        .with_defaults(session_root=tmp_path / "session-store")
        .with_model_provider(ScriptedModelProvider(()))
        .with_log_sink(log_sink)
        .with_diagnostic_sink(diagnostic_sink)
        .build(package)
    )

    assert application.service("observability.log-sink") is log_sink
    assert application.service("observability.diagnostic-sink") is diagnostic_sink
    assert _host_binding(application.resolved_plan, "observability.log-sink").source == (
        "host"
    )
    assert _host_binding(
        application.resolved_plan, "observability.diagnostic-sink"
    ).source == "host"
    await application.close()


@pytest.mark.asyncio
async def test_builder_keeps_plugin_sinks_when_host_does_not_inject(
    tmp_path: Path,
):
    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.builder-default-sinks",
        model="test-model",
        base_url="https://model.invalid/v1",
    )

    application = await (
        SAgentBuilder()
        .with_defaults(session_root=tmp_path / "session-store")
        .with_model_provider(ScriptedModelProvider(()))
        .build(package)
    )

    assert isinstance(application.service("observability.log-sink"), NoopLogSink)
    assert isinstance(
        application.service("observability.diagnostic-sink"), NoopDiagnosticSink
    )
    assert _host_binding(application.resolved_plan, "observability.log-sink").source == (
        "plugin"
    )
    assert _host_binding(
        application.resolved_plan, "observability.diagnostic-sink"
    ).source == "plugin"
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
async def test_materialize_agent_uses_next_manifest_without_a_second_dispatcher(
    tmp_path: Path,
):
    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.materialize-agent",
        model="test-model",
        base_url="https://model.invalid/v1",
    )
    application = await (
        SAgentBuilder()
        .with_defaults(session_root=tmp_path / "session-store")
        .with_model_provider(ScriptedModelProvider(()))
        .build(package)
    )
    dispatcher = application.service("execution.dispatcher")
    next_manifest = _with_runtime_capabilities(
        package,
        **{
            "context.reducer": "sage.context.reducer.window",
            "context.token-estimator": (
                "sage.context.token-estimator.unicode-heuristic"
            ),
        },
    )

    ports = await application.materialize_agent(
        next_manifest,
        agent_id="assistant",
        run_id="run_next",
        model=ScriptedModelProvider(()),
    )
    try:
        assert isinstance(ports.token_estimator, UnicodeHeuristicTokenEstimator)
        assert isinstance(ports.context_reducer, WindowContextReducer)
        assert application.service("execution.dispatcher") is dispatcher
        assert _host_binding(ports.resolved_plan, "context.reducer").plugin_id == (
            "sage.context.reducer.window"
        )
        assert _host_binding(ports.resolved_plan, "context.token-estimator").plugin_id == (
            "sage.context.token-estimator.unicode-heuristic"
        )
        assert sum(
            value.capability == "model.provider"
            for value in ports.resolved_plan.providers
        ) == 1
        assert "desktop-host" not in {
            value.source for value in ports.resolved_plan.providers
        }
    finally:
        for handle in reversed(ports.scope_handles):
            await handle.close()
        await application.close()


@pytest.mark.asyncio
async def test_materialize_agent_reuses_agent_scoped_ports(tmp_path: Path):
    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.materialize-reuse",
        model="test-model",
        base_url="https://model.invalid/v1",
    )
    application = await (
        SAgentBuilder()
        .with_defaults(session_root=tmp_path / "session-store")
        .with_model_provider(ScriptedModelProvider(()))
        .build(package)
    )
    first = await application.materialize_agent(
        package, agent_id="assistant", run_id="run_1"
    )
    second = await application.materialize_agent(
        package, agent_id="assistant", run_id="run_2"
    )
    try:
        assert first.token_estimator is second.token_estimator
        assert first.tool_selection_policy is second.tool_selection_policy
        assert first.continuation_policy is not second.continuation_policy
    finally:
        for handle in reversed((*first.scope_handles, *second.scope_handles)):
            await handle.close()
        await application.close()


@pytest.mark.asyncio
async def test_materialize_agent_isolates_cached_ports_by_tenant_and_agent(tmp_path):
    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.materialize-tenant-isolation",
        model="test-model",
        base_url="https://model.invalid/v1",
    )
    application = await (
        SAgentBuilder()
        .with_defaults(session_root=tmp_path / "session-store")
        .with_model_provider(ScriptedModelProvider(()))
        .build(package, tenant_id="tenant_a")
    )

    tenant_a_first = await application.materialize_agent(
        package,
        agent_id="assistant",
        run_id="run_a1",
    )
    tenant_a_second = await application.materialize_agent(
        package,
        agent_id="assistant",
        run_id="run_a2",
    )
    tenant_b = await application.materialize_agent(
        package,
        tenant_id="tenant_b",
        agent_id="assistant",
        run_id="run_b1",
    )
    try:
        assert tenant_a_first.token_estimator is tenant_a_second.token_estimator
        assert tenant_a_first.token_estimator is not tenant_b.token_estimator
        tenant_a_contexts = [
            handle.context
            for handle in application._scope_handles
            if handle.context.tenant_id == "tenant_a"
            and handle.context.agent_id == "assistant"
        ]
        tenant_b_contexts = [
            handle.context
            for handle in application._scope_handles
            if handle.context.tenant_id == "tenant_b"
            and handle.context.agent_id == "assistant"
        ]
        assert tenant_a_contexts
        assert tenant_b_contexts
        assert all(context.run_id is None for context in tenant_a_contexts)
        assert all(context.run_id is None for context in tenant_b_contexts)
    finally:
        for handle in reversed(
            (
                *tenant_a_first.scope_handles,
                *tenant_a_second.scope_handles,
                *tenant_b.scope_handles,
            )
        ):
            await handle.close()
        await application.close()


@pytest.mark.asyncio
async def test_materialized_plan_reports_only_ports_selected_for_this_call(
    tmp_path: Path,
):
    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.materialize-plan-cache",
        model="test-model",
        base_url="https://model.invalid/v1",
    )
    window = _with_runtime_capabilities(
        package, **{"context.reducer": "sage.context.reducer.window"}
    )
    persistent = _with_runtime_capabilities(
        package, **{"context.reducer": "sage.context.reducer.persistent-summary"}
    )
    application = await (
        SAgentBuilder()
        .with_defaults(session_root=tmp_path / "session-store")
        .with_model_provider(ScriptedModelProvider(()))
        .build(package)
    )
    first = await application.materialize_agent(
        window, agent_id="assistant", run_id="run_1"
    )
    second = await application.materialize_agent(
        persistent, agent_id="assistant", run_id="run_2"
    )
    catalog = object()
    executor = object()
    third = await application.materialize_agent(
        window,
        agent_id="assistant",
        run_id="run_3",
        tool_catalog=catalog,
        tool_executor=executor,
    )
    try:
        assert isinstance(third.context_reducer, WindowContextReducer)
        assert _host_binding(third.resolved_plan, "context.reducer").plugin_id == (
            "sage.context.reducer.window"
        )
        assert sum(
            value.capability == "context.reducer"
            for value in third.resolved_plan.providers
        ) == 1
        assert third.tool_catalog is catalog
        assert third.tool_executor is executor
        assert _host_binding(third.resolved_plan, "tool.catalog").source == "host"
        assert _host_binding(third.resolved_plan, "tool.executor").source == "host"
        assert sum(
            value.capability == "model.provider"
            for value in third.resolved_plan.providers
        ) == 1
    finally:
        for handle in reversed(
            (*first.scope_handles, *second.scope_handles, *third.scope_handles)
        ):
            await handle.close()
        await application.close()


@pytest.mark.asyncio
async def test_materialize_agent_rolls_back_run_scopes_on_later_failure(
    tmp_path: Path,
):
    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.materialize-rollback",
        model="test-model",
        base_url="https://model.invalid/v1",
    )
    application = await (
        SAgentBuilder()
        .with_defaults(session_root=tmp_path / "session-store")
        .with_model_provider(ScriptedModelProvider(()))
        .build(package)
    )
    composer = application._composer
    original_port = composer._port
    opened_run_handles = []

    async def fail_after_continuation(*args, **kwargs):
        value = await original_port(*args, **kwargs)
        if kwargs["capability"] == "agent.continuation-policy":
            opened_run_handles.extend(kwargs["run_handles"])
        if kwargs["capability"] == "memory.recall-query":
            raise RuntimeError("later component failed")
        return value

    composer._port = fail_after_continuation
    try:
        with pytest.raises(RuntimeError, match="later component failed"):
            await application.materialize_agent(
                package, agent_id="assistant", run_id="run_failure"
            )
        assert opened_run_handles
        assert all(handle._closed for handle in opened_run_handles)
    finally:
        composer._port = original_port
        await application.close()


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
        model="test-model",
        base_url="https://model.invalid/v1",
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
        SAgentBuilder()
        .with_defaults(session_root=session_root)
        .with_model_provider(model)
        .with_tool_provider(
            InMemoryToolCatalog(tools),
            InMemoryToolExecutor(
                {tool.name: tool for tool in tools},
                {tool.name: _policy_tool_handler for tool in tools},
            ),
        )
    )
    if policy is not None:
        builder = builder.with_tool_policy(policy)
    return await builder.build(package)


async def _run_to_boundary(application: SAgentApplication, package, *, key: str):
    stream = await application.entrypoint().run_stream(
        StartRun(
            agent_id=package.entrypoint.agent,
            input=(InputItem(role="user", content=(TextBlock(text="go"),)),),
            resolved_spec_hash=application.composition_hash,
            idempotency_key=key,
        ),
        _POLICY_USER,
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
async def test_host_tool_policy_is_visible_in_the_plan_but_does_not_fence_runs(
    tmp_path: Path,
):
    package = _policy_package("test.tool-policy-identity")
    session_root = tmp_path / "session-store"
    hashes: dict[str, str] = {}
    # 同一 session_root 顺序构建，排除存储身份带来的差异。
    for label, policy in (
        ("default", None),
        ("auto", DefaultToolPolicy(approval_strategy=ApprovalStrategy.AUTO_APPROVE)),
        ("ask", DefaultToolPolicy(approval_strategy=ApprovalStrategy.ALWAYS_ASK)),
    ):
        application = await _build_with_tool_policy(
            session_root, package, policy, ScriptedModelProvider(())
        )
        try:
            hashes[label] = application.composition_hash
            plan = application.resolved_plan
            # 策略不是服务：既不暴露给 application.services，也不进入 hash。
            assert "agent.tool-policy" not in application.services
            if policy is None:
                assert all(
                    value.capability != "agent.tool-policy" for value in plan.providers
                )
                continue
            binding = _host_binding(plan, "agent.tool-policy")
            assert binding.source == "host"
            assert binding.plugin_id is None
            assert policy.composition_identity() == policy.policy_hash
            loop = application.entrypoint().driver_factory("run_identity")
            assert loop.tool_policy is policy
        finally:
            await application.close()

    # 审批模式是宿主运行偏好：换一档不改变 composition hash，
    # 上个进程挂起的 Run 在新的审批模式下仍能续跑。
    assert hashes["default"] == hashes["auto"] == hashes["ask"]

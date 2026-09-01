from pathlib import Path
import hashlib
from types import SimpleNamespace

import pytest

from sagents.v2 import RunExecutionBinding, SAgentApplication, SAgentBuilder
from sagents.v2.builder import _ExecutionBoundDriver
from sagents.v2.contracts.commands import InputItem, StartRun
from sagents.v2.contracts.items import TextBlock
from sagents.v2.model.contracts import ModelEventKind, ModelResponse, ModelStreamEvent
from sagents.v2.package.presets import BuiltinPackageFactory
from sagents.v2.package.manifest.runtime import CapabilitySelection
from sagents.v2.package.manifest.agents import AgentMemoryBehavior
from sagents.v2.memory import NoopMemoryProvider
from sagents.v2.runtime.extensions import (
    CapabilityOffer,
    ExtensionDescriptor,
    ExtensionRegistration,
    ExtensionScope,
)
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.agent.policy import ExplicitStatusContinuationPolicy
from sagents.v2.context import (
    ModelConversationSummarizer,
    PersistentSummaryContextReducer,
    ReferenceContextUnitCompactor,
    SessionDerivedConversationSummaryStore,
    UnicodeHeuristicTokenEstimator,
)
from sagents.v2.runtime.execution import ExecutionBindingRequest
from sagents.v2.runtime.session import EphemeralSessionStore
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
from sagents.v2.tool.plugins.official import OfficialToolRuntime


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
            config={"session_store": "untrusted-manifest-value"},
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
    assert reducer.store.session_store is loop.runtime.session_store
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

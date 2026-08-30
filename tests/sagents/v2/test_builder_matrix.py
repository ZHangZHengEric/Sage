from pathlib import Path
import hashlib

import pytest

from sagents.v2 import RunExecutionBinding, SAgent, SAgentBuilder
from sagents.v2.contracts.commands import InputItem, StartRun
from sagents.v2.contracts.items import TextBlock
from sagents.v2.model.contracts import ModelEventKind, ModelResponse, ModelStreamEvent
from sagents.v2.package.presets import BuiltinPackageFactory
from sagents.v2.package.manifest.runtime import ProviderSelection
from sagents.v2.package.manifest.agents import AgentMemoryBehavior
from sagents.v2.memory import NoopMemoryProvider
from sagents.v2.runtime.extensions import (
    CapabilityOffer,
    ExtensionDescriptor,
    ExtensionRegistration,
    ExtensionScope,
)
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
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


def test_public_builder_is_the_composition_entrypoint(tmp_path: Path):
    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.builder",
        model="test-model",
        base_url="https://model.invalid/v1",
    )
    agent = (
        SAgentBuilder()
        .with_defaults(session_root=tmp_path / "session-store")
        .with_model_provider(ScriptedModelProvider(()))
        .build(package)
    )

    assert isinstance(agent, SAgent)
    assert agent.runtime.session_store.capabilities["global_session_index"] is False


@pytest.mark.parametrize(
    ("preset", "memory_enabled"),
    [("assistant", False), ("coder", True)],
)
def test_search_memory_assignment_controls_recall_and_auto_write(
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
    agent = (
        SAgentBuilder()
        .with_defaults(session_root=tmp_path / preset / "session-store")
        .with_memory_provider(NoopMemoryProvider())
        .with_model_provider(ScriptedModelProvider(()))
        .build(package)
    )
    loop = agent.driver_factory("run_1")

    assert loop.automatic_memory_recall is memory_enabled
    assert all(
        value.__class__.__name__ != "MemoryContextSource"
        for value in loop.context_assembler.providers
    )
    assert (agent.memory_service is not None) is memory_enabled
    assert agent.memory_scope["recall"] is memory_enabled
    assert agent.memory_scope["auto_write"] is memory_enabled


def test_registered_third_party_model_plugin_is_selected_by_model_route(tmp_path: Path):
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

    agent = (
        SAgentBuilder()
        .with_defaults(session_root=tmp_path / "session-store")
        .register(registration)
        .build(package)
    )

    assert agent.driver_factory("run_1").model is provider


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
                update={"tool_provider": ProviderSelection(plugin="sage.tool.official")}
            )
        }
    )

    builder = (
        SAgentBuilder()
        .with_defaults(session_root=tmp_path / "session-store")
        .with_model_provider(ScriptedModelProvider(()))
    )
    with pytest.raises(ValueError, match="with_tool_runtime"):
        builder.build(package)

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
    agent = builder.with_tool_runtime(OfficialToolRuntime(handle, issuer)).build(
        package
    )
    assert isinstance(agent, SAgent)


@pytest.mark.asyncio
async def test_execution_binding_provider_receives_actual_run_and_closes_once(tmp_path: Path):
    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.run-binding",
        model="test-model",
        base_url="https://model.invalid/v1",
    )
    package = package.model_copy(
        update={
            "runtime": package.runtime.model_copy(
                update={"tool_provider": ProviderSelection(plugin="sage.tool.official")}
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
    agent = (
        SAgentBuilder()
        .with_defaults(session_root=tmp_path / "session-store")
        .with_model_provider(model)
        .with_execution_binding_provider(bindings)
        .build(package)
    )
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
    await agent.close()

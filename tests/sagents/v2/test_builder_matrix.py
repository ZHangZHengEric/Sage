from pathlib import Path
import hashlib

import pytest

from sagents.v2 import SAgent, SAgentBuilder
from sagents.v2.model.contracts import ModelEventKind, ModelResponse, ModelStreamEvent
from sagents.v2.package.presets import BuiltinPackageFactory
from sagents.v2.package.manifest.runtime import ProviderSelection
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
            filesystem=FileSystemPolicy(
                allowed_operations=frozenset(FileOperation)
            ),
            process=ProcessPolicy(enabled=False),
            network=NetworkPolicy(),
            policy_hash=f"sha256:{digest}",
            metadata={"host_workspace": str(tmp_path)},
        ),
        RequestContext(
            actor=ActorRef(
                principal_id="user_1", principal_type=PrincipalType.USER
            )
        ),
        run_id="run_1",
    )
    agent = builder.with_tool_runtime(OfficialToolRuntime(handle, issuer)).build(package)
    assert isinstance(agent, SAgent)

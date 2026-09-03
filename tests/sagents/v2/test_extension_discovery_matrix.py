from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from sagents.v2 import SAgentBuilder
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.model import ModelProvider
from sagents.v2.memory import NoopMemoryProvider
from sagents.v2.package.manifest.resolver import CompositionResolver
from sagents.v2.package.manifest.root import PluginDeclaration
from sagents.v2.package.manifest.runtime import CapabilitySelection
from sagents.v2.package.presets import BuiltinPackageFactory
from sagents.v2.runtime.extensions import (
    CapabilityOffer,
    ExtensionDescriptor,
    ExtensionRegistration,
    ExtensionScope,
)
from sagents.v2.runtime.extensions import discovery
from sagents.v2.testing.plugins import ScriptedModelProvider


@dataclass(frozen=True)
class _FakeEntryPoint:
    name: str
    value: Any

    def load(self):
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


def _model_registration(
    provider: ModelProvider,
    *,
    plugin_id: str = "acme.model.private-gateway",
    api_version: str = "2",
    observed_configs: list[dict[str, Any]] | None = None,
) -> ExtensionRegistration:
    def factory(context, dependencies):
        if observed_configs is not None:
            observed_configs.append(dict(context.config))
        return provider

    return ExtensionRegistration(
        descriptor=ExtensionDescriptor(
            plugin_id=plugin_id,
            version="1.0.0",
            api_version=api_version,
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
        factory=factory,
    )


def _package_with_declared_model_plugin():
    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.discovered-model",
        model="test-model",
        base_url="https://model.invalid/v1",
    )
    route = package.models["primary"].model_copy(
        update={"plugin": "acme.model.private-gateway"}
    )
    return package.model_copy(
        update={
            "models": {"primary": route},
            "plugins": (
                PluginDeclaration(
                    id="acme.model.private-gateway",
                    version=">=1,<2",
                    config={
                        "gateway_region": "cn-east",
                        "route": "must-be-overridden-by-the-model-route",
                    },
                ),
            ),
        }
    )


@pytest.mark.parametrize("use_resolved_manifest", [False, True])
@pytest.mark.asyncio
async def test_declared_entry_point_is_loaded_and_configured(
    tmp_path: Path, monkeypatch, use_resolved_manifest: bool
):
    monkeypatch.setenv("SAGE_MODEL_API_KEY", "test-key")
    provider = ScriptedModelProvider(())
    observed_configs: list[dict[str, Any]] = []
    registration = _model_registration(provider, observed_configs=observed_configs)
    monkeypatch.setattr(
        discovery.metadata,
        "entry_points",
        lambda **kwargs: (_FakeEntryPoint("acme.model.private-gateway", registration),),
    )
    package = _package_with_declared_model_plugin()
    build_input = (
        CompositionResolver().resolve(package) if use_resolved_manifest else package
    )

    application = await (
        SAgentBuilder()
        .with_defaults(session_root=tmp_path / "session-store")
        .build(build_input)
    )

    assert application.entrypoint().driver_factory("run_1").model.provider is provider
    assert observed_configs[0]["gateway_region"] == "cn-east"
    assert observed_configs[0]["route"]["model"] == "test-model"
    await application.close()


@pytest.mark.asyncio
async def test_manually_registered_declared_plugin_does_not_require_entry_point(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("SAGE_MODEL_API_KEY", "test-key")
    provider = ScriptedModelProvider(())
    registration = _model_registration(provider)

    def unexpected_discovery(**kwargs):
        raise AssertionError("manual registrations must win before discovery")

    monkeypatch.setattr(discovery.metadata, "entry_points", unexpected_discovery)
    application = await (
        SAgentBuilder()
        .with_defaults(session_root=tmp_path / "session-store")
        .register(registration)
        .build(_package_with_declared_model_plugin())
    )

    assert application.entrypoint().driver_factory("run_1").model.provider is provider
    await application.close()


@pytest.mark.asyncio
async def test_resolved_manifest_preserves_runtime_plugin_selection(
    tmp_path, monkeypatch
):
    observed_configs: list[dict[str, Any]] = []

    def factory(context, dependencies):
        observed_configs.append(dict(context.config))
        return NoopMemoryProvider()

    registration = ExtensionRegistration(
        descriptor=ExtensionDescriptor(
            plugin_id="acme.memory.private-store",
            version="1.0.0",
            name="Private memory store",
            provides=(CapabilityOffer(capability="memory.provider", api_version="2"),),
            supported_scopes=frozenset({ExtensionScope.PROCESS}),
        ),
        factory=factory,
    )
    monkeypatch.setattr(
        discovery.metadata,
        "entry_points",
        lambda **kwargs: (_FakeEntryPoint("acme.memory.private-store", registration),),
    )
    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.resolved-runtime-plugin",
        model="test-model",
        base_url="https://model.invalid/v1",
    )
    package = package.model_copy(
        update={
            "plugins": (
                PluginDeclaration(
                    id="acme.memory.private-store",
                    config={"namespace": "default"},
                ),
            ),
            "runtime": package.runtime.model_copy(
                update={
                    "capabilities": {
                        "memory.provider": CapabilitySelection(
                            plugin="acme.memory.private-store",
                            config={"namespace": "agent"},
                        )
                    }
                }
            ),
        }
    )
    resolved = CompositionResolver().resolve(package)

    application = await (
        SAgentBuilder()
        .with_defaults(session_root=tmp_path / "session-store")
        .with_model_provider(ScriptedModelProvider(()))
        .build(resolved)
    )

    assert observed_configs == [{"namespace": "agent"}]
    await application.close()


@pytest.mark.parametrize(
    ("entry_points", "error_code"),
    [
        ((), "extension.entry_point_not_found"),
        (
            (_FakeEntryPoint("acme.model.private-gateway", object()),),
            "extension.entry_point_contract_invalid",
        ),
        (
            (
                _FakeEntryPoint(
                    "acme.model.private-gateway",
                    _model_registration(
                        ScriptedModelProvider(()), plugin_id="other.model"
                    ),
                ),
            ),
            "extension.entry_point_id_mismatch",
        ),
        (
            (
                _FakeEntryPoint(
                    "acme.model.private-gateway",
                    _model_registration(ScriptedModelProvider(()), api_version="3"),
                ),
            ),
            "extension.api_version_unsupported",
        ),
        (
            (
                _FakeEntryPoint(
                    "acme.model.private-gateway", RuntimeError("broken import")
                ),
            ),
            "extension.entry_point_load_failed",
        ),
    ],
)
def test_invalid_declared_entry_points_fail_with_typed_errors(
    monkeypatch, entry_points, error_code
):
    monkeypatch.setattr(
        discovery.metadata,
        "entry_points",
        lambda **kwargs: entry_points,
    )

    with pytest.raises(SageV2Error) as invalid:
        discovery.load_installed_extension("acme.model.private-gateway")

    assert invalid.value.info.code == error_code


def test_duplicate_installed_entry_points_are_rejected(monkeypatch):
    registration = _model_registration(ScriptedModelProvider(()))
    monkeypatch.setattr(
        discovery.metadata,
        "entry_points",
        lambda **kwargs: (
            _FakeEntryPoint("acme.model.private-gateway", registration),
            _FakeEntryPoint("acme.model.private-gateway", registration),
        ),
    )

    with pytest.raises(SageV2Error) as invalid:
        discovery.load_installed_extension("acme.model.private-gateway")

    assert invalid.value.info.code == "extension.entry_point_ambiguous"


def test_declared_plugin_version_must_match_loaded_registration(monkeypatch):
    registration = _model_registration(ScriptedModelProvider(()))
    monkeypatch.setattr(
        discovery.metadata,
        "entry_points",
        lambda **kwargs: (_FakeEntryPoint("acme.model.private-gateway", registration),),
    )

    with pytest.raises(SageV2Error) as mismatch:
        discovery.load_installed_extension(
            "acme.model.private-gateway", version_requirement=">=2,<3"
        )

    assert mismatch.value.info.code == "extension.version_mismatch"


@pytest.mark.asyncio
async def test_manually_registered_plugin_still_obeys_manifest_version(tmp_path):
    provider = ScriptedModelProvider(())
    package = _package_with_declared_model_plugin().model_copy(
        update={
            "plugins": (
                PluginDeclaration(
                    id="acme.model.private-gateway",
                    version=">=2,<3",
                ),
            )
        }
    )

    with pytest.raises(SageV2Error) as mismatch:
        await (
            SAgentBuilder()
            .with_defaults(session_root=tmp_path / "session-store")
            .register(_model_registration(provider))
            .build(package)
        )

    assert mismatch.value.info.code == "extension.version_mismatch"

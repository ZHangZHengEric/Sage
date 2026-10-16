"""One registration/configuration/lifecycle contract for package and host assembly."""

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from app.v2.desktop.backend.composition import build_desktop_application
from examples.sagents_v2_host.__main__ import offline_model
from examples.sagents_v2_host.plugins import estimator_registration
from sagents.v2 import SAgentBuilder
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.package.manifest import SageManifestLoader
from sagents.v2.package.manifest.resolver import CompositionResolver
from sagents.v2.package.manifest.runtime import RuntimeConfig
from sagents.v2.runtime.extensions import (
    CapabilityKey,
    CapabilityOffer,
    ExtensionDescriptor,
    ExtensionRegistration,
    ExtensionScope,
)


def package():
    return SageManifestLoader().load(Path("examples/sagents_v2_host/sage.yaml"))


def builder(tmp_path, registration=None):
    return (
        SAgentBuilder()
        .with_defaults(session_root=tmp_path)
        .with_model_provider(offline_model())
        .register(registration or estimator_registration())
    )


@pytest.mark.asyncio
async def test_runtime_parameter_and_embedded_runtime_have_same_identity(tmp_path):
    manifest = package()
    direct = await builder(tmp_path).build(manifest)
    identity = direct.composition_hash
    await direct.close()
    separate = await builder(tmp_path).build(
        manifest.model_copy(update={"runtime": RuntimeConfig()}),
        runtime=manifest.runtime.model_dump(mode="json"),
    )
    try:
        assert separate.composition_hash == identity
        assert separate.service("context.token-estimator").bytes_per_token == 4
    finally:
        await separate.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("config", [{"bytes_per_token": 0}, {"typo": 4}])
async def test_invalid_registered_plugin_parameters_fail_before_factory(
    tmp_path, config
):
    calls = []
    registration = estimator_registration()
    original_factory = registration.factory

    def factory(context, dependencies):
        calls.append(context)
        return original_factory(context, dependencies)

    with pytest.raises(SageV2Error) as caught:
        await builder(tmp_path, replace(registration, factory=factory)).build(
            package(),
            runtime={
                "capabilities": {
                    "context.token-estimator": {
                        "plugin": registration.descriptor.plugin_id,
                        "config": config,
                    }
                }
            },
        )
    assert caught.value.info.code == "extension.config_invalid"
    assert calls == []


@pytest.mark.asyncio
async def test_resolved_package_cannot_silently_change_runtime(tmp_path):
    resolved = CompositionResolver().resolve(package())
    with pytest.raises(ValueError, match="already resolved"):
        await builder(tmp_path).build(resolved, runtime=RuntimeConfig())


@pytest.mark.asyncio
async def test_desktop_uses_same_custom_plugin_registration_and_config(tmp_path):
    app = await build_desktop_application(
        session_root=tmp_path / "runtime",
        workspace=tmp_path / "workspace",
        extensions=(estimator_registration(),),
        component_selections={
            "context.token-estimator": "example.context.byte-estimator"
        },
        component_configs={"context.token-estimator": {"bytes_per_token": 8}},
    )
    try:
        assert app.service("context.token-estimator").bytes_per_token == 8
    finally:
        await app.close()


@pytest.mark.asyncio
async def test_process_provider_config_names_concurrency_and_shutdown(tmp_path):
    created, stopped = [], []

    def factory(context, dependencies):
        value = {"left": object(), "right": object()}
        created.append(value)
        return value

    registration = ExtensionRegistration(
        descriptor=ExtensionDescriptor(
            plugin_id="example.host.service",
            version="2.0.0",
            name="Test host service",
            provides=tuple(
                CapabilityOffer(
                    capability="example.service", api_version="2", name=name
                )
                for name in ("left", "right")
            ),
            supported_scopes=frozenset({ExtensionScope.PROCESS}),
            config_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        ),
        factory=factory,
        start=lambda value, context, dependencies: {
            CapabilityKey(capability="example.service", name=name): port
            for name, port in value.items()
        },
        stop=lambda value, reason: stopped.append(value),
    )
    app = await builder(tmp_path).register(registration).build(package())
    try:
        selection = {"plugin": "example.host.service", "name": "left"}
        values = await asyncio.gather(
            *(app.process_provider("example.service", selection) for _ in range(12))
        )
        assert len(created) == 1
        assert all(value is created[0]["left"] for value in values)
        right = await app.process_provider(
            "example.service", {**selection, "name": "right"}
        )
        assert right is created[1]["right"]
        assert right is not values[0]
        with pytest.raises(ValueError, match="process scope"):
            await app.process_provider("example.service", {**selection, "scope": "run"})
        with pytest.raises(SageV2Error) as caught:
            await app.process_provider(
                "example.service", {**selection, "config": {"unknown": True}}
            )
        assert caught.value.info.code == "extension.config_invalid"
    finally:
        await app.close()
    assert len(stopped) == 2
    await app.close()
    assert len(stopped) == 2


@pytest.mark.asyncio
async def test_server_registration_and_package_runtime_parameter(tmp_path):
    from app.v2.server.database import Database, DatabaseSettings
    from app.v2.server.packages.builder import PackageBuilder
    from tests.app.v2.server.conftest import FixtureServerHost, make_settings

    registration = estimator_registration()
    settings = make_settings(tmp_path, plugin_overrides={
        "context.token-estimator": {
            "plugin": registration.descriptor.plugin_id,
            "config": {"bytes_per_token": 8},
        },
    })
    host = FixtureServerHost(
        settings, database=Database(DatabaseSettings(
            url=f"sqlite+aiosqlite:///{tmp_path}/host.db",
        )), model_provider=offline_model(), extensions=(registration,),
    )
    from app.v2.server.config.plugins import ServerPluginConfig, revision
    ServerPluginConfig(tmp_path, registry=host.extensions).save(
        settings.plugin_overrides, revision({}),
    )
    await host.start()
    try:
        assert host.application.service("context.token-estimator").bytes_per_token == 8
        managed = await (
            PackageBuilder(settings, None, tmp_path / "package", application=host.application)
            .with_defaults(session_root=tmp_path / "package")
            .with_model_provider(offline_model())
            .register(registration)
            .build(package(), runtime=package().runtime)
        )
        try:
            assert managed.service("context.token-estimator").bytes_per_token == 4
        finally:
            await managed.close()
        assert host.application.service("context.token-estimator").bytes_per_token == 8
        assert host.execution.sandbox_provider is not None
    finally:
        await host.close()
    assert host.execution.sandbox_provider is None

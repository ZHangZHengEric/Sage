"""One registration/configuration/lifecycle contract for package and host assembly."""

from tests.sagents.v2.sdk_fixture import build_registered_package
from tests.sagents.v2.sdk_fixture import fixture_configuration

from tests.sagents.v2.model_fixture import TEST_MODELS

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from examples.v2.host.__main__ import offline_model
from examples.v2.host.plugins import compactor_registration
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
    return SageManifestLoader().load(Path("examples/v2/host/sage.yaml"))


def builder(tmp_path, registration=None):
    return fixture_configuration(
        tmp_path,
        models=TEST_MODELS,
        model=offline_model(),
        registrations=(registration or compactor_registration(),),
    )


def observed_compactor(calls):
    registration = compactor_registration()
    original = registration.factory

    def factory(context, dependencies):
        calls.append(dict(context.config))
        return original(context, dependencies)

    return replace(registration, factory=factory)


@pytest.mark.asyncio
async def test_typed_and_serialized_runtime_have_same_run_identity(tmp_path):
    from tests.sagents.v2.test_standard_execution_configuration import CONTEXT, run

    manifest = package()
    calls = []
    identities = []
    for index, runtime in enumerate(
        (manifest.runtime, manifest.runtime.model_dump(mode="json"))
    ):
        app = await build_registered_package(
            configuration=builder(tmp_path, observed_compactor(calls)),
            package=manifest,
            runtime=runtime,
        )
        try:
            agent = app.loaded_agents[0]
            result, _ = await run(app, agent, f"runtime-{index}")
            assert result.state.value == "completed"
            snapshot = await app.run_configuration(result.run_id, CONTEXT)
            assert snapshot["runtime"]["capabilities"]["context.unit-compactor"][
                "config"
            ] == {"minimum_characters": 4}
            identities.append(snapshot["composition_hash"])
        finally:
            await app.close()
    assert identities[0] == identities[1]
    assert calls == [{"minimum_characters": 4}] * 2


@pytest.mark.asyncio
@pytest.mark.parametrize("config", [{"minimum_characters": 0}, {"typo": 4}])
async def test_invalid_registered_plugin_parameters_fail_before_factory(
    tmp_path, config
):
    calls = []
    registration = compactor_registration()
    original_factory = registration.factory

    def factory(context, dependencies):
        calls.append(context)
        return original_factory(context, dependencies)

    with pytest.raises(SageV2Error) as caught:
        await build_registered_package(
            configuration=builder(tmp_path, replace(registration, factory=factory)),
            package=package(),
            runtime={
                "capabilities": {
                    "context.unit-compactor": {
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
    resolved = CompositionResolver(models=TEST_MODELS).resolve(package())
    with pytest.raises(ValueError, match="already resolved"):
        await build_registered_package(
            configuration=builder(tmp_path), package=resolved, runtime=RuntimeConfig()
        )


@pytest.mark.asyncio
async def test_desktop_uses_same_custom_plugin_registration_and_config(tmp_path):
    from tests.app.v2.desktop.sdk_fixture import desktop, execute

    calls = []
    registration = observed_compactor(calls)
    service, _, _ = desktop(
        tmp_path,
        registrations=(registration,),
        runtime={
            "capabilities": {
                "context.unit-compactor": {
                    "plugin": registration.descriptor.plugin_id,
                    "config": {"minimum_characters": 8},
                }
            },
        },
    )
    try:
        result, _, _ = await execute(service)
        assert result.state.value == "completed"
        snapshot = await service.application.run_configuration(
            result.run_id, service._context("user_1")
        )
        assert snapshot["runtime"]["capabilities"]["context.unit-compactor"][
            "config"
        ] == {"minimum_characters": 8}
        assert calls == [{"minimum_characters": 8}]
    finally:
        await service.close()


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
    from sagents.v2.package.manifest.runtime import CapabilitySelection

    configuration = builder(tmp_path, registration)
    config = configuration.runtime.model_copy(
        update={
            "capabilities": {
                **configuration.runtime.capabilities,
                "example.service": CapabilitySelection(
                    plugin="example.host.service", name="left"
                ),
            }
        }
    )
    app = await build_registered_package(
        configuration=configuration, runtime=config, package=package()
    )
    try:
        values = await asyncio.gather(
            *(
                asyncio.sleep(0, result=app.service("example.service"))
                for _ in range(12)
            )
        )
        assert len(created) == 1
        assert all(value is created[0]["left"] for value in values)
        assert not hasattr(app, "process_provider")
    finally:
        await app.close()
    assert stopped == created
    await app.close()
    assert stopped == created


def test_server_registration_and_package_runtime_parameter(tmp_path):
    from fastapi.testclient import TestClient
    from app.v2.server.database import Database, DatabaseSettings
    from app.v2.server.main import create_app
    from app.v2.server.config.plugins import ServerPluginConfig, revision
    from tests.app.v2.server.conftest import (
        CompletingJudgeModel,
        FixtureServerHost,
        make_settings,
        register_and_login,
    )
    from tests.app.v2.server.test_agui_chat import _run_input, _parse_sse
    from tests.sagents.v2.test_standard_execution_configuration import CONTEXT, run

    calls = []
    registration = observed_compactor(calls)
    settings = make_settings(
        tmp_path,
        plugin_overrides={
            "context.unit-compactor": {
                "plugin": registration.descriptor.plugin_id,
                "config": {"minimum_characters": 8},
            },
        },
    )
    host = FixtureServerHost(
        settings,
        database=Database(
            DatabaseSettings(url=f"sqlite+aiosqlite:///{tmp_path}/host.db")
        ),
        model_provider=CompletingJudgeModel(offline_model()),
        extensions=(registration,),
    )
    ServerPluginConfig(tmp_path, registry=host.extensions).save(
        settings.plugin_overrides, revision({})
    )

    async def standalone():
        managed = await build_registered_package(
            configuration=builder(tmp_path / "package", registration),
            package=package(),
            runtime=package().runtime,
        )
        try:
            result, _ = await run(managed, managed.loaded_agents[0], "package")
            assert result.state.value == "completed"
            snapshot = await managed.run_configuration(result.run_id, CONTEXT)
            assert snapshot["runtime"]["capabilities"]["context.unit-compactor"][
                "config"
            ] == {"minimum_characters": 4}
        finally:
            await managed.close()

    with TestClient(create_app(service=host)) as client:
        token = register_and_login(client)
        response = client.post(
            "/api/agent",
            json=_run_input(),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert "RUN_FINISHED" in {event["type"] for event in _parse_sse(response.text)}
        assert calls == [{"minimum_characters": 8}]
        asyncio.run(standalone())
        assert calls == [{"minimum_characters": 8}, {"minimum_characters": 4}]
        assert host.application.runtime_configuration.capabilities[
            "context.unit-compactor"
        ].config == {"minimum_characters": 8}
        assert host.execution.sandbox_provider is not None
    assert host.execution.sandbox_provider is None

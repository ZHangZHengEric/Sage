
from typing import cast, Mapping
from sagents.v2.sagent import SAgent

from tests.sagents.v2.sdk_fixture import build_registered_package
from tests.sagents.v2.model_fixture import TEST_MODELS
from pathlib import Path

import pytest

from sagents.v2 import SAgentApplication
from sagents.v2.package.presets import BuiltinPackageFactory
from sagents.v2.package.manifest.runtime import CapabilitySelection
from sagents.v2.testing.plugins import ScriptedModelProvider
from sagents.v2.runtime.session import FilesystemSessionStore
from sagents.v2.contracts.run_state import EventCursor


@pytest.mark.asyncio
async def test_builder_returns_application_with_one_close_boundary(tmp_path):
    package = BuiltinPackageFactory.create("assistant", package_id="test.application")
    application = await build_registered_package(tmp_path / "sessions", models=TEST_MODELS,
        model=ScriptedModelProvider(()), package=package)
    try:
        assert isinstance(application, SAgentApplication)
        assert application.service("session.access") is not None
        assert isinstance(application.service("session.store"), FilesystemSessionStore)
        assert not hasattr(application.entrypoint(), "driver_factory")
        with pytest.raises(TypeError):
            getattr(application, "subscribe_interface")("native", EventCursor(run_id="missing", run_sequence=0))
        for capability in ("execution.scheduler", "execution.job-runtime", "execution.dispatcher", "artifact.store", "package.registry"):
            assert application.service(capability) is not None
        loaded = application.loaded_agents[0]
        assert loaded.composition_hash.startswith("sha256:")
        assert loaded.resolved_plan.composition_hash == loaded.composition_hash
        assert loaded.package_id == "test.application"
        bindings = {(value.capability, value.plugin_id, value.source) for value in loaded.resolved_plan.providers}
        assert ("session.store", "sage.session.filesystem", "plugin") in bindings
        assert any(capability == "model.provider" and plugin == "test.fixture.model.provider" for capability, plugin, _ in bindings)
        assert all("credential" not in value.name for value in loaded.resolved_plan.providers)
    finally:
        await application.close()
    await application.close()
    reopened = FilesystemSessionStore(tmp_path / "sessions")
    await reopened.close()


@pytest.mark.asyncio
async def test_build_failure_rolls_back_started_extensions(tmp_path: Path):
    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.application-rollback",

    )
    package = package.model_copy(
        update={
            "runtime": package.runtime.model_copy(
                update={
                    "capabilities": {
                        "session.store": CapabilitySelection(
                            plugin="sage.session.filesystem",
                            config={"root": ""},
                        )
                    }
                }
            )
        }
    )

    with pytest.raises(Exception):
        await (
            build_registered_package(tmp_path, models=TEST_MODELS, model=ScriptedModelProvider(()), package=package)
        )


@pytest.mark.asyncio
async def test_application_stops_execution_resources_before_closing_agents():
    order: list[str] = []

    class Resource:
        async def close(self):
            order.append("dispatcher")

    class Agent:
        async def close(self):
            assert order == ["dispatcher"]
            order.append("agent")

    application = SAgentApplication._from_composition(
        agents=cast('Mapping[str, SAgent]', {"main": Agent()}),
        entrypoint_agent_id="main",
        scope_handles=(),
        services={},
        adapters={},
        composition_hash="sha256:test",
        owned_resources=(Resource(),),
    )
    await application.close()
    assert order == ["dispatcher", "agent"]


@pytest.mark.asyncio
async def test_registered_host_resources_close_in_dependency_order(tmp_path):
    from sagents.v2.package.manifest.runtime import RuntimeConfig
    from sagents.v2.runtime.extensions import CapabilityOffer, ExtensionDependency, ExtensionDescriptor, ExtensionRegistration, ExtensionScope
    from tests.sagents.v2.test_standard_execution_configuration import package, response, run
    order = []
    class Resource:
        def __init__(self, name):
            self.name = name
        async def close(self):
            order.append(self.name)
    def registration(name, dependencies=()):
        def create(context, resolved):
            if dependencies:
                assert resolved.require("test.provider").name == "provider"
            return Resource(name)
        return ExtensionRegistration(descriptor=ExtensionDescriptor(plugin_id="test."+name, name=name, version="1",
            provides=(CapabilityOffer(capability="test."+name, api_version="2"),),
            dependencies=tuple(ExtensionDependency(capability=dependency) for dependency in dependencies),
            supported_scopes=frozenset({ExtensionScope.PROCESS})), factory=create)
    selected = {"test.provider": {"plugin": "test.provider"}, "test.dependent": {"plugin": "test.dependent"},
        "tool.selection-policy": {"plugin": "sage.tool-selection.direct"},
        "agent.continuation-policy": {"plugin": "sage.agent.continuation.deterministic"}}
    application = await build_registered_package(tmp_path, models=TEST_MODELS, model=ScriptedModelProvider((response(),)),
        package=package(), registrations=(registration("provider"), registration("dependent", ("test.provider",))),
        runtime=RuntimeConfig.model_validate({"capabilities": selected}))
    try:
        result, _ = await run(application, application.loaded_agents[0], "resources")
        assert result.state.value == "completed"
        assert not order
        assert not hasattr(application, "adopt_resource")
    finally:
        await application.close()
    await application.close()
    assert order == ["dependent", "provider"]


@pytest.mark.asyncio
async def test_application_close_retries_only_transient_teardown_failures():
    calls: list[str] = []

    class Resource:
        def __init__(self, name, *, fail_once=False):
            self.name = name
            self.fail_once = fail_once

        async def close(self):
            calls.append(self.name)
            if self.fail_once:
                self.fail_once = False
                raise OSError(f"{self.name} unavailable")

    stable = Resource("stable")
    transient = Resource("transient", fail_once=True)
    agent = Resource("agent")
    application = SAgentApplication._from_composition(
        agents=cast('Mapping[str, SAgent]', {"main": agent}),
        entrypoint_agent_id="main",
        scope_handles=(),
        services={},
        adapters={},
        composition_hash="sha256:test",
        owned_resources=(transient, stable),
    )

    with pytest.raises(RuntimeError, match="failed to close"):
        await application.close()
    with pytest.raises(RuntimeError, match="closing"):
        application.entrypoint()
    await application.close()

    assert calls == ["stable", "transient", "transient", "agent"]

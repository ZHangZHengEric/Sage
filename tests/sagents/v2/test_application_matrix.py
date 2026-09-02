from pathlib import Path

import pytest

from sagents.v2 import SAgentApplication, SAgentBuilder
from sagents.v2.package.presets import BuiltinPackageFactory
from sagents.v2.package.manifest.runtime import CapabilitySelection
from sagents.v2.testing.plugins import ScriptedModelProvider
from sagents.v2.runtime.session import FilesystemSessionStore
from sagents.v2.contracts.run_state import EventCursor


@pytest.mark.asyncio
async def test_builder_returns_application_with_one_close_boundary(tmp_path: Path):
    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.application",
        model="test-model",
    )
    application = await (
        SAgentBuilder()
        .with_defaults(session_root=tmp_path / "sessions")
        .with_model_provider(ScriptedModelProvider(()))
        .build(package)
    )

    assert isinstance(application, SAgentApplication)
    assert application.service("session.access") is not None
    with pytest.raises(KeyError):
        application.service("session.store")
    cursor = EventCursor(run_id="run_missing", run_sequence=0)
    with pytest.raises(TypeError):
        application.entrypoint().subscribe_events(cursor)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        application.subscribe_interface(  # type: ignore[call-arg]
            "native", cursor
        )
    assert application.service("execution.scheduler") is not None
    assert application.service("execution.job-runtime") is not None
    assert application.service("artifact.store") is not None
    assert application.service("package.registry") is not None
    assert application.composition_hash.startswith("sha256:")
    assert application.resolved_plan.composition_hash == application.composition_hash
    assert application.resolved_plan.package_id == "test.application"
    bindings = {
        (value.capability, value.plugin_id, value.source)
        for value in application.resolved_plan.providers
    }
    assert (
        "session.store",
        "sage.session.filesystem",
        "plugin",
    ) in bindings
    assert ("model.provider", None, "host") in bindings
    assert ("execution.dispatcher", None, "composition-root") in bindings
    assert all(
        "credential" not in value.name for value in application.resolved_plan.providers
    )

    await application.close()
    await application.close()
    reopened = FilesystemSessionStore(tmp_path / "sessions")
    await reopened.close()


@pytest.mark.asyncio
async def test_build_failure_rolls_back_started_extensions(tmp_path: Path):
    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.application-rollback",
        model="test-model",
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
            SAgentBuilder()
            .with_model_provider(ScriptedModelProvider(()))
            .build(package)
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

    application = SAgentApplication(
        agents={"main": Agent()},
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
async def test_application_can_adopt_a_host_resource_with_explicit_close_order():
    order: list[str] = []

    class Resource:
        def __init__(self, name: str):
            self.name = name

        async def close(self):
            order.append(self.name)

    provider = Resource("provider")
    application = SAgentApplication(
        agents={"main": Resource("agent")},
        entrypoint_agent_id="main",
        scope_handles=(),
        services={},
        adapters={},
        composition_hash="sha256:test",
        owned_resources=(Resource("dispatcher"),),
    )

    await application.adopt_resource(provider, close_after_existing=True)
    await application.adopt_resource(provider, close_after_existing=True)
    await application.close()

    assert order == ["dispatcher", "provider", "agent"]


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
    application = SAgentApplication(
        agents={"main": agent},
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

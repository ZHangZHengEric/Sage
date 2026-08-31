from pathlib import Path

import pytest

from sagents.v2 import SAgentApplication, SAgentBuilder
from sagents.v2.package.presets import BuiltinPackageFactory
from sagents.v2.package.manifest.runtime import CapabilitySelection
from sagents.v2.testing.plugins import ScriptedModelProvider
from sagents.v2.runtime.session import FilesystemSessionStore


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
    assert application.entrypoint().runtime.session_store is application.service(
        "session.store"
    )
    assert application.service("execution.scheduler") is not None
    assert application.service("execution.job-runtime") is not None
    assert application.service("artifact.store") is not None
    assert application.service("package.registry") is not None
    assert application.composition_hash.startswith("sha256:")

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
        await SAgentBuilder().with_model_provider(ScriptedModelProvider(())).build(
            package
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

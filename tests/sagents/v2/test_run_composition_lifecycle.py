"""Host-neutral assembly and resource ownership behavior (no model/network calls)."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from sagents.v2.application import SAgentApplication
from sagents.v2.composition.resources import RunResources


def application():
    return SAgentApplication(
        agents={"main": SimpleNamespace(close=AsyncMock())},
        entrypoint_agent_id="main",
        scope_handles=(),
        services={},
        adapters={},
        composition_hash="test",
    )


class Resource:
    def __init__(self, name, log, failures=0):
        self.name, self.log, self.failures = name, log, failures

    async def close(self):
        self.log.append(self.name)
        if self.failures:
            self.failures -= 1
            raise RuntimeError(f"close {self.name}")


@pytest.mark.asyncio
async def test_services_close_before_dependencies_and_retry_only_failures():
    log = []
    resources = RunResources()
    sandbox = Resource("sandbox", log)
    stable = Resource("stable", log)
    transient = Resource("transient", log, failures=1)
    resources.own(sandbox, dependency=True)
    resources.own(stable)
    resources.own(stable)  # Ownership registration is identity-idempotent.
    resources.own(transient)
    with pytest.raises(RuntimeError, match="transient"):
        await resources.close()
    assert log == ["transient", "stable"]
    await resources.close()
    await resources.close()
    assert log == ["transient", "stable", "transient", "sandbox"]
    assert not resources.pending


@pytest.mark.asyncio
async def test_success_transfers_only_registered_resources_to_host():
    app = application()
    log = []
    borrowed = Resource("borrowed", log)
    driver = SimpleNamespace(execute=AsyncMock(), borrowed=borrowed)

    async def compose(resources):
        resources.own(Resource("owned", log))
        return driver

    run = await app.compose_run(compose)
    assert run.value is driver
    driver.execute.assert_not_called()  # Composition must never start/replay a Run.
    await run.close()
    await app.close()
    assert log == ["owned"]


@pytest.mark.asyncio
async def test_failed_composition_rolls_back_and_retains_failed_cleanup():
    app = application()
    log = []
    failure = ValueError("invalid manifest")

    async def compose(resources):
        resources.own(Resource("sandbox", log), dependency=True)
        resources.own(Resource("scope", log, failures=1))
        raise failure

    with pytest.raises(ValueError) as caught:
        await app.compose_run(compose)
    assert caught.value is failure
    assert log == ["scope", "sandbox"]
    assert "close scope" in failure.__notes__[0]
    await app.close()
    assert log == ["scope", "sandbox", "scope"]


@pytest.mark.asyncio
async def test_cancellation_rolls_back_without_turning_into_success():
    app = application()
    acquired = asyncio.Event()
    wait = asyncio.Event()
    log = []

    async def compose(resources):
        resources.own(Resource("scope", log))
        acquired.set()
        await wait.wait()

    task = asyncio.create_task(app.compose_run(compose))
    await acquired.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert log == ["scope"]
    await app.close()


@pytest.mark.asyncio
async def test_shutdown_waits_for_assembly_then_rejects_new_assembly():
    app = application()
    acquired = asyncio.Event()
    release = asyncio.Event()
    log = []

    async def compose(resources):
        resources.own(Resource("scope", log))
        acquired.set()
        await release.wait()
        raise ValueError("rollback")

    task = asyncio.create_task(app.compose_run(compose))
    await acquired.wait()
    shutdown = asyncio.create_task(app.close())
    await asyncio.sleep(0)
    assert not shutdown.done()
    other = AsyncMock()
    with pytest.raises(RuntimeError, match="closing"):
        await app.compose_run(other)
    other.assert_not_awaited()
    release.set()
    with pytest.raises(ValueError, match="rollback"):
        await task
    await shutdown
    assert log == ["scope"]
    with pytest.raises(RuntimeError, match="closed"):
        await app.compose_run(other)


@pytest.mark.asyncio
async def test_concurrent_resource_close_does_not_duplicate_successful_cleanup():
    resources = RunResources()
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def close():
        calls.append("close")
        entered.set()
        await release.wait()

    resources.own(SimpleNamespace(close=close))
    first = asyncio.create_task(resources.close())
    await entered.wait()
    second = asyncio.create_task(resources.close())
    release.set()
    await asyncio.gather(first, second)
    assert calls == ["close"]


@pytest.mark.asyncio
async def test_shared_runtime_borrows_services_without_transferring_ownership(tmp_path):
    from sagents.v2 import SAgentBuilder
    from sagents.v2.package.manifest import SageManifestLoader
    from sagents.v2.testing.plugins.scripted_model import ScriptedModelProvider

    manifest = SageManifestLoader().loads("""
schema_version: sage/v2
kind: application
metadata: {id: test.shared, version: 1.0.0, name: Shared}
agents:
  main: {name: Main, instructions: {inline: Hello}}
entrypoint: {agent: main}
""")
    model = ScriptedModelProvider(())
    host = (
        await SAgentBuilder()
        .with_defaults(session_root=tmp_path)
        .with_model_provider(model)
        .build(manifest)
    )
    try:
        child = (
            await SAgentBuilder()
            .with_shared_runtime(host)
            .with_model_provider(model)
            .build(manifest)
        )
        assert (
            child.entrypoint().runtime.session_store
            is host.entrypoint().runtime.session_store
        )
        assert child.service("execution.scheduler") is host.service(
            "execution.scheduler"
        )
        await child.close()
        # Closing a borrowing Application must leave shared scheduling usable.
        assert await host.service("execution.scheduler").capabilities()
        assert host.entrypoint()
    finally:
        await host.close()


@pytest.mark.asyncio
async def test_scope_registration_during_shutdown_requires_inflight_assembly():
    app = application()
    entered, release = asyncio.Event(), asyncio.Event()
    scope = SimpleNamespace(close=AsyncMock())

    async def compose(resources):
        entered.set()
        await release.wait()
        app.retain_scope(scope)
        return "ready"

    assembly = asyncio.create_task(app.compose_run(compose))
    await entered.wait()
    shutdown = asyncio.create_task(app.close())
    await asyncio.sleep(0)
    release.set()
    await assembly
    await shutdown
    scope.close.assert_awaited_once()

    app = application()
    entered, release = asyncio.Event(), asyncio.Event()

    async def blocked_close():
        entered.set()
        await release.wait()

    await app.adopt_resource(SimpleNamespace(close=blocked_close))
    shutdown = asyncio.create_task(app.close())
    await entered.wait()
    with pytest.raises(RuntimeError, match="closing"):
        app.retain_scope(SimpleNamespace(close=AsyncMock()))
    release.set()
    await shutdown

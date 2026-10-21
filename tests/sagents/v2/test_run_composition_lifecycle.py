"""Plugin ownership, assembly and shutdown through the standard SDK path."""

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Literal

import asyncio

import pytest

from sagents.v2 import SAgentBuilder
from sagents.v2.runtime.extensions import (
    CapabilityOffer, ExtensionDependency, ExtensionDescriptor, ExtensionRegistration, ExtensionScope,
)
from tests.sagents.v2.model_fixture import TEST_MODELS
from tests.sagents.v2.test_standard_execution_configuration import package


class Resource:
    def __init__(self, name, log, failures=0):
        self.name, self.log, self.failures = name, log, failures

    async def close(self):
        self.log.append(self.name)
        if self.failures:
            self.failures -= 1
            raise RuntimeError("close " + self.name)


def registration(name, factory, *, ownership="owned", dependencies=(), scope=ExtensionScope.PROCESS, capability=None):
    return ExtensionRegistration(
        descriptor=ExtensionDescriptor(plugin_id=name, name=name, version="1",
            provides=(CapabilityOffer(capability=capability or name, api_version="2"),),
            supported_scopes=frozenset({scope}), default_scope=scope,
            dependencies=tuple(ExtensionDependency(capability=value) for value in dependencies),
            config_schema={"type": "object", "additionalProperties": False}),
        factory=factory, ownership=cast("Literal['owned', 'borrowed']", ownership),
    )


def config(root, choices):
    return {"state_root": str(root), "capabilities": {
        "session.store": {"plugin": "sage.session.filesystem", "config": {"root": str(root)}},
        **{name: {"plugin": plugin} for name, plugin in choices.items()},
    }}


@pytest.mark.asyncio
async def test_success_closes_only_owned_registered_resources_once(tmp_path):
    log = []
    builder = SAgentBuilder()
    for name, ownership in (("test.owned", "owned"), ("test.borrowed", "borrowed")):
        value = Resource(name, log)
        builder.register(registration(name, lambda context, deps, value=value: value, ownership=ownership))
    app = await builder.build(runtime=config(tmp_path, {name: name for name in ("test.owned", "test.borrowed")}))
    await asyncio.gather(app.close(), app.close())
    assert log == ["test.owned"]


@pytest.mark.asyncio
async def test_factory_failure_rolls_back_owned_dependencies_and_preserves_borrowed(tmp_path):
    log = []
    builder = SAgentBuilder()
    for name, ownership in (("test.owned", "owned"), ("test.borrowed", "borrowed")):
        value = Resource(name, log)
        builder.register(registration(name, lambda context, deps, value=value: value, ownership=ownership))
    def fail(context, deps):
        assert deps.require("test.owned").name == "test.owned"
        raise ValueError("factory failure")
    builder.register(registration("test.failing", fail, dependencies=("test.owned", "test.borrowed")))
    with pytest.raises(ValueError, match="factory failure"):
        await builder.build(runtime=config(tmp_path, {name: name for name in ("test.owned", "test.borrowed", "test.failing")}))
    assert log == ["test.owned"]


@pytest.mark.asyncio
async def test_cancelling_standard_build_rolls_back_created_scopes(tmp_path):
    entered = asyncio.Event()
    log = []
    resource = Resource("owned", log)
    builder = SAgentBuilder().register(registration("test.owned", lambda context, deps: resource))
    async def blocked(context, deps):
        entered.set()
        await asyncio.Event().wait()
    builder.register(registration("test.blocked", blocked, dependencies=("test.owned",)))
    task = asyncio.create_task(builder.build(runtime=config(tmp_path, {name: name for name in ("test.owned", "test.blocked")})))
    await asyncio.wait_for(entered.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert log == ["owned"]


@pytest.mark.asyncio
async def test_shutdown_waits_for_standard_agent_load_and_rejects_new_loads(tmp_path):
    from sagents.v2.testing.plugins import ScriptedModelProvider
    entered, release = asyncio.Event(), asyncio.Event()
    log = []
    class Model(ScriptedModelProvider):
        async def close(self):
            log.append("model")
    async def create(context, deps):
        entered.set()
        await release.wait()
        return Model(())
    builder = SAgentBuilder().register(registration("test.model", create,
        scope=ExtensionScope.AGENT, capability="model.provider"))
    app = await builder.build(runtime=config(tmp_path, {"model.provider": "test.model"}), models=TEST_MODELS, tenant_id="owner")
    loading = asyncio.create_task(app.load_agent(package()))
    await asyncio.wait_for(entered.wait(), 5)
    shutdown = asyncio.create_task(app.close())
    await asyncio.sleep(0)
    assert not shutdown.done()
    with pytest.raises(RuntimeError, match="closing"):
        await app.load_agent(package())
    release.set()
    await loading
    await shutdown
    assert log == ["model"]


@pytest.mark.asyncio
async def test_run_cleanup_attempts_independent_resources_and_retries_only_failures():
    # A unit check of the SDK-owned cleanup primitive; no host Driver injection.
    from sagents.v2.composition.drivers import _CompositeRunResource
    log = []
    resources = _CompositeRunResource(Resource("sandbox", log), Resource("scope", log, failures=1), Resource("controller", log))
    with pytest.raises(RuntimeError, match="close scope"):
        await resources.close()
    assert log == ["controller", "scope", "sandbox"]
    await asyncio.gather(resources.close(), resources.close())
    assert log == ["controller", "scope", "sandbox", "scope"]


def test_standard_application_has_no_host_assembly_or_driver_injection_ports():
    from sagents.v2 import SAgentApplication
    import sagents.v2 as sdk
    assert not any(name.startswith("with_") for name in dir(SAgentBuilder))
    assert not hasattr(sdk, "HostAgentExecution")
    assert not any(hasattr(SAgentApplication, name) for name in (
        "compose_run", "adopt_resource", "process_provider", "materialize_agent", "retain_scope",
    ))


@pytest.mark.asyncio
async def test_registry_snapshot_preserves_bound_factory_owner(tmp_path):
    calls = []
    class Owner:
        def create(self, context, deps):
            calls.append(context.scope)
            return self
    owner = Owner()
    builder = SAgentBuilder().register(registration("test.owner", owner.create, ownership="borrowed"))
    app = await builder.build(runtime=config(tmp_path, {"test.owner": "test.owner"}))
    try:
        assert app.service("test.owner") is owner
        assert calls == [ExtensionScope.PROCESS]
    finally:
        await app.close()

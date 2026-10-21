"""One Session storage plugin publishes three ports with one resource lifecycle."""

from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from sagents.v2.runtime.extensions import (
    CapabilityRequirement, ExtensionHost, ExtensionRegistry, ExtensionScope,
    ExtensionScopeContext,
)
from sagents.v2.runtime.extensions.official import builtin_extension_registry
from sagents.v2.runtime.session.plugins import SESSION_STORAGE_CAPABILITIES


@pytest.mark.asyncio
@pytest.mark.parametrize("plugin,config", [
    ("sage.session.ephemeral", {}),
    ("sage.session.filesystem", {}),
    ("sage.session.mysql", {"dsn": "mysql://root@127.0.0.1/sage"}),
    ("sage.session.redis-mysql", {"dsn": "mysql://root@127.0.0.1/sage",
                                  "redis_url": "redis://localhost:6379"}),
])
async def test_session_storage_publishes_all_ports_and_closes_once(tmp_path, monkeypatch, plugin, config):
    config = {"root": str(tmp_path)} if plugin.endswith("filesystem") else config
    registration = builtin_extension_registry().get(plugin)
    if not registration.descriptor.availability.available:
        pytest.skip(registration.descriptor.availability.reason)
    context = ExtensionScopeContext(scope=ExtensionScope.PROCESS, scope_id="process", config=config)
    store = registration.factory(context, None)
    if "mysql" in plugin:
        monkeypatch.setattr(store._coordinator, "_ensure_ready", AsyncMock())
        if plugin.endswith("redis-mysql"):
            monkeypatch.setattr(store._coordinator, "list_dispatchable_runs", AsyncMock(return_value=[]))
    original_start, original_close = store.start, store.close
    start, close = AsyncMock(wraps=original_start), AsyncMock(wraps=original_close)
    monkeypatch.setattr(type(store), "start", start)
    monkeypatch.setattr(type(store), "close", close, raising=False)
    registry = ExtensionRegistry()
    registry.register(replace(registration, factory=lambda context, deps: store))
    host = ExtensionHost(registry)
    plan = host.plan(tuple(CapabilityRequirement(capability=key, api_version="2")
                           for key in SESSION_STORAGE_CAPABILITIES), configs={plugin: config})
    handle = await host.open_scope(context, plan)
    try:
        assert plan.graph.plugin_ids == (plugin,)
        assert handle.providers.require("session.store") is store
        assert handle.providers.require("derived-state.store") is store
        artifacts = handle.providers.require("artifact.store")
        assert artifacts.session_store is store
        assert artifacts.for_run("run").session_store is store
        start.assert_awaited_once()
    finally:
        await handle.close()
    close.assert_awaited_once()


def test_legacy_session_adapter_plugins_are_not_registered():
    registry = builtin_extension_registry()
    assert not registry.contains("sage.derived-state.session")
    assert not registry.contains("sage.artifact.session")


@pytest.mark.asyncio
async def test_application_reuses_storage_when_all_three_capabilities_select_it(tmp_path):
    from sagents.v2 import SAgentBuilder

    choice = {"plugin": "sage.session.filesystem", "config": {"root": str(tmp_path / "sessions")}}
    app = await SAgentBuilder().build(runtime={
        "state_root": str(tmp_path), "start_workers": False,
        "capabilities": {key: choice for key in SESSION_STORAGE_CAPABILITIES},
    })
    try:
        store = app.service("session.store")
        assert app.service("derived-state.store") is store
        assert app.service("artifact.store").session_store is store
        storage = [item for item in app.resolved_plan.providers
                   if item.capability in SESSION_STORAGE_CAPABILITIES]
        assert len(storage) == 3
        assert {item.plugin_id for item in storage} == {"sage.session.filesystem"}
    finally:
        await app.close()


@pytest.mark.asyncio
async def test_application_rejects_conflicting_configuration_for_shared_storage(tmp_path):
    from sagents.v2 import SAgentBuilder

    with pytest.raises(ValueError, match="same Session storage configuration"):
        await SAgentBuilder().build(runtime={
            "state_root": str(tmp_path), "start_workers": False,
            "capabilities": {
                "session.store": {"plugin": "sage.session.filesystem", "config": {"root": str(tmp_path / "sessions")}},
                "artifact.store": {"plugin": "sage.session.filesystem", "config": {"root": str(tmp_path / "other")}},
            },
        })


@pytest.mark.asyncio
@pytest.mark.parametrize("capability,plugin", [
    ("derived-state.store", "sage.derived-state.ephemeral"),
    ("artifact.store", "sage.artifact.ephemeral"),
])
async def test_consumer_can_select_independent_storage_with_combined_session_storage(tmp_path, capability, plugin):
    from sagents.v2 import SAgentBuilder
    from sagents.v2.runtime.extensions import CapabilityOffer, ExtensionDependency, ExtensionDescriptor, ExtensionRegistration

    seen = []
    consumer = ExtensionRegistration(
        descriptor=ExtensionDescriptor(
            plugin_id="test.storage-consumer", name="Storage consumer", version="1",
            provides=(CapabilityOffer(capability="test.consumer", api_version="2"),),
            dependencies=tuple(ExtensionDependency(capability=key) for key in SESSION_STORAGE_CAPABILITIES),
            supported_scopes=frozenset({ExtensionScope.PROCESS}),
        ), factory=lambda context, deps: seen.append(deps) or object(),
    )
    builder = SAgentBuilder().register(consumer)
    app = await builder.build(runtime={
        "state_root": str(tmp_path), "start_workers": False,
        "capabilities": {
            "session.store": {"plugin": "sage.session.filesystem", "config": {"root": str(tmp_path / "sessions")}},
            capability: {"plugin": plugin},
            "test.consumer": {"plugin": "test.storage-consumer"},
        },
    })
    try:
        assert seen[0].require("session.store") is app.service("session.store")
        assert seen[0].require("derived-state.store") is app.service("derived-state.store")
        assert seen[0].require("artifact.store") is app.service("artifact.store")
        selected = [item for item in app.resolved_plan.providers if item.capability == capability]
        assert len(selected) == 1 and selected[0].plugin_id == plugin
    finally:
        await app.close()

    # Also resolve both plugins together, before either has been started.
    registry = builtin_extension_registry()
    registry.register(consumer)
    host = ExtensionHost(registry)
    config = {"sage.session.filesystem": {"root": str(tmp_path / "cold")}}
    plan = host.plan((CapabilityRequirement(capability="test.consumer", api_version="2"),),
                     selections={**{key: "sage.session.filesystem" for key in SESSION_STORAGE_CAPABILITIES},
                                 capability: plugin}, configs=config)
    context = ExtensionScopeContext(scope=ExtensionScope.PROCESS, scope_id="cold")
    handle = await host.open_scope(context, plan)
    try:
        assert seen[-1].require(capability) is handle.providers.require(capability)
        # A selected view must not overwrite the Session plugin's own ports.
        reuse_plan = host.plan((CapabilityRequirement(capability=capability, api_version="2"),),
                               selections={capability: "sage.session.filesystem"}, configs=config)
        reused = await host.open_scope(context, reuse_plan, available=(handle,))
        try:
            value = reused.providers.require(capability)
            store = handle.providers.require("session.store")
            assert (value if capability == "derived-state.store" else value.session_store) is store
        finally:
            await reused.close()
    finally:
        await handle.close()


@pytest.mark.asyncio
async def test_ephemeral_storage_can_publish_all_ports_through_sync_host():
    host = ExtensionHost(builtin_extension_registry())
    plan = host.plan((CapabilityRequirement(capability="session.store", api_version="2"),),
                     selections={"session.store": "sage.session.ephemeral"})
    handle = host.open_scope_sync(ExtensionScopeContext(scope=ExtensionScope.PROCESS, scope_id="sync"), plan)
    try:
        store = handle.providers.require("session.store")
        assert handle.providers.require("derived-state.store") is store
        assert handle.providers.require("artifact.store").session_store is store
    finally:
        await handle.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("capability", ["derived-state.store", "artifact.store"])
async def test_storage_ports_cannot_select_a_second_session_backend(tmp_path, capability):
    from sagents.v2 import SAgentBuilder

    with pytest.raises(ValueError, match="selected session.store plugin"):
        await SAgentBuilder().build(runtime={
            "state_root": str(tmp_path), "start_workers": False,
            "capabilities": {
                "session.store": {"plugin": "sage.session.filesystem", "config": {"root": str(tmp_path / "sessions")}},
                capability: {"plugin": "sage.session.ephemeral"},
            },
        })

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.runtime.extensions.contracts import (
    CapabilityKey,
    CapabilityOffer,
    CapabilityRequirement,
    ExtensionDependency,
    ExtensionDescriptor,
    ExtensionRegistration,
    ExtensionScope,
    ExtensionScopeContext,
    StopReason,
)
from sagents.v2.runtime.extensions.host import ExtensionHost


EVENTS: list[str] = []


@dataclass
class FakePlugin:
    descriptor: ExtensionDescriptor
    value: object = field(default_factory=object)
    fail_start: bool = False
    dependencies_seen: dict = field(default_factory=dict)
    starts: int = 0
    stops: list[StopReason] = field(default_factory=list)

    async def start(self, context, dependencies):
        EVENTS.append(f"start:{self.descriptor.plugin_id}")
        self.starts += 1
        self.dependencies_seen = dict(dependencies)
        if self.fail_start:
            raise RuntimeError(f"failed:{self.descriptor.plugin_id}")
        return {
            f"{offer.capability}:{offer.name}": self.value
            for offer in self.descriptor.provides
        }

    async def stop(self, reason):
        EVENTS.append(f"stop:{self.descriptor.plugin_id}:{reason.value}")
        self.stops.append(reason)

    @property
    def registration(self):
        return ExtensionRegistration(
            descriptor=self.descriptor,
            factory=lambda context, dependencies: self,
        )


def plugin(
    plugin_id,
    capability,
    *,
    api="2",
    name="default",
    requires=(),
    optional=(),
    scopes=(ExtensionScope.RUN,),
    multi=False,
    fail=False,
):
    return FakePlugin(
        ExtensionDescriptor(
            plugin_id=plugin_id,
            version="2.0.0",
            name=plugin_id,
            provides=(
                CapabilityOffer(
                    capability=capability,
                    api_version=api,
                    name=name,
                    multi_provider=multi,
                ),
            ),
            dependencies=tuple(
                ExtensionDependency(
                    capability=value.capability,
                    api_version=value.api_version,
                    name=value.name,
                    optional=value.optional,
                )
                for value in (*requires, *optional)
            ),
            supported_scopes=frozenset(scopes),
        ),
        fail_start=fail,
    )


def requirement(capability, api=">=2,<3", *, name=None, optional=False):
    return CapabilityRequirement(
        capability=capability,
        api_version=api,
        name=name,
        optional=optional,
    )


def context(scope=ExtensionScope.RUN):
    return ExtensionScopeContext(scope=scope, scope_id="scope_1", run_id="run_1")


@pytest.fixture(autouse=True)
def clear_events():
    EVENTS.clear()


def test_duplicate_plugin_id_is_rejected_per_host():
    host = ExtensionHost()
    host.register(plugin("plugin_a", "model").registration)
    with pytest.raises(SageV2Error) as duplicate:
        host.register(plugin("plugin_a", "tool").registration)
    assert duplicate.value.info.code == "extension.duplicate_id"


@pytest.mark.parametrize(
    ("api", "valid"),
    [("1", False), ("2", True), ("2.5", True), ("3", False)],
)
def test_capability_api_version_range_matrix(api, valid):
    host = ExtensionHost()
    host.register(plugin("provider", "model", api=api).registration)
    if valid:
        graph = host.resolve((requirement("model"),))
        assert graph.plugin_ids == ("provider",)
    else:
        with pytest.raises(SageV2Error) as missing:
            host.resolve((requirement("model"),))
        assert missing.value.info.code == "extension.capability_missing"


def test_missing_required_fails_but_missing_optional_is_ignored():
    host = ExtensionHost()
    with pytest.raises(SageV2Error) as missing:
        host.resolve((requirement("model"),))
    assert missing.value.info.code == "extension.capability_missing"
    graph = host.resolve((requirement("telemetry", optional=True),))
    assert graph.plugin_ids == ()


def test_ambiguous_single_provider_requires_explicit_selection():
    host = ExtensionHost()
    host.register(plugin("model_a", "model").registration)
    host.register(plugin("model_b", "model").registration)
    with pytest.raises(SageV2Error) as ambiguous:
        host.resolve((requirement("model"),))
    assert ambiguous.value.info.code == "extension.capability_ambiguous"
    graph = host.resolve((requirement("model"),), selections={"model": "model_b"})
    assert graph.plugin_ids == ("model_b",)


@pytest.mark.asyncio
async def test_multi_provider_capability_returns_stable_tuple():
    host = ExtensionHost()
    first = plugin("sink_a", "observability_sink", multi=True)
    second = plugin("sink_b", "observability_sink", multi=True)
    host.register(first.registration)
    host.register(second.registration)
    plan = host.plan((requirement("observability_sink"),))
    handle = await host.open_scope(context(), plan)
    assert handle.providers.get_provider("observability_sink") == (
        first.value,
        second.value,
    )
    await handle.close()


@pytest.mark.asyncio
async def test_dependencies_start_before_consumers_and_stop_in_reverse():
    event_store = plugin("event_store", "event_store")
    agent_loop = plugin(
        "agent_loop",
        "agent_loop",
        requires=(requirement("event_store"),),
    )
    host = ExtensionHost()
    host.register(agent_loop.registration)
    host.register(event_store.registration)

    plan = host.plan((requirement("agent_loop"),))
    handle = await host.open_scope(context(), plan)
    assert EVENTS == ["start:event_store", "start:agent_loop"]
    assert agent_loop.dependencies_seen == {
        CapabilityKey(capability="event_store"): event_store.value
    }
    await handle.close()
    assert EVENTS[-2:] == [
        "stop:agent_loop:scope_closed",
        "stop:event_store:scope_closed",
    ]


@pytest.mark.asyncio
async def test_hierarchy_opens_async_cross_scope_dependencies_and_owns_them():
    process_store = plugin(
        "process_store",
        "event_store",
        scopes=(ExtensionScope.PROCESS,),
    )
    run_loop = plugin(
        "run_loop",
        "agent_loop",
        requires=(requirement("event_store"),),
        scopes=(ExtensionScope.RUN,),
    )
    host = ExtensionHost()
    host.register(process_store.registration)
    host.register(run_loop.registration)
    plan = host.plan(
        (requirement("agent_loop"),),
        scope_overrides={
            "process_store": ExtensionScope.PROCESS,
            "run_loop": ExtensionScope.RUN,
        },
    )

    handle = await host.open_scope_hierarchy(context(), plan)

    assert run_loop.dependencies_seen == {
        CapabilityKey(capability="event_store"): process_store.value
    }
    await handle.close()
    assert EVENTS == [
        "start:process_store",
        "start:run_loop",
        "stop:run_loop:scope_closed",
        "stop:process_store:scope_closed",
    ]


def test_dependency_cycle_is_rejected_before_any_plugin_starts():
    plugin_a = plugin("plugin_a", "a", requires=(requirement("b"),))
    plugin_b = plugin("plugin_b", "b", requires=(requirement("a"),))
    host = ExtensionHost()
    host.register(plugin_a.registration)
    host.register(plugin_b.registration)
    with pytest.raises(SageV2Error) as cycle:
        host.resolve((requirement("a"),))
    assert cycle.value.info.code == "extension.dependency_cycle"
    assert EVENTS == []


@pytest.mark.asyncio
async def test_start_failure_rolls_back_failing_and_started_plugins():
    dependency = plugin("dependency", "store")
    failing = plugin(
        "failing",
        "runtime",
        requires=(requirement("store"),),
        fail=True,
    )
    host = ExtensionHost()
    host.register(dependency.registration)
    host.register(failing.registration)
    plan = host.plan((requirement("runtime"),))
    with pytest.raises(RuntimeError, match="failed:failing"):
        await host.open_scope(context(), plan)
    assert failing.stops == [StopReason.START_FAILED]
    assert dependency.stops == [StopReason.START_FAILED]
    assert EVENTS == [
        "start:dependency",
        "start:failing",
        "stop:failing:start_failed",
        "stop:dependency:start_failed",
    ]


@pytest.mark.asyncio
async def test_scope_is_validated_before_plugin_start():
    process_only = plugin(
        "process_catalog",
        "tool_catalog",
        scopes=(ExtensionScope.PROCESS,),
    )
    host = ExtensionHost()
    host.register(process_only.registration)
    plan = host.plan((requirement("tool_catalog"),))
    with pytest.raises(SageV2Error) as scope:
        await host.open_scope(context(ExtensionScope.RUN), plan)
    assert scope.value.info.code == "extension.scope_hierarchy_invalid"
    assert process_only.starts == 0


def test_resolution_hash_is_deterministic_and_changes_with_selection():
    host = ExtensionHost()
    host.register(plugin("model_a", "model").registration)
    host.register(plugin("model_b", "model").registration)
    first = host.resolve((requirement("model"),), selections={"model": "model_a"})
    repeat = host.resolve((requirement("model"),), selections={"model": "model_a"})
    second = host.resolve((requirement("model"),), selections={"model": "model_b"})
    assert first.resolution_hash == repeat.resolution_hash
    assert first.resolution_hash != second.resolution_hash


@pytest.mark.asyncio
async def test_two_hosts_have_no_shared_registry_or_lifecycle_state():
    first_host = ExtensionHost()
    second_host = ExtensionHost()
    first_plugin = plugin("model", "model")
    second_plugin = plugin("model", "model")
    first_host.register(first_plugin.registration)
    second_host.register(second_plugin.registration)
    first_handle = await first_host.open_scope(
        context(), first_host.plan((requirement("model"),))
    )
    second_handle = await second_host.open_scope(
        context(), second_host.plan((requirement("model"),))
    )
    assert first_handle.providers.get_provider("model") is first_plugin.value
    assert second_handle.providers.get_provider("model") is second_plugin.value
    assert (
        first_handle.providers.get_provider("model")
        is not second_handle.providers.get_provider("model")
    )
    await first_handle.close()
    assert first_plugin.stops == [StopReason.SCOPE_CLOSED]
    assert second_plugin.stops == []
    await second_handle.close()

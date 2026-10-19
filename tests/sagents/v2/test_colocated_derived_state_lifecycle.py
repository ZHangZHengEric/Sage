"""A borrowed session store exposes derived state without restarting itself."""

import pytest

from sagents.v2.runtime.extensions import (
    CapabilityOffer, CapabilityRequirement, ExtensionDescriptor, ExtensionHost,
    ExtensionRegistration, ExtensionRegistry, ExtensionScope, ExtensionScopeContext,
)
from sagents.v2.runtime.extensions.core import core_registrations


@pytest.mark.asyncio
async def test_colocated_derived_state_does_not_restart_or_close_session_plugin():
    class Store:
        starts = 0
        closes = 0

        async def start(self, context, dependencies):
            self.starts += 1
            return {"session.store": self}

        async def close(self):
            self.closes += 1

        async def get_derived_state(self, *args, **kwargs):
            pass

        async def put_derived_state(self, *args, **kwargs):
            pass

        async def delete_derived_state(self, *args, **kwargs):
            pass

    store = Store()
    registry = ExtensionRegistry()
    registry.register(ExtensionRegistration(
        descriptor=ExtensionDescriptor(
            plugin_id="test.session", name="Session", version="1",
            provides=(CapabilityOffer(capability="session.store", api_version="2"),),
            supported_scopes=frozenset({ExtensionScope.PROCESS}),
        ), factory=lambda context, deps: store,
    ))
    registry.register(next(item for item in core_registrations()
                           if item.descriptor.plugin_id == "sage.derived-state.session"))
    host = ExtensionHost(registry)
    plan = host.plan((
        CapabilityRequirement(capability="session.store", api_version="2"),
        CapabilityRequirement(capability="derived-state.store", api_version="2"),
    ))
    handle = await host.open_scope(
        ExtensionScopeContext(scope=ExtensionScope.PROCESS, scope_id="process"), plan,
    )
    assert handle.providers.require("derived-state.store") is store
    assert store.starts == 1
    await handle.close()
    assert store.closes == 1

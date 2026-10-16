"""Open a selected provider through ExtensionHost; never construct plugins directly."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sagents.v2.runtime.extensions import (
    CapabilityRequirement,
    ExtensionHost,
    ExtensionRegistry,
    ExtensionScope,
    ExtensionScopeContext,
    ExtensionScopeHandle,
)


async def open_provider(
    host: ExtensionHost,
    extensions: ExtensionRegistry,
    parent,
    plugin_id: str,
    config: dict[str, Any],
    capability: str,
    *,
    scope: ExtensionScope,
    scope_id: str,
    tenant_id: str | None = None,
    agent_id: str | None = None,
    run_id: str | None = None,
    offer_name: str | None = None,
    register: Callable[[ExtensionScopeHandle], None] | None = None,
):
    registration = extensions.get(plugin_id)
    if capability not in {
        offer.capability for offer in registration.descriptor.provides
    }:
        raise ValueError(f"extension {plugin_id!r} does not provide {capability!r}")
    names = tuple(
        offer.name for offer in registration.descriptor.provides
        if offer.capability == capability
    )
    name = offer_name if offer_name is not None else names[0]
    if name == "default" and name not in names and len(names) == 1:
        name = names[0]
    if name not in names:
        raise ValueError(f"extension {plugin_id!r} does not provide {capability!r} named {name!r}")
    plan = host.plan(
        (
            CapabilityRequirement(
                capability=capability,
                api_version=("3" if capability == "execution.sandbox" else ">=2,<3"),
                name=name,
            ),
        ),
        selections={capability: plugin_id},
        configs={plugin_id: config},
        scope_overrides={plugin_id: scope},
    )
    handle = await host.open_scope_hierarchy(
        ExtensionScopeContext(
            scope=scope,
            scope_id=scope_id,
            tenant_id=tenant_id,
            agent_id=(
                agent_id
                if scope in {ExtensionScope.AGENT, ExtensionScope.RUN}
                else None
            ),
            run_id=run_id if scope == ExtensionScope.RUN else None,
        ),
        plan,
        parent=parent if scope != ExtensionScope.PROCESS else None,
    )
    if register is not None:
        register(handle)
    return handle.providers.require(capability, name), handle

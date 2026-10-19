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
    available: tuple[ExtensionScopeHandle, ...] = (),
    runtime=None,
    agent_configuration=None,
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
    requirements = (CapabilityRequirement(
        capability=capability,
        api_version=("3" if capability == "execution.sandbox" else ">=2,<3"),
        name=name,
    ),)
    sources = _scope_sources((*available, *((parent,) if parent else ())))
    selections = {capability: plugin_id}
    configs = {plugin_id: config}
    scopes = {plugin_id: scope}
    queue = [registration]
    visited = set()
    while queue:
        current = queue.pop()
        if current.descriptor.plugin_id in visited:
            continue
        visited.add(current.descriptor.plugin_id)
        for dependency in current.descriptor.dependencies:
            selected = () if runtime is None else runtime.selections(dependency.capability)
            selected = tuple(item for item in selected if dependency.name is None or item.name == dependency.name)
            if len(selected) > 1:
                raise ValueError(f"ambiguous dependency {dependency.capability!r}; select a named provider")
            candidates = [source for source in sources if _matches_identity(
                source.context, tenant_id, agent_id, run_id,
            ) and any(
                offer.capability == dependency.capability
                and (dependency.name is None or offer.name == dependency.name)
                for started in source._started for offer in started.registration.descriptor.provides
            )]
            if selected:
                choice = selected[0]
                dependency_id = choice.plugin
                dependency_config = dict(choice.config)
                dependency_scope = choice.scope
            else:
                ids = {started.registration.descriptor.plugin_id for source in candidates
                       for started in source._started
                       if any(offer.capability == dependency.capability
                              and (dependency.name is None or offer.name == dependency.name)
                              for offer in started.registration.descriptor.provides)}
                if len(ids) != 1:
                    continue  # The ordinary resolver reports missing/ambiguous dependencies.
                dependency_id = ids.pop()
                dependency_config, dependency_scope = {}, None
            descriptor = extensions.get(dependency_id).descriptor
            for source in candidates:
                if dependency_id in source.configurations:
                    dependency_config = {**source.configurations[dependency_id], **dependency_config}
                    dependency_scope = dependency_scope or source.context.scope
            key = dependency.capability if dependency.name is None else f"{dependency.capability}:{dependency.name}"
            if key in selections and selections[key] != dependency_id:
                raise ValueError(f"conflicting dependency selection for {key!r}")
            selections[key] = dependency_id
            configs[dependency_id] = dependency_config
            scopes[dependency_id] = dependency_scope or descriptor.resolved_default_scope()
            queue.append(extensions.get(dependency_id))
    plan = host.plan(requirements, selections=selections, configs=configs, scope_overrides=scopes)
    rank = {item: index for index, item in enumerate(ExtensionScope)}
    created = []
    try:
        for level in sorted(set(plan.scopes.values()) | {scope}, key=rank.__getitem__):
            if rank[level] > rank[scope]:
                continue
            context = ExtensionScopeContext(
                scope=level, scope_id=scope_id if level == scope else f"{scope_id}:{level.value}",
                tenant_id=tenant_id,
                agent_id=agent_id if level in {ExtensionScope.AGENT, ExtensionScope.RUN} else None,
                run_id=run_id if level == ExtensionScope.RUN else None,
                agent_configuration=agent_configuration if level in {ExtensionScope.AGENT, ExtensionScope.RUN} else None,
            )
            handle = await host.open_scope(context, plan, available=(*sources, *created))
            if level != scope and not handle._started:
                continue
            created.append(handle)
            if level != scope and register is not None:
                register(handle)
        handle = created[-1]
        if register is None:
            handle._owned_ancestors = tuple(created[:-1])
    except BaseException as exc:
        for item in reversed(created):
            try:
                await item.close()
            except BaseException as close_exc:
                exc.add_note(f"dependency rollback also failed: {close_exc}")
        raise
    if register is not None:
        register(handle)
    return handle.providers.require(capability, name), handle


def _matches_identity(context, tenant_id, agent_id, run_id):
    return (context.scope == ExtensionScope.PROCESS or (
        context.tenant_id == tenant_id
        and (context.scope == ExtensionScope.TENANT or (
            context.agent_id == agent_id
            and (context.scope == ExtensionScope.AGENT or context.run_id == run_id)
        ))
    ))


def _scope_sources(handles):
    result, seen = [], set()
    def visit(handle):
        if id(handle) in seen or handle._closed:
            return
        seen.add(id(handle))
        if handle.parent is not None:
            visit(handle.parent)
        for ancestor in handle._owned_ancestors:
            visit(ancestor)
        result.append(handle)
    for handle in handles:
        visit(handle)
    return tuple(result)


class DeferredRunCapability:
    """A diagnostic marker; the implementation is opened only after Run admission."""
    def __init__(self, plugin_id, capability):
        self.plugin_id, self.capability = plugin_id, capability

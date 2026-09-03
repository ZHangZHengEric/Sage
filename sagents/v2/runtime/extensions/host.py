"""Resolved, hierarchical extension composition and lifecycle management."""

from __future__ import annotations

import inspect
import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.runtime.extensions.contracts import (
    CapabilityKey,
    CapabilityRequirement,
    ExtensionRegistration,
    ExtensionScope,
    ExtensionScopeContext,
    ProviderSet,
    StopReason,
)
from sagents.v2.runtime.extensions.registry import ExtensionRegistry
from sagents.v2.runtime.extensions.resolver import (
    ExtensionResolver,
    ResolvedExtensionGraph,
)
from sagents.v2.runtime.extensions.scope import ExtensionScopeHandle, StartedExtension


_SCOPE_RANK = {
    ExtensionScope.PROCESS: 0,
    ExtensionScope.TENANT: 1,
    ExtensionScope.AGENT: 2,
    ExtensionScope.RUN: 3,
}


@dataclass(frozen=True)
class ExtensionCompositionPlan:
    """One validated provider graph reused while opening nested scopes."""

    graph: ResolvedExtensionGraph
    configs: Mapping[str, Mapping[str, Any]]
    scopes: Mapping[str, ExtensionScope]
    composition_hash: str


class ExtensionHost:
    """Resolve providers once and create deterministic nested scope instances."""

    def __init__(
        self,
        registry: ExtensionRegistry | None = None,
        *,
        built_in_only: bool = False,
    ) -> None:
        self.registry = registry or ExtensionRegistry()
        self.resolver = ExtensionResolver(self.registry)
        self.built_in_only = built_in_only

    def register(self, registration: ExtensionRegistration) -> None:
        self.registry.register(registration)

    def resolve(self, *args, **kwargs):
        return self.resolver.resolve(*args, **kwargs)

    def plan(
        self,
        requirements: tuple[CapabilityRequirement, ...],
        *,
        selections: Mapping[str, str] | None = None,
        configs: Mapping[str, Mapping[str, Any]] | None = None,
        scope_overrides: Mapping[str, ExtensionScope] | None = None,
    ) -> ExtensionCompositionPlan:
        graph = self.resolver.resolve(requirements, selections=selections)
        self._validate_graph_trust(graph)
        supplied_configs = dict(configs or {})
        supplied_scopes = dict(scope_overrides or {})
        unknown = (set(supplied_configs) | set(supplied_scopes)) - set(graph.plugin_ids)
        if unknown:
            raise _error(
                "extension.unselected_configuration",
                ErrorCategory.VALIDATION,
                f"configuration was supplied for unselected extensions: {sorted(unknown)}",
            )

        validated_configs: dict[str, Mapping[str, Any]] = {}
        scopes: dict[str, ExtensionScope] = {}
        for plugin_id in graph.plugin_ids:
            registration = self.registry.get(plugin_id)
            descriptor = registration.descriptor
            raw_config = dict(supplied_configs.get(plugin_id, {}))
            try:
                schema = descriptor.config_schema or {
                    "type": "object",
                    "additionalProperties": True,
                }
                Draft202012Validator(schema).validate(raw_config)
                if registration.config_model is not None:
                    model = registration.config_model.model_validate(raw_config)
                    validated = {
                        key: value
                        for key, value in model
                        if key in model.model_fields_set
                    }
                else:
                    validated = raw_config
            except Exception as exc:
                raise _error(
                    "extension.config_invalid",
                    ErrorCategory.VALIDATION,
                    f"invalid configuration for extension {plugin_id!r}: {exc}",
                ) from exc
            selected_scope = supplied_scopes.get(
                plugin_id, descriptor.resolved_default_scope()
            )
            if selected_scope not in descriptor.supported_scopes:
                raise _error(
                    "extension.scope_unsupported",
                    ErrorCategory.VALIDATION,
                    f"extension {plugin_id!r} does not support scope "
                    f"{selected_scope.value!r}",
                )
            validated_configs[plugin_id] = MappingProxyType(dict(validated))
            scopes[plugin_id] = selected_scope

        for consumer_id, provider_id in graph.dependencies:
            if _SCOPE_RANK[scopes[provider_id]] > _SCOPE_RANK[scopes[consumer_id]]:
                raise _error(
                    "extension.invalid_scope_dependency",
                    ErrorCategory.VALIDATION,
                    f"{consumer_id!r} at {scopes[consumer_id].value!r} cannot depend "
                    f"on shorter-lived {provider_id!r} at {scopes[provider_id].value!r}",
                )
        composition_hash = _composition_hash(
            graph.resolution_hash,
            validated_configs,
            scopes,
        )
        return ExtensionCompositionPlan(
            graph=graph,
            configs=MappingProxyType(validated_configs),
            scopes=MappingProxyType(scopes),
            composition_hash=composition_hash,
        )

    async def open_scope(
        self,
        context: ExtensionScopeContext,
        plan: ExtensionCompositionPlan,
        *,
        parent: ExtensionScopeHandle | None = None,
    ) -> ExtensionScopeHandle:
        self._validate_graph_trust(plan.graph)
        context = _normalized_scope_context(context)
        if parent is None and any(
            _SCOPE_RANK[selected_scope] < _SCOPE_RANK[context.scope]
            for selected_scope in plan.scopes.values()
        ):
            raise _error(
                "extension.scope_hierarchy_invalid",
                ErrorCategory.VALIDATION,
                "opening a nested extension scope requires its parent scope handle",
            )
        if parent is not None:
            if parent._closed:
                raise _error(
                    "extension.parent_scope_closed",
                    ErrorCategory.RESOURCE_LOST,
                    "cannot open a child scope from a closed parent",
                )
            if _SCOPE_RANK[parent.context.scope] >= _SCOPE_RANK[context.scope]:
                raise _error(
                    "extension.scope_hierarchy_invalid",
                    ErrorCategory.VALIDATION,
                    "child extension scope must be shorter-lived than its parent",
                )

        providers = parent.providers.as_dict() if parent is not None else {}
        started: list[StartedExtension] = []
        starting: StartedExtension | None = None
        try:
            for plugin_id in plan.graph.start_order:
                if plan.scopes[plugin_id] != context.scope:
                    continue
                registration = self.registry.get(plugin_id)
                descriptor = registration.descriptor
                plugin_context = context.model_copy(
                    update={"config": dict(plan.configs[plugin_id])}
                )
                dependencies = ProviderSet(
                    {
                        key: value
                        for key, value in providers.items()
                        if any(
                            dependency.capability == key.capability
                            and (dependency.name is None or dependency.name == key.name)
                            for dependency in descriptor.dependencies
                        )
                    }
                )
                self._validate_dependencies_available(descriptor, dependencies)
                instance = registration.factory(plugin_context, dependencies)
                if inspect.isawaitable(instance):
                    instance = await instance
                starting = StartedExtension(registration, instance)
                produced = await _start_extension(
                    starting, plugin_context, dependencies
                )
                expected = {
                    CapabilityKey(capability=offer.capability, name=offer.name)
                    for offer in descriptor.provides
                }
                if set(produced) != expected:
                    raise _error(
                        "extension.provider_contract_mismatch",
                        ErrorCategory.PROVIDER_PERMANENT,
                        f"extension {plugin_id!r} produced "
                        f"{sorted(map(str, produced))}; expected "
                        f"{sorted(map(str, expected))}",
                    )
                for key, provider in produced.items():
                    if key in providers:
                        matching = [
                            value
                            for value in plan.graph.capabilities
                            if value.capability == key.capability
                            and value.name == key.name
                        ]
                        if not matching or not all(
                            value.multi_provider for value in matching
                        ):
                            raise _error(
                                "extension.provider_key_conflict",
                                ErrorCategory.CONFLICT,
                                f"provider key {key} was produced more than once",
                            )
                        current = providers[key]
                        providers[key] = (
                            (*current, provider)
                            if isinstance(current, tuple)
                            else (current, provider)
                        )
                    else:
                        providers[key] = provider
                started.append(starting)
                starting = None
        except BaseException as exc:
            rollback = ([starting] if starting is not None else []) + list(
                reversed(started)
            )
            for value in rollback:
                if value is not None:
                    try:
                        await _stop_extension(value, StopReason.START_FAILED)
                    except BaseException as stop_exc:
                        exc.add_note(
                            "extension rollback also failed for "
                            f"{value.registration.descriptor.plugin_id!r}: {stop_exc}"
                        )
            raise
        return ExtensionScopeHandle(
            graph=plan.graph,
            context=context,
            providers=ProviderSet(providers),
            _started=started,
            parent=parent,
            composition_hash=plan.composition_hash,
        )

    async def open_scope_hierarchy(
        self,
        context: ExtensionScopeContext,
        plan: ExtensionCompositionPlan,
        *,
        parent: ExtensionScopeHandle | None = None,
    ) -> ExtensionScopeHandle:
        """Open every required lifetime level and return one owning leaf handle."""

        selected_scopes = sorted(
            {
                scope
                for scope in plan.scopes.values()
                if _SCOPE_RANK[scope] <= _SCOPE_RANK[context.scope]
            },
            key=_SCOPE_RANK.__getitem__,
        )
        if not selected_scopes:
            return await self.open_scope(context, plan, parent=parent)
        current_parent = parent
        if current_parent is not None:
            parent_plugin_ids: set[str] = set()
            ancestor = current_parent
            while ancestor is not None:
                parent_plugin_ids.update(
                    value.registration.descriptor.plugin_id
                    for value in ancestor._started
                )
                ancestor = ancestor.parent
            inherited_plugin_ids = {
                plugin_id
                for plugin_id, scope in plan.scopes.items()
                if _SCOPE_RANK[scope] <= _SCOPE_RANK[current_parent.context.scope]
            }
            missing_in_parent = inherited_plugin_ids.difference(parent_plugin_ids)
            if missing_in_parent:
                raise _error(
                    "extension.parent_scope_incomplete",
                    ErrorCategory.VALIDATION,
                    "the supplied parent scope does not own required longer-lived "
                    f"extensions: {sorted(missing_in_parent)}",
                )
        created: list[ExtensionScopeHandle] = []
        try:
            for scope in selected_scopes:
                if (
                    current_parent is not None
                    and _SCOPE_RANK[scope] <= _SCOPE_RANK[current_parent.context.scope]
                ):
                    continue
                scope_context = context.model_copy(
                    update={
                        "scope": scope,
                        "scope_id": (
                            context.scope_id
                            if scope == context.scope
                            else f"{context.scope_id}:{scope.value}"
                        ),
                    }
                )
                handle = await self.open_scope(
                    scope_context,
                    plan,
                    parent=current_parent,
                )
                created.append(handle)
                current_parent = handle
        except BaseException as exc:
            for handle in reversed(created):
                try:
                    await handle.close(StopReason.START_FAILED)
                except BaseException as close_exc:
                    exc.add_note(f"scope rollback also failed: {close_exc}")
            raise
        if not created:
            if current_parent is None or (
                _SCOPE_RANK[current_parent.context.scope] >= _SCOPE_RANK[context.scope]
            ):
                raise _error(
                    "extension.scope_hierarchy_invalid",
                    ErrorCategory.VALIDATION,
                    "extension hierarchy has no shorter-lived leaf scope to open",
                )
            created.append(await self.open_scope(context, plan, parent=current_parent))
        leaf = created[-1]
        leaf._owned_ancestors = tuple(created[:-1])
        return leaf

    def open_scope_sync(
        self,
        context: ExtensionScopeContext,
        plan: ExtensionCompositionPlan,
        *,
        parent: ExtensionScopeHandle | None = None,
    ) -> ExtensionScopeHandle:
        """Open a scope for synchronous embedding hosts.

        This is intentionally a Scope Manager operation, not a second Builder
        path. It preserves dependency validation, provider contracts, rollback,
        and reverse close bookkeeping, while rejecting asynchronous plugins so
        they cannot be accidentally bound to a temporary event loop.
        """

        self._validate_graph_trust(plan.graph)
        context = _normalized_scope_context(context)
        if parent is None and any(
            _SCOPE_RANK[selected_scope] < _SCOPE_RANK[context.scope]
            for selected_scope in plan.scopes.values()
        ):
            raise _error(
                "extension.scope_hierarchy_invalid",
                ErrorCategory.VALIDATION,
                "opening a nested extension scope requires its parent scope handle",
            )
        if parent is not None and (
            parent._closed
            or _SCOPE_RANK[parent.context.scope] >= _SCOPE_RANK[context.scope]
        ):
            raise _error(
                "extension.scope_hierarchy_invalid",
                ErrorCategory.VALIDATION,
                "invalid or closed parent extension scope",
            )

        providers = parent.providers.as_dict() if parent is not None else {}
        started: list[StartedExtension] = []
        starting: StartedExtension | None = None
        try:
            for plugin_id in plan.graph.start_order:
                if plan.scopes[plugin_id] != context.scope:
                    continue
                registration = self.registry.get(plugin_id)
                descriptor = registration.descriptor
                plugin_context = context.model_copy(
                    update={"config": dict(plan.configs[plugin_id])}
                )
                dependencies = ProviderSet(
                    {
                        key: value
                        for key, value in providers.items()
                        if any(
                            dependency.capability == key.capability
                            and (dependency.name is None or dependency.name == key.name)
                            for dependency in descriptor.dependencies
                        )
                    }
                )
                self._validate_dependencies_available(descriptor, dependencies)
                instance = registration.factory(plugin_context, dependencies)
                if inspect.isawaitable(instance):
                    close = getattr(instance, "close", None)
                    if close is not None:
                        close()
                    raise _error(
                        "extension.async_plugin_requires_async_host",
                        ErrorCategory.VALIDATION,
                        f"extension {plugin_id!r} requires open_scope()",
                    )
                starting = StartedExtension(registration, instance)
                if registration.start is not None:
                    produced = registration.start(
                        instance, plugin_context, dependencies
                    )
                else:
                    start = getattr(instance, "start", None)
                    produced = (
                        start(plugin_context, dependencies)
                        if start is not None
                        else {
                            CapabilityKey(
                                capability=offer.capability, name=offer.name
                            ): instance
                            for offer in descriptor.provides
                        }
                    )
                if inspect.isawaitable(produced):
                    close = getattr(produced, "close", None)
                    if close is not None:
                        close()
                    raise _error(
                        "extension.async_plugin_requires_async_host",
                        ErrorCategory.VALIDATION,
                        f"extension {plugin_id!r} requires open_scope()",
                    )
                produced = dict(produced)
                expected = {
                    CapabilityKey(capability=offer.capability, name=offer.name)
                    for offer in descriptor.provides
                }
                if set(produced) != expected:
                    raise _error(
                        "extension.provider_contract_mismatch",
                        ErrorCategory.PROVIDER_PERMANENT,
                        f"extension {plugin_id!r} produced an invalid provider set",
                    )
                for key, provider in produced.items():
                    if key in providers:
                        matching = [
                            value
                            for value in plan.graph.capabilities
                            if value.capability == key.capability
                            and value.name == key.name
                        ]
                        if not matching or not all(
                            value.multi_provider for value in matching
                        ):
                            raise _error(
                                "extension.provider_key_conflict",
                                ErrorCategory.CONFLICT,
                                f"provider key {key} was produced more than once",
                            )
                        current = providers[key]
                        providers[key] = (
                            (*current, provider)
                            if isinstance(current, tuple)
                            else (current, provider)
                        )
                    else:
                        providers[key] = provider
                started.append(starting)
                starting = None
        except Exception as exc:
            # Synchronous embeddings cannot await asynchronous stop hooks. All
            # objects accepted above are sync-only by contract, so close them
            # directly during rollback.
            rollback = ([starting] if starting is not None else []) + list(
                reversed(started)
            )
            for value in rollback:
                stop = value.registration.stop or getattr(value.instance, "stop", None)
                close = getattr(value.instance, "close", None)
                if stop is not None or close is not None:
                    try:
                        result = (
                            stop(value.instance, StopReason.START_FAILED)
                            if value.registration.stop is not None
                            else stop(StopReason.START_FAILED)
                            if stop is not None
                            else close()
                        )
                        if inspect.isawaitable(result):
                            result.close()
                    except Exception as stop_exc:
                        exc.add_note(
                            "extension rollback also failed for "
                            f"{value.registration.descriptor.plugin_id!r}: {stop_exc}"
                        )
            raise
        return ExtensionScopeHandle(
            graph=plan.graph,
            context=context,
            providers=ProviderSet(providers),
            _started=started,
            parent=parent,
            composition_hash=plan.composition_hash,
        )

    def _validate_graph_trust(self, graph: ResolvedExtensionGraph) -> None:
        if not self.built_in_only:
            return
        external = sorted(
            plugin_id
            for plugin_id in graph.plugin_ids
            if not self.registry.is_trusted_builtin(plugin_id)
        )
        if external:
            raise _error(
                "extension.plugin_trust_policy_violation",
                ErrorCategory.VALIDATION,
                "built_in_only policy rejected external extensions: "
                + ", ".join(external),
            )

    @staticmethod
    def _validate_dependencies_available(descriptor, dependencies: ProviderSet) -> None:
        missing = sorted(
            f"{dependency.capability}:{dependency.name or '*'}"
            for dependency in descriptor.dependencies
            if not dependency.optional
            and not any(
                key.capability == dependency.capability
                and (dependency.name is None or key.name == dependency.name)
                for key in dependencies
            )
        )
        if missing:
            raise _error(
                "extension.dependency_unavailable",
                ErrorCategory.RESOURCE_LOST,
                f"extension {descriptor.plugin_id!r} is missing resolved providers: "
                + ", ".join(missing),
            )


async def _start_extension(
    started: StartedExtension,
    context: ExtensionScopeContext,
    dependencies: ProviderSet,
) -> dict[CapabilityKey, Any]:
    registration = started.registration
    if registration.start is not None:
        produced = registration.start(started.instance, context, dependencies)
    else:
        start = getattr(started.instance, "start", None)
        if start is not None:
            produced = start(context, dependencies)
        elif len(registration.descriptor.provides) == 1:
            offer = registration.descriptor.provides[0]
            return {
                CapabilityKey(capability=offer.capability, name=offer.name): (
                    started.instance
                )
            }
        else:
            raise _error(
                "extension.start_required",
                ErrorCategory.PROVIDER_PERMANENT,
                f"extension {registration.descriptor.plugin_id!r} provides multiple "
                "capabilities and requires a start hook",
            )
    if inspect.isawaitable(produced):
        produced = await produced
    normalized: dict[CapabilityKey, Any] = {}
    for key, value in dict(produced).items():
        if isinstance(key, CapabilityKey):
            normalized[key] = value
            continue
        capability, separator, name = str(key).rpartition(":")
        if not separator:
            capability, name = str(key), "default"
        normalized[CapabilityKey(capability=capability, name=name)] = value
    return normalized


async def _stop_extension(
    started: StartedExtension,
    reason: StopReason,
) -> None:
    registration = started.registration
    if registration.stop is not None:
        result = registration.stop(started.instance, reason)
    else:
        stop = getattr(started.instance, "stop", None)
        if stop is not None:
            result = stop(reason)
        else:
            close = getattr(started.instance, "close", None)
            result = close() if close is not None else None
    if inspect.isawaitable(result):
        await result


def _error(code: str, category: ErrorCategory, message: str) -> SageV2Error:
    return SageV2Error(
        RuntimeErrorInfo(
            code=code,
            category=category,
            message=message,
            safe_to_resume=True,
        )
    )


def _normalized_scope_context(
    context: ExtensionScopeContext,
) -> ExtensionScopeContext:
    """Expose only identities that belong to the current lifetime boundary."""

    if context.scope == ExtensionScope.PROCESS:
        updates = {"tenant_id": None, "agent_id": None, "run_id": None}
    elif context.scope == ExtensionScope.TENANT:
        updates = {"agent_id": None, "run_id": None}
    elif context.scope == ExtensionScope.AGENT:
        updates = {"run_id": None}
    else:
        updates = {}
    return context.model_copy(update=updates) if updates else context


def _composition_hash(
    resolution_hash: str,
    configs: Mapping[str, Mapping[str, Any]],
    scopes: Mapping[str, ExtensionScope],
) -> str:
    payload = {
        "resolution": resolution_hash,
        "configs": _composition_value(configs),
        "scopes": {key: value.value for key, value in sorted(scopes.items())},
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _composition_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, bytes):
        return {"bytes_sha256": hashlib.sha256(value).hexdigest()}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {
            str(key): _composition_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_composition_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(
            (_composition_value(item) for item in value),
            key=lambda item: json.dumps(item, sort_keys=True, default=str),
        )
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _composition_value(model_dump(mode="python"))
    secret_value = getattr(value, "get_secret_value", None)
    if callable(secret_value):
        encoded = str(secret_value()).encode()
        return {"secret_sha256": hashlib.sha256(encoded).hexdigest()}
    identity = getattr(value, "composition_identity", None)
    if callable(identity):
        identity = identity()
    if identity is not None:
        return {
            "type": f"{type(value).__module__}.{type(value).__qualname__}",
            "identity": _composition_value(identity),
        }
    return {"type": f"{type(value).__module__}.{type(value).__qualname__}"}

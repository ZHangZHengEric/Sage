"""Factory-driven extension lifecycle host."""

from __future__ import annotations

import inspect
from typing import Any, Mapping

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.runtime.extensions.contracts import (
    CapabilityRequirement,
    ExtensionRegistration,
    ExtensionScopeContext,
    StopReason,
)
from sagents.v2.runtime.extensions.registry import ExtensionRegistry
from sagents.v2.runtime.extensions.resolver import ExtensionResolver
from sagents.v2.runtime.extensions.scope import ExtensionScopeHandle, StartedExtension


class ExtensionHost:
    """Create fresh scoped instances from registered factories."""

    def __init__(self, registry: ExtensionRegistry | None = None) -> None:
        self.registry = registry or ExtensionRegistry()
        self.resolver = ExtensionResolver(self.registry)

    def register(self, registration: ExtensionRegistration) -> None:
        self.registry.register(registration)

    def resolve(self, *args, **kwargs):
        return self.resolver.resolve(*args, **kwargs)

    async def open_scope(
        self,
        context: ExtensionScopeContext,
        requirements: tuple[CapabilityRequirement, ...],
        *,
        selections: Mapping[str, str] | None = None,
    ) -> ExtensionScopeHandle:
        graph = self.resolver.resolve(requirements, selections=selections)
        providers: dict[str, Any] = {}
        started: list[StartedExtension] = []
        starting: StartedExtension | None = None
        try:
            for plugin_id in graph.start_order:
                registration = self.registry.get(plugin_id)
                descriptor = registration.descriptor
                if context.scope not in descriptor.supported_scopes:
                    raise _error(
                        "extension.scope_unsupported",
                        ErrorCategory.VALIDATION,
                        f"extension {plugin_id!r} does not support "
                        f"scope {context.scope.value!r}",
                    )
                dependencies = {
                    key: value
                    for key, value in providers.items()
                    if any(
                        dependency.capability == key.split(":", 1)[0]
                        for dependency in descriptor.dependencies
                    )
                }
                instance = registration.factory(context, dependencies)
                if inspect.isawaitable(instance):
                    instance = await instance
                starting = StartedExtension(registration, instance)
                if registration.start is not None:
                    produced = registration.start(instance, context, dependencies)
                else:
                    start = getattr(instance, "start", None)
                    if start is not None:
                        produced = start(context, dependencies)
                    elif len(descriptor.provides) == 1:
                        offer = descriptor.provides[0]
                        produced = {f"{offer.capability}:{offer.name}": instance}
                    else:
                        raise _error(
                            "extension.start_required",
                            ErrorCategory.PROVIDER_PERMANENT,
                            f"extension {plugin_id!r} provides multiple capabilities "
                            "and requires a start hook",
                        )
                if inspect.isawaitable(produced):
                    produced = await produced
                produced = dict(produced)
                expected = {
                    f"{offer.capability}:{offer.name}" for offer in descriptor.provides
                }
                if set(produced) != expected:
                    raise _error(
                        "extension.provider_contract_mismatch",
                        ErrorCategory.PROVIDER_PERMANENT,
                        f"extension {plugin_id!r} produced {sorted(produced)}; "
                        f"expected {sorted(expected)}",
                    )
                for key, provider in produced.items():
                    if key in providers:
                        matching = [
                            value
                            for value in graph.capabilities
                            if f"{value.capability}:{value.name}" == key
                        ]
                        if not matching or not all(
                            value.multi_provider for value in matching
                        ):
                            raise _error(
                                "extension.provider_key_conflict",
                                ErrorCategory.CONFLICT,
                                f"provider key {key!r} was produced more than once",
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
        except Exception:
            rollback = ([starting] if starting is not None else []) + list(
                reversed(started)
            )
            for value in rollback:
                if value is None:
                    continue
                try:
                    if value.registration.stop is not None:
                        result = value.registration.stop(
                            value.instance, StopReason.START_FAILED
                        )
                    else:
                        stop = getattr(value.instance, "stop", None)
                        result = stop(StopReason.START_FAILED) if stop else None
                    if inspect.isawaitable(result):
                        await result
                except Exception:
                    pass
            raise
        return ExtensionScopeHandle(graph, providers, started)


def _error(code: str, category: ErrorCategory, message: str) -> SageV2Error:
    return SageV2Error(
        RuntimeErrorInfo(
            code=code,
            category=category,
            message=message,
            safe_to_resume=True,
        )
    )

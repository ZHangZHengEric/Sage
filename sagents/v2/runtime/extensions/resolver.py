"""Deterministic dependency and capability resolution."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Mapping

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.runtime.extensions.contracts import (
    CapabilityRequirement,
    ExtensionDescriptor,
)
from sagents.v2.runtime.extensions.registry import ExtensionRegistry


@dataclass(frozen=True)
class ResolvedCapability:
    capability: str
    name: str
    api_version: str
    plugin_id: str
    multi_provider: bool = False


@dataclass(frozen=True)
class ResolvedExtensionGraph:
    plugin_ids: tuple[str, ...]
    start_order: tuple[str, ...]
    capabilities: tuple[ResolvedCapability, ...]
    dependencies: tuple[tuple[str, str], ...]
    resolution_hash: str


class ExtensionResolver:
    def __init__(self, registry: ExtensionRegistry) -> None:
        self.registry = registry

    def resolve(
        self,
        requirements: tuple[CapabilityRequirement, ...],
        *,
        selections: Mapping[str, str] | None = None,
    ) -> ResolvedExtensionGraph:
        selections = dict(selections or {})
        offers = defaultdict(list)
        for registration in self.registry.registrations():
            descriptor = registration.descriptor
            if not descriptor.availability.available:
                continue
            for offer in descriptor.provides:
                offers[offer.capability].append((descriptor, offer))

        selected: dict[str, ExtensionDescriptor] = {}
        capabilities: list[ResolvedCapability] = []
        dependencies: dict[str, set[str]] = defaultdict(set)
        queue: list[tuple[str | None, CapabilityRequirement]] = [
            (None, requirement) for requirement in requirements
        ]
        visited = set()
        while queue:
            consumer_id, requirement = queue.pop(0)
            visit_key = (
                consumer_id,
                requirement.capability,
                requirement.api_version,
                requirement.name,
            )
            if visit_key in visited:
                continue
            visited.add(visit_key)
            candidates = [
                (descriptor, offer)
                for descriptor, offer in offers.get(requirement.capability, ())
                if (requirement.name is None or offer.name == requirement.name)
                and _version_satisfies(offer.api_version, requirement.api_version)
            ]
            selected_id = selections.get(requirement.capability)
            if selected_id is not None:
                candidates = [
                    value for value in candidates if value[0].plugin_id == selected_id
                ]
            if not candidates:
                if requirement.optional:
                    continue
                raise _error(
                    "extension.capability_missing",
                    ErrorCategory.VALIDATION,
                    f"no extension satisfies {requirement.capability!r} "
                    f"{requirement.api_version!r}",
                )
            if len(candidates) > 1 and not all(
                offer.multi_provider for _, offer in candidates
            ):
                raise _error(
                    "extension.capability_ambiguous",
                    ErrorCategory.CONFLICT,
                    f"capability {requirement.capability!r} has multiple providers: "
                    f"{sorted(value.plugin_id for value, _ in candidates)}",
                )
            chosen = (
                candidates
                if all(offer.multi_provider for _, offer in candidates)
                else candidates[:1]
            )
            for descriptor, offer in chosen:
                selected[descriptor.plugin_id] = descriptor
                resolved = ResolvedCapability(
                    capability=offer.capability,
                    name=offer.name,
                    api_version=offer.api_version,
                    plugin_id=descriptor.plugin_id,
                    multi_provider=offer.multi_provider,
                )
                if resolved not in capabilities:
                    capabilities.append(resolved)
                if consumer_id and consumer_id != descriptor.plugin_id:
                    dependencies[consumer_id].add(descriptor.plugin_id)
                for dependency in descriptor.dependencies:
                    queue.append((descriptor.plugin_id, dependency.requirement()))

        order = _topological_order(set(selected), dependencies)
        resolved_capabilities = tuple(
            sorted(
                capabilities,
                key=lambda item: (item.capability, item.name, item.plugin_id),
            )
        )
        encoded = json.dumps(
            {
                "plugins": [
                    {"id": key, "version": selected[key].version}
                    for key in sorted(selected)
                ],
                "start_order": order,
                "capabilities": [value.__dict__ for value in resolved_capabilities],
                "dependencies": [
                    [consumer, provider]
                    for consumer, provider in sorted(
                        (consumer, provider)
                        for consumer, providers in dependencies.items()
                        for provider in providers
                    )
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return ResolvedExtensionGraph(
            plugin_ids=tuple(sorted(selected)),
            start_order=order,
            capabilities=resolved_capabilities,
            dependencies=tuple(
                sorted(
                    (consumer, provider)
                    for consumer, providers in dependencies.items()
                    for provider in providers
                )
            ),
            resolution_hash=f"sha256:{hashlib.sha256(encoded).hexdigest()}",
        )


_VERSION = re.compile(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?$")


def _version_tuple(version: str) -> tuple[int, int, int]:
    match = _VERSION.match(version.strip())
    if match is None:
        raise ValueError(f"invalid version {version!r}")
    return tuple(int(value or 0) for value in match.groups())  # type: ignore[return-value]


def _version_satisfies(version: str, requirement: str) -> bool:
    current = _version_tuple(version)
    for clause in [value.strip() for value in requirement.split(",") if value.strip()]:
        operator = next(
            (
                value
                for value in (">=", "<=", "==", ">", "<")
                if clause.startswith(value)
            ),
            None,
        )
        if operator is None:
            if current[0] != _version_tuple(clause)[0]:
                return False
            continue
        target = _version_tuple(clause[len(operator) :])
        if operator == ">=" and current < target:
            return False
        if operator == "<=" and current > target:
            return False
        if operator == ">" and current <= target:
            return False
        if operator == "<" and current >= target:
            return False
        if operator == "==" and current != target:
            return False
    return True


def _topological_order(
    plugin_ids: set[str], dependencies: Mapping[str, set[str]]
) -> tuple[str, ...]:
    temporary: set[str] = set()
    permanent: set[str] = set()
    result: list[str] = []

    def visit(plugin_id: str, trail: tuple[str, ...]) -> None:
        if plugin_id in permanent:
            return
        if plugin_id in temporary:
            raise _error(
                "extension.dependency_cycle",
                ErrorCategory.CONFLICT,
                "extension dependency cycle: " + " -> ".join((*trail, plugin_id)),
            )
        temporary.add(plugin_id)
        for dependency in sorted(dependencies.get(plugin_id, ())):
            if dependency in plugin_ids:
                visit(dependency, (*trail, plugin_id))
        temporary.remove(plugin_id)
        permanent.add(plugin_id)
        result.append(plugin_id)

    for plugin_id in sorted(plugin_ids):
        visit(plugin_id, ())
    return tuple(result)


def _error(code: str, category: ErrorCategory, message: str) -> SageV2Error:
    return SageV2Error(
        RuntimeErrorInfo(
            code=code,
            category=category,
            message=message,
            safe_to_resume=True,
        )
    )

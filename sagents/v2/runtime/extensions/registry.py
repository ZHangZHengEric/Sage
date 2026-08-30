"""Actual extension registrations and typed domain facades."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar, cast

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.runtime.extensions.contracts import ExtensionRegistration


class ExtensionRegistry:
    """Own factories, not merely UI metadata."""

    def __init__(self) -> None:
        self._registrations: dict[str, ExtensionRegistration] = {}

    def register(self, registration: ExtensionRegistration) -> None:
        plugin_id = registration.descriptor.plugin_id
        if plugin_id in self._registrations:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="extension.duplicate_id",
                    category=ErrorCategory.CONFLICT,
                    message=f"extension {plugin_id!r} is already registered",
                    safe_to_resume=True,
                )
            )
        self._registrations[plugin_id] = registration

    def get(self, plugin_id: str) -> ExtensionRegistration:
        try:
            return self._registrations[plugin_id]
        except KeyError as exc:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="extension.not_found",
                    category=ErrorCategory.VALIDATION,
                    message=f"extension {plugin_id!r} is not registered",
                    safe_to_resume=True,
                )
            ) from exc

    def contains(self, plugin_id: str) -> bool:
        return plugin_id in self._registrations

    def registrations(self) -> tuple[ExtensionRegistration, ...]:
        return tuple(self._registrations[key] for key in sorted(self._registrations))

    def inventory(self) -> tuple[dict, ...]:
        """Return truthful inventory derived from executable registrations."""

        return tuple(
            registration.descriptor.model_dump(mode="json")
            for registration in self.registrations()
        )


T = TypeVar("T")


@dataclass(frozen=True)
class TypedExtensionRegistry(Generic[T]):
    """Capability-specific view over the shared registry."""

    registry: ExtensionRegistry
    capability: str

    def register(self, registration: ExtensionRegistration[T]) -> None:
        if self.capability not in {
            offer.capability for offer in registration.descriptor.provides
        }:
            raise ValueError(
                f"extension {registration.descriptor.plugin_id!r} does not provide "
                f"{self.capability!r}"
            )
        self.registry.register(registration)

    def get(self, plugin_id: str) -> ExtensionRegistration[T]:
        registration = self.registry.get(plugin_id)
        if self.capability not in {
            offer.capability for offer in registration.descriptor.provides
        }:
            raise ValueError(
                f"extension {plugin_id!r} does not provide {self.capability!r}"
            )
        return cast(ExtensionRegistration[T], registration)

    def inventory(self) -> tuple[dict, ...]:
        return tuple(
            value
            for value in self.registry.inventory()
            if self.capability in {offer["capability"] for offer in value["provides"]}
        )

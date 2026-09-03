"""Actual extension registrations and typed domain facades."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Generic, TypeVar, cast

from pydantic import ConfigDict, create_model

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
        if registration.config_model is None:
            model_name = (
                "".join(
                    value.capitalize()
                    for value in plugin_id.replace("-", ".").split(".")
                )
                + "Config"
            )
            schema = registration.descriptor.config_schema or {
                "type": "object",
                "properties": {},
                "additionalProperties": True,
            }
            properties = dict(schema.get("properties") or {})
            required = set(schema.get("required") or ())
            fields = {
                name: (
                    _python_type(value),
                    ... if name in required else None,
                )
                for name, value in properties.items()
            }
            generated_model = create_model(
                model_name,
                __config__=ConfigDict(
                    extra=(
                        "forbid"
                        if schema.get("additionalProperties", True) is False
                        else "allow"
                    ),
                    arbitrary_types_allowed=True,
                ),
                **fields,
            )
            registration = replace(registration, config_model=generated_model)
        if registration.descriptor.config_schema is None:
            registration = replace(
                registration,
                descriptor=registration.descriptor.model_copy(
                    update={
                        "config_schema": registration.config_model.model_json_schema()
                    }
                ),
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


def _python_type(schema: dict[str, Any]) -> type[Any]:
    value = schema.get("type")
    types = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
        "null": type(None),
    }
    if isinstance(value, list):
        members = tuple(types.get(item, Any) for item in value)
        if not members or Any in members:
            return Any
        resolved = members[0]
        for member in members[1:]:
            resolved = resolved | member
        return resolved
    return types.get(value, Any)


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

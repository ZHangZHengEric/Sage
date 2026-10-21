"""Backend-neutral helpers for typed plugin registrations."""

from __future__ import annotations

import inspect

from sagents.v2.runtime.extensions.contracts import (
    CapabilityOffer,
    ExtensionAvailability,
    ExtensionDependency,
    ExtensionDescriptor,
    ExtensionRegistration,
    ExtensionScope,
    plugin_identity,
)
from sagents.v2.runtime.extensions.registry import ExtensionRegistry


def implementation_identity(implementation: type) -> dict[str, str]:
    plugin_id, name, description = plugin_identity(implementation)
    return {
        "plugin_id": plugin_id,
        "name": name,
        "description": description,
    }


def register_plugin(
    registry: ExtensionRegistry,
    implementation: type,
    capability: str,
    factory,
    *,
    scopes: set[ExtensionScope],
    dependencies: tuple[ExtensionDependency, ...] = (),
    provider_name: str = "default",
    multi_provider: bool = False,
    availability: ExtensionAvailability | None = None,
    config_schema: dict | None = None,
    capabilities: dict | None = None,
    api_version: str = "2",
    version: str = "2.0.0",
) -> None:
    if config_schema is not None:
        config_schema = _with_constructor_defaults(implementation, config_schema)
    registry.register(
        ExtensionRegistration(
            descriptor=ExtensionDescriptor(
                **implementation_identity(implementation),
                version=version,
                provides=(
                    CapabilityOffer(
                        capability=capability,
                        api_version=api_version,
                        name=provider_name,
                        multi_provider=multi_provider,
                    ),
                ),
                dependencies=dependencies,
                supported_scopes=frozenset(scopes),
                config_schema=(
                    config_schema
                    if config_schema is not None
                    else empty_config_schema()
                ),
                capabilities=capabilities or {},
                availability=availability or ExtensionAvailability(),
                built_in=True,
            ),
            factory=factory,
        )
    )


def _with_constructor_defaults(implementation: type, schema: dict) -> dict:
    """Publish scalar constructor defaults; explicit factory defaults win."""
    parameters = inspect.signature(implementation).parameters
    properties = {
        key: dict(value) for key, value in schema.get("properties", {}).items()
    }
    for key, field in properties.items():
        parameter = parameters.get(key)
        if parameter is None or "default" in field:
            continue
        value = parameter.default
        if isinstance(value, (str, int, float, bool)):
            field["default"] = value
    return {**schema, "properties": properties}


def empty_config_schema() -> dict:
    return {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }


def root_config_schema() -> dict:
    return {
        "type": "object",
        "properties": {"root": {"type": "string", "minLength": 1}},
        "required": ["root"],
        "additionalProperties": False,
    }


def service_registration(
    plugin, capability, factory, *, dependencies=(), config_model=None
):
    return ExtensionRegistration(
        descriptor=ExtensionDescriptor(
            plugin_id=plugin,
            name=capability,
            version="2.0.0",
            description=f"Standard {capability} implementation with declared dependencies and lifecycle.",
            provides=(CapabilityOffer(capability=capability, api_version="2"),),
            dependencies=tuple(
                ExtensionDependency(capability=key) for key in dependencies
            ),
            supported_scopes=frozenset({ExtensionScope.PROCESS}),
            config_schema=config_model.model_json_schema()
            if config_model
            else {
                "type": "object",
                "additionalProperties": False,
            },
            built_in=True,
        ),
        factory=factory,
        config_model=config_model,
    )

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
        self._trusted_builtin_ids: set[str] = set()

    def __deepcopy__(self, memo):
        # Freeze declarations, never clone a factory's captured host services.
        # Bound methods and callable objects retain their explicit ownership and
        # process identity across App registry snapshots.
        snapshot = type(self)()
        memo[id(self)] = snapshot
        snapshot._registrations = {
            key: replace(value, descriptor=value.descriptor.model_copy(deep=True))
            for key, value in self._registrations.items()
        }
        snapshot._trusted_builtin_ids = set(self._trusted_builtin_ids)
        return snapshot

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

    def validate_selection(self, capability: str, selection) -> None:
        """Reject invalid registration/offer/scope choices before creating resources."""
        if selection.grant_tools and capability != "tool.catalog":
            raise ValueError("grant_tools is supported only for a tool.catalog selection")
        from sagents.v2.runtime.extensions.versions import version_satisfies
        descriptor = self.get(selection.plugin).descriptor
        self.validate_parameters(selection.plugin, selection.config)
        offers = tuple(offer for offer in descriptor.provides if offer.capability == capability)
        if not offers or (selection.name != "default" and not any(
            offer.name == selection.name for offer in offers
        )) or (selection.name == "default" and len(offers) > 1 and not any(
            offer.name == "default" for offer in offers
        )):
            raise SageV2Error(RuntimeErrorInfo(
                code="extension.capability_missing", category=ErrorCategory.VALIDATION,
                message=f"extension {selection.plugin!r} does not provide {capability!r} named {selection.name!r}",
            ))
        selected = next((offer for offer in offers if offer.name == selection.name), offers[0])
        expected = "3" if capability == "execution.sandbox" else ">=2,<3"
        if not descriptor.availability.available or not version_satisfies(selected.api_version, expected):
            raise SageV2Error(RuntimeErrorInfo(
                code="extension.capability_unavailable", category=ErrorCategory.VALIDATION,
                message=f"extension {selection.plugin!r} is unavailable or has an incompatible {capability!r} protocol",
            ))
        if selection.scope is not None and selection.scope not in descriptor.supported_scopes:
            raise SageV2Error(RuntimeErrorInfo(
                code="extension.scope_unsupported", category=ErrorCategory.VALIDATION,
                message=f"extension {selection.plugin!r} does not support scope {selection.scope.value!r}",
            ))

    def validate_parameters(self, plugin_id, parameters) -> None:
        import json
        try:
            json.dumps(parameters, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise SageV2Error(RuntimeErrorInfo(code="extension.config_invalid", category=ErrorCategory.VALIDATION,
                message="plugin parameters must be finite JSON; register process objects through factories")) from exc
        if self.is_trusted_builtin(plugin_id):
            internal_ports = {"model", "store", "summarizer", "unit_compactor", "derived_state",
                              "session_store", "resolver", "runtime", "sandbox", "grant_issuer", "client"}
            if set(parameters) & internal_ports:
                raise SageV2Error(RuntimeErrorInfo(code="extension.config_invalid", category=ErrorCategory.VALIDATION,
                    message="SDK service objects are dependencies, not runtime configuration parameters"))

    def validate_runtime(self, runtime) -> None:
        """Validate capability identities and lifetimes before opening resources."""
        from .contracts import ExtensionScope
        process_ports = {
            "session.store", "derived-state.store", "credentials.provider",
            "execution.scheduler", "execution.job-runtime", "execution.binding", "execution.model-budget",
            "artifact.store", "package.registry", "agent.management", "workspace.initializer",
            "memory.provider", "session-memory.provider", "observability.log-sink",
            "observability.diagnostic-sink", "observability.trace-sink", "interface.protocol-adapter",
        }
        def scope(choice):
            return choice.scope or self.get(choice.plugin).descriptor.resolved_default_scope()
        for capability in runtime.capabilities:
            choices = runtime.selections(capability)
            if len({(choice.plugin, choice.name) for choice in choices}) != len(choices):
                raise ValueError(f"duplicate provider selection for {capability!r}")
            if capability != "tool.catalog" and len({choice.name for choice in choices}) != len(choices):
                raise ValueError(f"duplicate selections for {capability!r}")
            for choice in choices:
                self.validate_selection(capability, choice)
                if capability in process_ports and scope(choice) != ExtensionScope.PROCESS:
                    raise SageV2Error(RuntimeErrorInfo(code="extension.scope_unsupported", category=ErrorCategory.VALIDATION,
                        message=f"{capability!r} is an App process capability; select process scope"))
        for executor in runtime.selections("tool.executor"):
            paired = [catalog for catalog in runtime.selections("tool.catalog")
                      if catalog.plugin == executor.plugin and catalog.name == executor.name]
            if len(paired) != 1 or (executor.scope, executor.config) != (paired[0].scope, paired[0].config):
                raise ValueError("tool.executor must select the same registered pair, scope and parameters as tool.catalog")
        # Built-in adapters receive SDK-managed model/context ports. Apply the
        # same lifetime rule used by explicitly declared plugin dependencies.
        dependencies = {
            "sage.context.summarizer.model": ("model.provider",),
            "sage.agent.continuation.llm-judge": ("model.provider",),
            "sage.agent.continuation.hybrid": ("model.provider",),
            "sage.memory.recall-query.llm": ("model.provider",),
            "sage.context.reducer.persistent-summary": (
                "context.summary-store", "context.summarizer", "context.unit-compactor"),
        }
        rank = {value: index for index, value in enumerate(ExtensionScope)}
        for capability in runtime.capabilities:
            for consumer in runtime.selections(capability):
                if not self.is_trusted_builtin(consumer.plugin):
                    continue
                for dependency in dependencies.get(consumer.plugin, ()):
                    providers = runtime.selections(dependency)
                    provider_scope = scope(providers[0]) if providers else (
                        ExtensionScope.AGENT if dependency == "model.provider" else ExtensionScope.PROCESS)
                    if rank[provider_scope] > rank[scope(consumer)]:
                        raise SageV2Error(RuntimeErrorInfo(code="extension.invalid_scope_dependency", category=ErrorCategory.VALIDATION,
                            message=f"{consumer.plugin!r} at {scope(consumer).value!r} cannot capture {dependency!r} at {provider_scope.value!r}"))

    def trust_builtins(self, plugin_ids) -> None:
        """Record Host-owned built-ins independently from plugin self-reporting."""

        resolved = set(plugin_ids)
        invalid = sorted(
            plugin_id
            for plugin_id in resolved
            if plugin_id not in self._registrations
            or not self._registrations[plugin_id].descriptor.built_in
        )
        if invalid:
            raise ValueError(
                f"trusted built-ins must be registered and declared built-in: {invalid}"
            )
        self._trusted_builtin_ids.update(resolved)

    def is_trusted_builtin(self, plugin_id: str) -> bool:
        return plugin_id in self._trusted_builtin_ids

    def registrations(self) -> tuple[ExtensionRegistration, ...]:
        return tuple(self._registrations[key] for key in sorted(self._registrations))

    def inventory(self) -> tuple[dict, ...]:
        """Return truthful inventory derived from executable registrations."""

        return tuple(
            {
                **registration.descriptor.model_dump(mode="json"),
                "ownership": registration.ownership,
                # frozenset iteration changes with Python's hash seed. Inventory
                # participates in persisted composition identities and must be
                # canonical across worker processes and restarts.
                "supported_scopes": sorted(
                    scope.value for scope in registration.descriptor.supported_scopes
                ),
                "built_in": self.is_trusted_builtin(
                    registration.descriptor.plugin_id
                ),
            }
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

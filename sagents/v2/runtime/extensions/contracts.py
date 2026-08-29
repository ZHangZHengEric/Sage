"""Public contracts for installable SAgents v2 component implementations."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, Generic, Protocol, TypeVar

from pydantic import Field, model_validator

from sagents.v2.contracts.common import Identifier, StrictModel


class ExtensionScope(str, Enum):
    PROCESS = "process"
    TENANT = "tenant"
    AGENT = "agent"
    RUN = "run"


class StopReason(str, Enum):
    SCOPE_CLOSED = "scope_closed"
    START_FAILED = "start_failed"
    HOST_SHUTDOWN = "host_shutdown"
    RELOAD = "reload"


class CapabilityOffer(StrictModel):
    capability: Identifier
    api_version: str
    name: Identifier = "default"
    multi_provider: bool = False


class CapabilityRequirement(StrictModel):
    capability: Identifier
    api_version: str
    name: Identifier | None = None
    optional: bool = False


class ExtensionDependency(StrictModel):
    capability: Identifier
    api_version: str = ">=2,<3"
    name: Identifier | None = None
    optional: bool = False

    def requirement(self) -> CapabilityRequirement:
        return CapabilityRequirement(**self.model_dump())


class ExtensionAvailability(StrictModel):
    available: bool = True
    reason: str | None = None


class ExtensionDescriptor(StrictModel):
    """Serializable inventory plus dependency contract for one real factory."""

    plugin_id: Identifier
    version: str
    api_version: str = "2"
    name: str
    description: str = ""
    provides: tuple[CapabilityOffer, ...]
    dependencies: tuple[ExtensionDependency, ...] = ()
    supported_scopes: frozenset[ExtensionScope]
    config_schema: dict[str, Any] = Field(default_factory=dict)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    built_in: bool = False
    availability: ExtensionAvailability = Field(default_factory=ExtensionAvailability)

    @model_validator(mode="after")
    def validate_descriptor(self) -> "ExtensionDescriptor":
        if not self.provides:
            raise ValueError("an extension must provide at least one capability")
        keys = [(item.capability, item.name) for item in self.provides]
        if len(keys) != len(set(keys)):
            raise ValueError("provided capability keys must be unique")
        if not self.supported_scopes:
            raise ValueError("an extension must support at least one scope")
        return self


class ExtensionScopeContext(StrictModel):
    scope: ExtensionScope
    scope_id: Identifier
    tenant_id: Identifier | None = None
    agent_id: Identifier | None = None
    run_id: Identifier | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class ExtensionInstance(Protocol):
    async def start(
        self, context: ExtensionScopeContext, dependencies: Mapping[str, Any]
    ) -> Mapping[str, Any]: ...

    async def stop(self, reason: StopReason) -> None: ...


T = TypeVar("T")
ExtensionFactory = Callable[
    [ExtensionScopeContext, Mapping[str, Any]], T | Awaitable[T]
]
StartHook = Callable[
    [T, ExtensionScopeContext, Mapping[str, Any]],
    Mapping[str, Any] | Awaitable[Mapping[str, Any]],
]
StopHook = Callable[[T, StopReason], None | Awaitable[None]]


@dataclass(frozen=True)
class ExtensionRegistration(Generic[T]):
    """A descriptor coupled to the factory and lifecycle that make it real."""

    descriptor: ExtensionDescriptor
    factory: ExtensionFactory[T]
    start: StartHook[T] | None = None
    stop: StopHook[T] | None = None

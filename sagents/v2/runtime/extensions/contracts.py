"""Public contracts for installable SAgents v2 component implementations."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, Generic, Protocol, TypeVar

from pydantic import BaseModel, Field, model_validator

from sagents.v2.contracts.common import Identifier, StrictModel


class PluginIdentity(Protocol):
    """Stable host-visible identity declared by every selectable implementation."""

    plugin_id: ClassVar[str]
    name: ClassVar[str]
    description: ClassVar[str]


def plugin_identity(implementation: type[Any]) -> tuple[str, str, str]:
    """Read required identity attributes from one implementation class."""

    plugin_id = getattr(implementation, "plugin_id", None)
    name = getattr(implementation, "name", None)
    description = getattr(implementation, "description", None)
    missing = [
        field
        for field, value in (
            ("plugin_id", plugin_id),
            ("name", name),
            ("description", description),
        )
        if not isinstance(value, str) or not value.strip()
    ]
    if missing:
        raise TypeError(
            f"{implementation.__qualname__} must declare non-empty "
            f"{', '.join(missing)}"
        )
    return plugin_id, name, description


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


class CapabilityKey(StrictModel):
    """Unambiguous address for one provider exposed by an extension scope."""

    capability: Identifier
    name: Identifier = "default"

    def __str__(self) -> str:
        return f"{self.capability}:{self.name}"


class ProviderSet(Mapping[CapabilityKey, Any]):
    """Immutable typed provider view passed to extension factories and hooks."""

    def __init__(self, values: Mapping[CapabilityKey, Any] | None = None) -> None:
        self._values = dict(values or {})

    def __getitem__(self, key: CapabilityKey) -> Any:
        return self._values[key]

    def __iter__(self) -> Iterator[CapabilityKey]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def get_provider(self, capability: str, name: str = "default") -> Any | None:
        return self._values.get(CapabilityKey(capability=capability, name=name))

    def require(self, capability: str, name: str = "default") -> Any:
        key = CapabilityKey(capability=capability, name=name)
        try:
            return self._values[key]
        except KeyError as exc:
            raise KeyError(f"required provider {key} is unavailable") from exc

    def require_unique(self, capability: str) -> Any:
        """Return the sole named provider for a capability."""

        matches = [
            value for key, value in self._values.items() if key.capability == capability
        ]
        if len(matches) != 1:
            raise KeyError(
                f"expected one provider for {capability!r}, found {len(matches)}"
            )
        return matches[0]

    def merged(self, values: Mapping[CapabilityKey, Any]) -> "ProviderSet":
        return ProviderSet({**self._values, **values})

    def as_dict(self) -> dict[CapabilityKey, Any]:
        return dict(self._values)


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
    default_scope: ExtensionScope | None = None
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
        if self.default_scope is not None and self.default_scope not in self.supported_scopes:
            raise ValueError("default_scope must be included in supported_scopes")
        return self

    def resolved_default_scope(self) -> ExtensionScope:
        if self.default_scope is not None:
            return self.default_scope
        order = {
            ExtensionScope.PROCESS: 0,
            ExtensionScope.TENANT: 1,
            ExtensionScope.AGENT: 2,
            ExtensionScope.RUN: 3,
        }
        return min(self.supported_scopes, key=order.__getitem__)


class ExtensionScopeContext(StrictModel):
    scope: ExtensionScope
    scope_id: Identifier
    tenant_id: Identifier | None = None
    agent_id: Identifier | None = None
    run_id: Identifier | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class ExtensionInstance(Protocol):
    async def start(
        self, context: ExtensionScopeContext, dependencies: ProviderSet
    ) -> Mapping[CapabilityKey, Any]: ...

    async def stop(self, reason: StopReason) -> None: ...


T = TypeVar("T")
ExtensionFactory = Callable[
    [ExtensionScopeContext, ProviderSet], T | Awaitable[T]
]
StartHook = Callable[
    [T, ExtensionScopeContext, ProviderSet],
    Mapping[CapabilityKey, Any] | Awaitable[Mapping[CapabilityKey, Any]],
]
StopHook = Callable[[T, StopReason], None | Awaitable[None]]


@dataclass(frozen=True)
class ExtensionRegistration(Generic[T]):
    """A descriptor coupled to the factory and lifecycle that make it real."""

    descriptor: ExtensionDescriptor
    factory: ExtensionFactory[T]
    start: StartHook[T] | None = None
    stop: StopHook[T] | None = None
    config_model: type[BaseModel] | None = None

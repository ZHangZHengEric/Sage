"""SAgents V2 module for runtime/extensions/__init__.py."""

from sagents.v2.runtime.extensions.contracts import (
    CapabilityOffer,
    CapabilityRequirement,
    ExtensionDependency,
    ExtensionDescriptor,
    ExtensionAvailability,
    ExtensionRegistration,
    ExtensionScope,
    ExtensionScopeContext,
    StopReason,
)
from sagents.v2.runtime.extensions.host import (
    ExtensionHost,
)
from sagents.v2.runtime.extensions.registry import (
    ExtensionRegistry,
    TypedExtensionRegistry,
)
from sagents.v2.runtime.extensions.resolver import (
    ExtensionResolver,
    ResolvedExtensionGraph,
)
from sagents.v2.runtime.extensions.scope import ExtensionScopeHandle

__all__ = [
    "CapabilityOffer",
    "CapabilityRequirement",
    "ExtensionDependency",
    "ExtensionDescriptor",
    "ExtensionAvailability",
    "ExtensionHost",
    "ExtensionRegistration",
    "ExtensionRegistry",
    "ExtensionResolver",
    "ExtensionScope",
    "ExtensionScopeContext",
    "ExtensionScopeHandle",
    "ResolvedExtensionGraph",
    "StopReason",
    "TypedExtensionRegistry",
]

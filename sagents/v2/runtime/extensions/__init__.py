"""SAgents V2 module for runtime/extensions/__init__.py."""

from sagents.v2.runtime.extensions.contracts import (
    CapabilityKey,
    CapabilityName,
    CapabilityOffer,
    CapabilityRequirement,
    ExtensionDependency,
    ExtensionDescriptor,
    ExtensionAvailability,
    ExtensionRegistration,
    ExtensionScope,
    ExtensionScopeContext,
    PluginIdentity,
    ProviderSet,
    StopReason,
    plugin_identity,
)
from sagents.v2.runtime.extensions.capability_contracts import capability_contract_inventory
from sagents.v2.runtime.extensions.host import (
    ExtensionCompositionPlan,
    ExtensionHost,
)
from sagents.v2.runtime.extensions.discovery import (
    ENTRY_POINT_GROUP,
    load_installed_extension,
    validate_extension_version,
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
    "CapabilityKey",
    "CapabilityName",
    "capability_contract_inventory",
    "CapabilityRequirement",
    "ExtensionDependency",
    "ExtensionDescriptor",
    "ExtensionAvailability",
    "ENTRY_POINT_GROUP",
    "ExtensionHost",
    "ExtensionCompositionPlan",
    "ExtensionRegistration",
    "ExtensionRegistry",
    "ExtensionResolver",
    "ExtensionScope",
    "ExtensionScopeContext",
    "ExtensionScopeHandle",
    "PluginIdentity",
    "ResolvedExtensionGraph",
    "ProviderSet",
    "plugin_identity",
    "StopReason",
    "TypedExtensionRegistry",
    "load_installed_extension",
    "validate_extension_version",
]

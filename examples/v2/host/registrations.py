"""Small example registration constructors; selection and build remain explicit."""
from sagents.v2.runtime.extensions import (
    CapabilityKey, CapabilityOffer, ExtensionDescriptor, ExtensionRegistration,
    ExtensionScope,
)


def provided(plugin_id, factory, *capabilities, scope=ExtensionScope.PROCESS, ownership="borrowed"):
    """Register a capability factory, including already-created host resources."""
    return ExtensionRegistration(
        descriptor=ExtensionDescriptor(plugin_id=plugin_id, name=plugin_id, version="1",
            provides=tuple(CapabilityOffer(capability=name, api_version="2") for name in capabilities),
            supported_scopes=frozenset({scope}), default_scope=scope,
            config_schema={"type": "object", "additionalProperties": False}),
        factory=factory, ownership=ownership,
        start=(lambda instance, context, deps: {
            CapabilityKey(capability=name): getattr(instance, "catalog" if name == "tool.catalog" else "executor", instance)
            if name.startswith("tool.") else instance for name in capabilities
        }) if len(capabilities) > 1 else None,
    )


def runtime_for(root, runtime=None, *, capabilities=None):
    """Serializable example choices; no factories or process objects in config."""
    from sagents.v2.package.manifest.runtime import RuntimeConfig, CapabilitySelection
    selected = RuntimeConfig.model_validate(runtime or {})
    return selected.model_copy(update={"state_root": str(root), "capabilities": {
        "session.store": CapabilitySelection(plugin="sage.session.filesystem", config={"root": str(root)}),
        **selected.capabilities, **{name: CapabilitySelection.model_validate(value) for name, value in (capabilities or {}).items()},
    }})

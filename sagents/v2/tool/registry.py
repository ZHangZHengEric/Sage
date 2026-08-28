"""Typed facade for plugins that provide both Tool catalog and executor."""

from sagents.v2.runtime.extensions import ExtensionRegistration, ExtensionRegistry


class ToolProviderRegistry:
    def __init__(self, registry: ExtensionRegistry | None = None) -> None:
        self.registry = registry or ExtensionRegistry()

    def register(self, registration: ExtensionRegistration) -> None:
        capabilities = {value.capability for value in registration.descriptor.provides}
        if not {"tool.catalog", "tool.executor"} <= capabilities:
            raise ValueError("Tool plugins must provide catalog and executor together")
        self.registry.register(registration)

    def get(self, plugin_id: str) -> ExtensionRegistration:
        registration = self.registry.get(plugin_id)
        capabilities = {value.capability for value in registration.descriptor.provides}
        if not {"tool.catalog", "tool.executor"} <= capabilities:
            raise ValueError(f"extension {plugin_id!r} is not a Tool provider")
        return registration

    def inventory(self) -> tuple[dict, ...]:
        return tuple(
            value
            for value in self.registry.inventory()
            if {"tool.catalog", "tool.executor"}
            <= {offer["capability"] for offer in value["provides"]}
        )

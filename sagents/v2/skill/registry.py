"""Typed facade for complete Skill provider plugins."""

from sagents.v2.runtime.extensions import ExtensionRegistration, ExtensionRegistry


class SkillProviderRegistry:
    def __init__(self, registry: ExtensionRegistry | None = None) -> None:
        self.registry = registry or ExtensionRegistry()

    def register(self, registration: ExtensionRegistration) -> None:
        capabilities = {value.capability for value in registration.descriptor.provides}
        if not {"skill.provider"} <= capabilities:
            raise ValueError("Skill plugins must provide skill.provider")
        self.registry.register(registration)

    def get(self, plugin_id: str) -> ExtensionRegistration:
        registration = self.registry.get(plugin_id)
        capabilities = {value.capability for value in registration.descriptor.provides}
        if not {"skill.provider"} <= capabilities:
            raise ValueError(f"extension {plugin_id!r} is not a Skill provider")
        return registration

    def inventory(self) -> tuple[dict, ...]:
        return tuple(
            value
            for value in self.registry.inventory()
            if {"skill.provider"}
            <= {offer["capability"] for offer in value["provides"]}
        )

"""Root Sage manifest contract."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, PrivateAttr, field_validator, model_validator, model_serializer

from sagents.v2.contracts.common import Identifier, StrictModel
from sagents.v2.package.manifest.agents import AgentDefinition, ApplicationEntrypoint
from sagents.v2.package.manifest.flows import FlowDefinition
from sagents.v2.package.manifest.runtime import PolicyConfig, RuntimeConfig
from sagents.v2.runtime.extensions.contracts import ExtensionScope


class ManifestMetadata(StrictModel):
    id: Identifier
    version: str
    name: str
    description: str | None = None


class PluginDeclaration(StrictModel):
    id: Identifier
    version: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def retire_skill_estimate_limit(cls, value):
        if isinstance(value, dict) and value.get("id") == "sage.skill.loading.lazy":
            config = value.get("config")
            if isinstance(config, dict) and "max_active_tokens" in config:
                return {
                    **value,
                    "config": {
                        k: v for k, v in config.items() if k != "max_active_tokens"
                    },
                }
        return value


class InterfaceDeclaration(StrictModel):
    plugin: Identifier
    name: Identifier | None = None
    enabled: bool = True
    scope: ExtensionScope | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class TestDeclaration(StrictModel):
    scenarios: tuple[dict[str, Any], ...] = ()
    gates: dict[str, Any] = Field(default_factory=dict)


class SageManifest(StrictModel):
    # Not configuration: only whole-manifest archives retain historical hash inputs.
    _legacy_budget_values: dict = PrivateAttr(default_factory=dict)
    schema_version: Literal["sage/v2"] = "sage/v2"
    kind: Literal["application", "agent-package"] = "agent-package"
    metadata: ManifestMetadata
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    plugins: tuple[PluginDeclaration, ...] = ()
    policies: PolicyConfig = Field(default_factory=PolicyConfig)
    agents: dict[Identifier, AgentDefinition] = Field(default_factory=dict)
    flows: dict[Identifier, FlowDefinition] = Field(default_factory=dict)
    entrypoint: ApplicationEntrypoint
    interfaces: dict[Identifier, InterfaceDeclaration] = Field(default_factory=dict)
    tests: TestDeclaration = Field(default_factory=TestDeclaration)
    environments: dict[Identifier, dict[str, Any]] = Field(default_factory=dict)

    @model_validator(mode="wrap")
    @classmethod
    def preserve_legacy_budget_identity(cls, value, handler):
        from sagents.v2.package.manifest.legacy_budgets import legacy_budget_values

        manifest = handler(value)
        if isinstance(value, dict):
            manifest._legacy_budget_values = legacy_budget_values(value)
        return manifest

    @model_serializer(mode="wrap")
    def serialize_legacy_budget_identity(self, handler):
        from sagents.v2.package.manifest.legacy_budgets import restore_legacy_budget_values

        return restore_legacy_budget_values(handler(self), self._legacy_budget_values)

    @field_validator("plugins", mode="before")
    @classmethod
    def retire_estimator_plugins(cls, value):
        if not isinstance(value, (tuple, list)):
            return value

        def retired(plugin):
            identifier = (
                plugin.get("id")
                if isinstance(plugin, dict)
                else getattr(plugin, "id", None)
            )
            return isinstance(identifier, str) and identifier.startswith(
                "sage.context.token-estimator."
            )

        return tuple(plugin for plugin in value if not retired(plugin))

    @model_validator(mode="after")
    def validate_unique_plugin_declarations(self) -> "SageManifest":
        plugin_ids = [plugin.id for plugin in self.plugins]
        if len(plugin_ids) != len(set(plugin_ids)):
            raise ValueError("plugin declarations must have unique ids")
        return self

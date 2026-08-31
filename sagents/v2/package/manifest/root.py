"""Root Sage manifest contract."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from sagents.v2.contracts.common import Identifier, StrictModel
from sagents.v2.package.manifest.agents import AgentDefinition, ApplicationEntrypoint
from sagents.v2.package.manifest.credentials import CredentialDeclaration
from sagents.v2.package.manifest.flows import FlowDefinition
from sagents.v2.package.manifest.models import ModelRoute
from sagents.v2.package.manifest.runtime import PolicyConfig, RuntimeConfig
from sagents.v2.runtime.extensions.contracts import ExtensionScope


class ManifestMetadata(StrictModel):
    id: Identifier
    version: str
    name: str
    description: str | None = None


class PluginDeclaration(StrictModel):
    id: Identifier
    config: dict[str, Any] = Field(default_factory=dict)


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
    schema_version: Literal["sage/v2"] = "sage/v2"
    kind: Literal["application", "agent-package"] = "agent-package"
    metadata: ManifestMetadata
    credentials: dict[Identifier, CredentialDeclaration] = Field(default_factory=dict)
    models: dict[Identifier, ModelRoute] = Field(default_factory=dict)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    plugins: tuple[PluginDeclaration, ...] = ()
    policies: PolicyConfig = Field(default_factory=PolicyConfig)
    agents: dict[Identifier, AgentDefinition] = Field(default_factory=dict)
    flows: dict[Identifier, FlowDefinition] = Field(default_factory=dict)
    entrypoint: ApplicationEntrypoint
    interfaces: dict[Identifier, InterfaceDeclaration] = Field(default_factory=dict)
    tests: TestDeclaration = Field(default_factory=TestDeclaration)
    environments: dict[Identifier, dict[str, Any]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_unique_plugin_declarations(self) -> "SageManifest":
        plugin_ids = [plugin.id for plugin in self.plugins]
        if len(plugin_ids) != len(set(plugin_ids)):
            raise ValueError("plugin declarations must have unique ids")
        return self

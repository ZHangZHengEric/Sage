"""Official environment and host-injected credential registrations."""

from __future__ import annotations

from sagents.v2.package.manifest.credentials import CredentialDeclaration
from sagents.v2.runtime.credentials import (
    EnvironmentCredentialProvider,
    MappingCredentialProvider,
)
from sagents.v2.runtime.extensions.contracts import ExtensionScope
from sagents.v2.runtime.extensions.registration import register_plugin
from sagents.v2.runtime.extensions.registry import ExtensionRegistry


def register_credential_plugins(registry: ExtensionRegistry) -> None:
    register_plugin(
        registry,
        EnvironmentCredentialProvider,
        "credentials.provider",
        lambda context, dependencies: EnvironmentCredentialProvider(
            {
                key: CredentialDeclaration.model_validate(value)
                for key, value in context.config.get("declarations", {}).items()
            },
            context.config.get("environment"),
        ),
        scopes={ExtensionScope.PROCESS, ExtensionScope.TENANT},
        config_schema={
            "type": "object",
            "properties": {
                "declarations": {"type": "object"},
                "environment": {"type": ["object", "null"]},
            },
            "additionalProperties": False,
        },
    )

    register_plugin(
        registry,
        MappingCredentialProvider,
        "credentials.provider",
        lambda context, dependencies: MappingCredentialProvider(
            context.config.get("values", {}),
            source=str(context.config.get("source", "host")),
        ),
        scopes={ExtensionScope.PROCESS, ExtensionScope.TENANT},
        config_schema={
            "type": "object",
            "properties": {
                "values": {"type": "object"},
                "source": {"type": "string", "minLength": 1},
            },
            "additionalProperties": False,
        },
    )

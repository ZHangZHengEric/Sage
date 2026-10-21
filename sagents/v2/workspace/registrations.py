"""Official workspace initializer registrations."""

from __future__ import annotations

from sagents.v2.runtime.extensions.contracts import ExtensionScope
from sagents.v2.runtime.extensions.registration import register_plugin
from sagents.v2.runtime.extensions.registry import ExtensionRegistry
from sagents.v2.workspace import BareWorkspaceInitializer, ClawWorkspaceInitializer


def register_workspace_plugins(registry: ExtensionRegistry) -> None:
    register_plugin(
        registry,
        ClawWorkspaceInitializer,
        "workspace.initializer",
        lambda context, dependencies: ClawWorkspaceInitializer(
            language=str(context.config.get("language", "en"))
        ),
        scopes={ExtensionScope.PROCESS, ExtensionScope.AGENT},
        config_schema={
            "type": "object",
            "properties": {"language": {"type": "string", "minLength": 1}},
            "additionalProperties": False,
        },
    )

    register_plugin(
        registry,
        BareWorkspaceInitializer,
        "workspace.initializer",
        lambda context, dependencies: BareWorkspaceInitializer(),
        scopes={ExtensionScope.PROCESS, ExtensionScope.AGENT},
    )

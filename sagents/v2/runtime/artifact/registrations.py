"""Official standalone ArtifactStore registrations."""

from __future__ import annotations

from sagents.v2.runtime.artifact import FilesystemArtifactStore, InMemoryArtifactStore
from sagents.v2.runtime.extensions.contracts import ExtensionScope
from sagents.v2.runtime.extensions.registration import register_plugin
from sagents.v2.runtime.extensions.registry import ExtensionRegistry


def register_artifact_plugins(registry: ExtensionRegistry) -> None:
    register_plugin(
        registry,
        InMemoryArtifactStore,
        "artifact.store",
        lambda context, dependencies: InMemoryArtifactStore(),
        scopes={ExtensionScope.PROCESS, ExtensionScope.RUN},
        capabilities={
            "durable_across_process_restart": False,
            "shared_across_processes": False,
        },
    )

    register_plugin(
        registry,
        FilesystemArtifactStore,
        "artifact.store",
        lambda context, dependencies: FilesystemArtifactStore(context.config["root"]),
        scopes={ExtensionScope.PROCESS},
        config_schema={
            "type": "object",
            "required": ["root"],
            "properties": {"root": {"type": "string", "minLength": 1}},
            "additionalProperties": False,
        },
        capabilities={
            "durable_across_process_restart": True,
            "shared_across_processes": True,
        },
    )

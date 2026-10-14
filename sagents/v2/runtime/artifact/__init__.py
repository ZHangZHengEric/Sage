"""Artifact references and storage contracts."""

from sagents.v2._lazy import exported_names, resolve_export

_EXPORTS = {
    "ArtifactRef": ("sagents.v2.runtime.artifact.contracts", "ArtifactRef"),
    "ArtifactStore": ("sagents.v2.runtime.artifact.contracts", "ArtifactStore"),
    "InMemoryArtifactStore": ("sagents.v2.runtime.artifact.plugins.ephemeral", "InMemoryArtifactStore"),
    "SqliteArtifactStore": ("sagents.v2.runtime.artifact.plugins.sqlite", "SqliteArtifactStore"),
    "ScopedArtifactStore": ("sagents.v2.runtime.artifact.scoped", "ScopedArtifactStore"),
}
__all__ = list(_EXPORTS)


def __getattr__(name):
    return resolve_export(name, _EXPORTS, globals())


def __dir__():
    return exported_names(_EXPORTS, globals())

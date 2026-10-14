"""Artifact references and storage contracts."""

from sagents.v2._lazy import exported_names, resolve_export

_EXPORTS = {
    "SessionArtifactStore": (
        "sagents.v2.runtime.artifact.session",
        "SessionArtifactStore",
    ),
    "ArtifactRef": ("sagents.v2.runtime.artifact.contracts", "ArtifactRef"),
    "ArtifactStore": ("sagents.v2.runtime.artifact.contracts", "ArtifactStore"),
    "InMemoryArtifactStore": (
        "sagents.v2.runtime.artifact.plugins.ephemeral",
        "InMemoryArtifactStore",
    ),
    "FilesystemArtifactStore": (
        "sagents.v2.runtime.artifact.plugins.filesystem",
        "FilesystemArtifactStore",
    ),
    "ScopedArtifactStore": (
        "sagents.v2.runtime.artifact.scoped",
        "ScopedArtifactStore",
    ),
}
__all__ = list(_EXPORTS)


def __getattr__(name):
    return resolve_export(name, _EXPORTS, globals())


def __dir__():
    return exported_names(_EXPORTS, globals())

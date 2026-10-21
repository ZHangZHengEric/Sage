"""Artifact references and storage contracts."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sagents.v2.runtime.artifact.plugins.session import SessionArtifactStore as SessionArtifactStore
    from sagents.v2.runtime.artifact.contracts import ArtifactRef as ArtifactRef
    from sagents.v2.runtime.artifact.contracts import ArtifactStore as ArtifactStore
    from sagents.v2.runtime.artifact.plugins.ephemeral import InMemoryArtifactStore as InMemoryArtifactStore
    from sagents.v2.runtime.artifact.plugins.filesystem import FilesystemArtifactStore as FilesystemArtifactStore
    from sagents.v2.runtime.artifact.scoped import ScopedArtifactStore as ScopedArtifactStore


from sagents.v2._lazy import exported_names, resolve_export

_EXPORTS = {
    "SessionArtifactStore": (
        "sagents.v2.runtime.artifact.plugins.session",
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
__all__ = [
    "SessionArtifactStore",
    "ArtifactRef",
    "ArtifactStore",
    "InMemoryArtifactStore",
    "FilesystemArtifactStore",
    "ScopedArtifactStore",
]


def __getattr__(name):
    return resolve_export(name, _EXPORTS, globals())


def __dir__():
    return exported_names(_EXPORTS, globals())

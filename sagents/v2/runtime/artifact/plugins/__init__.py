"""Official ArtifactStore backends."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sagents.v2.runtime.artifact.plugins.ephemeral import InMemoryArtifactStore as InMemoryArtifactStore
    from sagents.v2.runtime.artifact.plugins.filesystem import FilesystemArtifactStore as FilesystemArtifactStore


from sagents.v2._lazy import exported_names, resolve_export

_EXPORTS = {
    "InMemoryArtifactStore": ("sagents.v2.runtime.artifact.plugins.ephemeral", "InMemoryArtifactStore"),
    "FilesystemArtifactStore": ("sagents.v2.runtime.artifact.plugins.filesystem", "FilesystemArtifactStore"),
}
__all__ = [
    "InMemoryArtifactStore",
    "FilesystemArtifactStore",
]


def __getattr__(name):
    return resolve_export(name, _EXPORTS, globals())


def __dir__():
    return exported_names(_EXPORTS, globals())

"""Capability publication for Session storage plugins."""

from sagents.v2.runtime.artifact.plugins.session import SessionArtifactStore


SESSION_STORAGE_CAPABILITIES = ("session.store", "derived-state.store", "artifact.store")


def session_storage_providers(store):
    return {
        "session.store": store,
        "derived-state.store": store,
        "artifact.store": SessionArtifactStore(store),
    }

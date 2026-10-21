"""Bind identities without changing the configured artifact implementation."""

from sagents.v2.runtime.artifact.scoped import ScopedArtifactStore
from sagents.v2.runtime.artifact import SessionArtifactStore


def bind_artifact_store(store, run_id):
    if isinstance(store, SessionArtifactStore):
        return store.for_run(run_id)
    return ScopedArtifactStore(store, run_id)

"""Host-selected namespaces prevent cross-tenant artifact lookup."""

import hashlib

from sagents.v2.runtime.artifact.contracts import ArtifactStore


class ScopedArtifactStore:
    def __init__(self, store: ArtifactStore, namespace: str):
        self.store = store
        self.prefix = hashlib.sha256(namespace.encode()).hexdigest() + ":"

    async def put(self, *, artifact_id, media_type, content, metadata=None):
        reference = await self.store.put(
            artifact_id=self.prefix + artifact_id,
            media_type=media_type,
            content=content,
            metadata=metadata,
        )
        return reference.model_copy(update={"artifact_id": artifact_id})

    async def get(self, artifact_id):
        reference, content = await self.store.get(self.prefix + artifact_id)
        return reference.model_copy(update={"artifact_id": artifact_id}), content

    async def delete(self, artifact_id):
        return await self.store.delete(self.prefix + artifact_id)

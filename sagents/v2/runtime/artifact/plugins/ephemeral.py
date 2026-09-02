"""In-memory ArtifactStore for tests and embedded processes."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator
from typing import Any

from sagents.v2.runtime.artifact.contracts import ArtifactRef


class InMemoryArtifactStore:
    plugin_id = "sage.artifact.ephemeral"
    name = "In-memory ArtifactStore"
    description = "Process-local artifact bytes without restart durability."

    def __init__(self) -> None:
        self._values: dict[str, tuple[ArtifactRef, bytes]] = {}
        self._lock = asyncio.Lock()

    async def put(
        self,
        *,
        artifact_id: str,
        content: AsyncIterator[bytes],
        media_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactRef:
        payload = b"".join([chunk async for chunk in content])
        reference = ArtifactRef(
            artifact_id=artifact_id,
            media_type=media_type,
            size_bytes=len(payload),
            digest=f"sha256:{hashlib.sha256(payload).hexdigest()}",
            metadata=dict(metadata or {}),
        )
        async with self._lock:
            self._values[artifact_id] = (reference, payload)
        return reference

    async def get(self, artifact_id: str) -> tuple[ArtifactRef, AsyncIterator[bytes]]:
        async with self._lock:
            reference, payload = self._values[artifact_id]

        async def stream() -> AsyncIterator[bytes]:
            yield payload

        return reference, stream()

    async def delete(self, artifact_id: str) -> bool:
        async with self._lock:
            return self._values.pop(artifact_id, None) is not None

"""Artifact references and storage contracts.

Artifacts are addressed outputs, not Session persistence. The interface stays
small in this refactor so hosts can supply local, object-store, or remote
implementations without coupling the Kernel to one storage protocol.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator
from typing import Any, Protocol

from pydantic import Field

from sagents.v2.contracts.common import StrictModel


class ArtifactRef(StrictModel):
    artifact_id: str
    media_type: str
    size_bytes: int = Field(ge=0)
    uri: str | None = None
    digest: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ArtifactStore(Protocol):
    """Backend-neutral immutable artifact port selected by the host."""

    async def put(
        self,
        *,
        artifact_id: str,
        media_type: str,
        content: AsyncIterator[bytes],
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactRef: ...

    async def get(
        self, artifact_id: str
    ) -> tuple[ArtifactRef, AsyncIterator[bytes]]: ...

    async def delete(self, artifact_id: str) -> bool: ...


class InMemoryArtifactStore:
    """Reference ArtifactStore for tests and embedded processes."""

    def __init__(self) -> None:
        self._values: dict[str, tuple[ArtifactRef, bytes]] = {}
        self._lock = asyncio.Lock()

    async def put(
        self,
        *,
        artifact_id: str,
        media_type: str,
        content: AsyncIterator[bytes],
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


__all__ = ["ArtifactRef", "ArtifactStore", "InMemoryArtifactStore"]

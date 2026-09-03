"""In-memory ArtifactStore for tests and embedded processes."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator
from copy import deepcopy
from typing import Any

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.runtime.artifact.contracts import ArtifactRef


class InMemoryArtifactStore:
    plugin_id = "sage.artifact.ephemeral"
    name = "In-memory ArtifactStore"
    description = "Process-local artifact bytes without restart durability."

    @property
    def capabilities(self) -> dict[str, bool]:
        return {
            "durable_across_process_restart": False,
            "shared_across_processes": False,
        }

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
            metadata=deepcopy(metadata or {}),
        )
        async with self._lock:
            existing = self._values.get(artifact_id)
            if existing is not None:
                if existing == (reference, payload):
                    return existing[0].model_copy(deep=True)
                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="artifact.id_conflict",
                        category=ErrorCategory.CONFLICT,
                        message=(
                            f"immutable artifact {artifact_id!r} already exists with "
                            "different content or metadata"
                        ),
                        safe_to_resume=True,
                    )
                )
            self._values[artifact_id] = (reference.model_copy(deep=True), payload)
        return reference.model_copy(deep=True)

    async def get(self, artifact_id: str) -> tuple[ArtifactRef, AsyncIterator[bytes]]:
        async with self._lock:
            try:
                reference, payload = self._values[artifact_id]
            except KeyError as exc:
                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="artifact.not_found",
                        category=ErrorCategory.VALIDATION,
                        message=f"artifact {artifact_id!r} was not found",
                        safe_to_resume=True,
                    )
                ) from exc

        async def stream() -> AsyncIterator[bytes]:
            yield payload

        return reference.model_copy(deep=True), stream()

    async def delete(self, artifact_id: str) -> bool:
        async with self._lock:
            return self._values.pop(artifact_id, None) is not None

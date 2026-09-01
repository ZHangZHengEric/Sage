"""Artifact references and storage contracts.

Artifacts are addressed outputs, not Session persistence.
"""

from __future__ import annotations

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

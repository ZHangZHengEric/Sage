"""Backend-neutral long-term Memory contracts for SAgents v2."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import Field

from sagents.v2.contracts.common import StrictModel


class MemoryScope(StrictModel):
    """Isolation boundary supplied to a Memory provider on every operation."""

    tenant_id: str | None = None
    principal_id: str
    agent_id: str | None = None
    session_id: str | None = None


class MemoryRecord(StrictModel):
    memory_id: str
    scope: MemoryScope
    content: str
    kind: str = "fact"
    source: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class MemoryQuery(StrictModel):
    scope: MemoryScope
    text: str
    limit: int = Field(default=8, gt=0, le=100)
    kinds: tuple[str, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryHit(StrictModel):
    record: MemoryRecord
    score: float = Field(ge=0)
    reason: str | None = None


class MemoryWriteResult(StrictModel):
    memory_id: str
    created: bool


class MemoryDeleteResult(StrictModel):
    memory_id: str
    deleted: bool


class MemoryCapabilities(StrictModel):
    api_version: Literal["2"] = "2"
    durable: bool
    supports_filtering: bool = False
    supports_delete: bool = True


class MemoryProvider(Protocol):
    """The only backend contract required from a third-party Memory plugin."""

    async def capabilities(self) -> MemoryCapabilities: ...
    async def recall(self, query: MemoryQuery) -> tuple[MemoryHit, ...]: ...
    async def remember(self, record: MemoryRecord) -> MemoryWriteResult: ...
    async def forget(
        self, memory_id: str, *, scope: MemoryScope
    ) -> MemoryDeleteResult: ...
    async def get(
        self, memory_id: str, *, scope: MemoryScope
    ) -> MemoryRecord | None: ...
    async def health(self) -> dict[str, Any]: ...

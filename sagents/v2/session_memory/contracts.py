"""Provider-neutral contracts for searchable Session history."""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import Field

from sagents.v2.contracts.common import StrictModel


class SessionMemoryRecord(StrictModel):
    record_id: str
    session_id: str
    role: str
    content: str
    position: int = Field(ge=0)
    source: dict[str, Any] = Field(default_factory=dict)


class SessionMemoryQuery(StrictModel):
    session_id: str
    run_id: str
    text: str
    limit: int = Field(default=5, gt=0, le=100)
    included_record_ids: tuple[str, ...] = ()
    excluded_record_ids: tuple[str, ...] = ()


class SessionMemoryHit(StrictModel):
    record: SessionMemoryRecord
    score: float = Field(ge=0)
    reason: str = "bm25"


class SessionMemoryCapabilities(StrictModel):
    api_version: Literal["2"] = "2"
    durable: bool
    incremental_index: bool = True


class SessionMemoryProvider(Protocol):
    """Replaceable derived index; canonical history remains in SessionStore."""

    async def capabilities(self) -> SessionMemoryCapabilities: ...

    async def sync(self, records: tuple[SessionMemoryRecord, ...]) -> None: ...

    async def recall(
        self, query: SessionMemoryQuery
    ) -> tuple[SessionMemoryHit, ...]: ...

    async def forget_session(self, session_id: str) -> None: ...

    async def health(self) -> dict[str, Any]: ...

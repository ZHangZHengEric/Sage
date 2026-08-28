"""Stable Memory coordination and post-commit ingestion policies."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from sagents.v2.contracts.common import utc_now
from sagents.v2.contracts.events import ItemEventData, RuntimeEvent
from sagents.v2.contracts.items import MessageItemData, TextBlock
from sagents.v2.contracts.principals import RequestContext
from sagents.v2.contracts.run_state import RunSnapshot, RunState
from sagents.v2.memory.contracts import (
    MemoryDeleteResult,
    MemoryHit,
    MemoryProvider,
    MemoryQuery,
    MemoryRecord,
    MemoryScope,
    MemoryWriteResult,
)


class MemoryIngestionPolicy(Protocol):
    async def should_ingest(
        self, run: RunSnapshot, events: tuple[RuntimeEvent, ...]
    ) -> bool: ...


class MemoryExtractor(Protocol):
    async def extract(
        self,
        run: RunSnapshot,
        events: tuple[RuntimeEvent, ...],
        scope: MemoryScope,
    ) -> tuple[MemoryRecord, ...]: ...


class CompletedRunMemoryPolicy:
    async def should_ingest(
        self, run: RunSnapshot, events: tuple[RuntimeEvent, ...]
    ) -> bool:
        return run.state == RunState.COMPLETED


class CanonicalMessageMemoryExtractor:
    """Conservative default extractor over canonical completed messages."""

    async def extract(
        self,
        run: RunSnapshot,
        events: tuple[RuntimeEvent, ...],
        scope: MemoryScope,
    ) -> tuple[MemoryRecord, ...]:
        records = []
        for event in events:
            if event.type != "message.completed" or not isinstance(
                event.data, ItemEventData
            ):
                continue
            item = event.data.item
            if item is None or not isinstance(item.data, MessageItemData):
                continue
            text = "\n".join(
                block.text
                for block in item.data.content
                if isinstance(block, TextBlock)
            ).strip()
            if not text or item.data.role not in {"user", "assistant"}:
                continue
            now = utc_now()
            records.append(
                MemoryRecord(
                    # Event-derived identity makes post-commit ingestion safe
                    # to retry after a process crash or duplicate publication.
                    memory_id=f"memory_{event.event_id}",
                    scope=scope,
                    content=text,
                    kind=f"conversation.{item.data.role}",
                    source={
                        "session_id": run.session_id,
                        "run_id": run.run_id,
                        "event_id": event.event_id,
                        "item_id": item.item_id,
                    },
                    created_at=now,
                    updated_at=now,
                )
            )
        return tuple(records)


class MemoryService:
    """Coordinate a selected provider without exposing its storage internals."""

    def __init__(
        self,
        provider: MemoryProvider,
        *,
        ingestion_policy: MemoryIngestionPolicy | None = None,
        extractor: MemoryExtractor | None = None,
        on_error: Callable[[Exception], Awaitable[None]] | None = None,
        scope_mode: str = "principal",
    ) -> None:
        self.provider = provider
        self.ingestion_policy = ingestion_policy or CompletedRunMemoryPolicy()
        self.extractor = extractor or CanonicalMessageMemoryExtractor()
        self.on_error = on_error
        if scope_mode not in {"principal", "agent", "session"}:
            raise ValueError(f"unsupported Memory scope {scope_mode!r}")
        self.scope_mode = scope_mode

    async def recall(self, query: MemoryQuery) -> tuple[MemoryHit, ...]:
        return await self.provider.recall(query)

    async def remember(self, record: MemoryRecord) -> MemoryWriteResult:
        return await self.provider.remember(record)

    async def forget(self, memory_id: str, *, scope: MemoryScope) -> MemoryDeleteResult:
        return await self.provider.forget(memory_id, scope=scope)

    async def ingest_committed_run(
        self, run: RunSnapshot, context: RequestContext, session_store
    ) -> None:
        """Ingest only after the caller confirms canonical publication."""

        try:
            events = await session_store.read_events(run.run_id)
            if not await self.ingestion_policy.should_ingest(run, events):
                return
            scope = MemoryScope(
                tenant_id=context.actor.tenant_id,
                principal_id=context.actor.principal_id,
                agent_id=(
                    (await session_store.get_start_command(run.run_id)).agent_id
                    if self.scope_mode in {"agent", "session"}
                    else None
                ),
                session_id=(run.session_id if self.scope_mode == "session" else None),
            )
            for record in await self.extractor.extract(run, events, scope):
                await self.provider.remember(record)
        except Exception as exc:
            # Memory is downstream derived state. It must never roll back an
            # already acknowledged canonical Session commit.
            if self.on_error is not None:
                await self.on_error(exc)

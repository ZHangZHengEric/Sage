"""Session history indexing and request-aware retrieval coordination."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections import OrderedDict
from dataclasses import dataclass, field

from sagents.v2.context import ContextProjection
from sagents.v2.contracts.items import TextBlock
from sagents.v2.model import ModelMessage
from sagents.v2.session_memory.contracts import (
    SessionMemoryHit,
    SessionMemoryProvider,
    SessionMemoryQuery,
    SessionMemoryRecord,
)

_MAX_TRACKED_RUNS = 1_024
_MAX_TRACKED_SESSIONS = 256


@dataclass(frozen=True)
class _RequestBoundary:
    """What one observed projection allows the next recall to search."""

    session_id: str | None
    historical: frozenset[str]
    source_count: int = 0
    # tool_call_id -> record ids produced by that call, so a search_memory call
    # cannot retrieve its own request.
    calls: dict[str, tuple[str, ...]] = field(default_factory=dict)


class SessionMemoryService:
    """Index Session history incrementally and search only declared history.

    Indexing is driven by :meth:`observe_projection`, which the ContextAssembler
    calls once per model request with the canonical Run ledger already in
    memory. Only newly appended records are handed to the provider, so a recall
    costs one provider query instead of a full history rebuild plus a full
    re-sync.
    """

    def __init__(self, provider: SessionMemoryProvider) -> None:
        self.provider = provider
        self._boundaries: OrderedDict[str, _RequestBoundary] = OrderedDict()
        # session_id -> record_id -> content digest already accepted by the
        # provider. Purely an optimisation: losing it re-syncs, never corrupts.
        self._indexed: OrderedDict[str, dict[str, str]] = OrderedDict()
        self._lock = asyncio.Lock()

    async def observe_projection(
        self,
        run_id: str,
        projection: ContextProjection,
        *,
        session_id: str | None = None,
        source_messages: tuple[ModelMessage, ...] = (),
    ) -> None:
        historical = frozenset(
            self.record_id(message)
            for message in projection.historical_messages
            if message.role != "system"
        )
        async with self._lock:
            previous = self._boundaries.get(run_id)
            append_from = 0
            calls: dict[str, list[str]] = {}
            if (
                previous is not None
                and previous.session_id == session_id
                and previous.source_count <= len(source_messages)
            ):
                append_from = previous.source_count
                calls = {key: list(value) for key, value in previous.calls.items()}
            appended = source_messages[append_from:]
            records = (
                self._records(
                    session_id,
                    appended,
                    start_position=append_from,
                )
                if session_id is not None and appended
                else ()
            )
            for record in records:
                for tool_call_id in record.source.get("tool_call_ids", ()):
                    calls.setdefault(tool_call_id, []).append(record.record_id)
            pending = self._unindexed_locked(session_id, records)
        if pending:
            # Provider I/O stays outside the service lock so unrelated Runs can
            # index concurrently. A failed write does not advance this Run.
            await self.provider.sync(pending)
        boundary = _RequestBoundary(
            session_id=session_id,
            historical=historical,
            source_count=len(source_messages),
            calls={key: tuple(value) for key, value in calls.items()},
        )
        async with self._lock:
            self._remember_locked(session_id, pending)
            current = self._boundaries.get(run_id)
            if (
                current is not None
                and current.session_id == session_id
                and current.source_count > boundary.source_count
            ):
                return
            self._boundaries[run_id] = boundary
            self._boundaries.move_to_end(run_id)
            while len(self._boundaries) > _MAX_TRACKED_RUNS:
                self._boundaries.popitem(last=False)

    async def recall(
        self,
        *,
        run_id: str,
        session_id: str,
        text: str,
        limit: int,
        tool_call_id: str | None = None,
    ) -> tuple[SessionMemoryHit, ...]:
        async with self._lock:
            boundary = self._boundaries.get(run_id)
        # Missing projection and an explicit empty declaration both mean that
        # the reducer exposed no searchable history for this request. The
        # reducer plugin owns this boundary: Session Memory deliberately does
        # not infer history as "canonical ledger minus visible request".
        if boundary is None or not boundary.historical:
            return ()
        current_call_records = (
            frozenset(boundary.calls.get(tool_call_id, ()))
            if tool_call_id is not None
            else frozenset()
        )
        historical_record_ids = tuple(
            sorted(boundary.historical - current_call_records)
        )
        if not historical_record_ids:
            return ()
        return await self.provider.recall(
            SessionMemoryQuery(
                session_id=session_id,
                run_id=run_id,
                text=text,
                limit=limit,
                included_record_ids=historical_record_ids,
                excluded_record_ids=tuple(sorted(current_call_records)),
            )
        )

    async def forget_session(self, session_id: str) -> None:
        await self.provider.forget_session(session_id)
        async with self._lock:
            self._indexed.pop(session_id, None)
            for run_id, boundary in tuple(self._boundaries.items()):
                if boundary.session_id == session_id:
                    del self._boundaries[run_id]

    def _unindexed_locked(
        self, session_id: str | None, records: tuple[SessionMemoryRecord, ...]
    ) -> tuple[SessionMemoryRecord, ...]:
        if session_id is None or not records:
            return ()
        known = self._indexed.get(session_id, {})
        return tuple(
            record
            for record in records
            if known.get(record.record_id) != self._digest(record)
        )

    def _remember_locked(
        self, session_id: str | None, records: tuple[SessionMemoryRecord, ...]
    ) -> None:
        if session_id is None:
            return
        known = self._indexed.setdefault(session_id, {})
        for record in records:
            known[record.record_id] = self._digest(record)
        self._indexed.move_to_end(session_id)
        while len(self._indexed) > _MAX_TRACKED_SESSIONS:
            self._indexed.popitem(last=False)

    @classmethod
    def _records(
        cls,
        session_id: str,
        messages: tuple[ModelMessage, ...],
        *,
        start_position: int = 0,
    ) -> tuple[SessionMemoryRecord, ...]:
        # ``messages`` is the newly appended suffix of the canonical Run ledger.
        return tuple(
            cls._record(session_id, message, start_position + offset)
            for offset, message in enumerate(messages)
            if message.role != "system" and cls._content(message)
        )

    @staticmethod
    def _digest(record: SessionMemoryRecord) -> str:
        return hashlib.sha256(
            f"{record.position}\n{record.role}\n{record.content}".encode()
        ).hexdigest()

    @classmethod
    def _record(
        cls, session_id: str, message: ModelMessage, position: int
    ) -> SessionMemoryRecord:
        return SessionMemoryRecord(
            record_id=cls.record_id(message),
            session_id=session_id,
            role=message.role,
            content=cls._content(message),
            position=position,
            source={
                key: message.metadata[key]
                for key in (
                    "source_session_id",
                    "source_run_id",
                    "source_item_id",
                )
                if key in message.metadata
            }
            | {
                "tool_call_ids": tuple(
                    call.tool_call_id for call in message.tool_calls
                )
            },
        )

    @staticmethod
    def record_id(message: ModelMessage) -> str:
        item_id = message.metadata.get("source_item_id")
        if isinstance(item_id, str) and item_id:
            return item_id
        encoded = json.dumps(
            message.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return f"message_{hashlib.sha256(encoded).hexdigest()}"

    @staticmethod
    def _content(message: ModelMessage) -> str:
        parts = [
            block.text.strip()
            for block in message.content
            if isinstance(block, TextBlock) and block.text.strip()
        ]
        if message.tool_calls:
            parts.extend(
                f"{call.name} {json.dumps(call.arguments, ensure_ascii=False, sort_keys=True)}"
                for call in message.tool_calls
            )
        return "\n".join(parts).strip()

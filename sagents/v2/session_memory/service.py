"""Session history indexing and request-aware retrieval coordination."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections import OrderedDict
from typing import Protocol

from sagents.v2.context import ContextProjection
from sagents.v2.context.session_history import (
    SessionHistoryLedgerBuilder,
    SessionHistoryReader,
)
from sagents.v2.contracts.commands import StartRun
from sagents.v2.contracts.items import TextBlock
from sagents.v2.model import ModelMessage
from sagents.v2.session_memory.contracts import (
    SessionMemoryHit,
    SessionMemoryProvider,
    SessionMemoryQuery,
    SessionMemoryRecord,
)


class SessionMemoryReader(SessionHistoryReader, Protocol):
    async def get_start_command(self, run_id: str) -> StartRun: ...


class SessionMemoryService:
    """Index Session history and search only reducer-declared history."""

    def __init__(
        self,
        provider: SessionMemoryProvider,
        history_reader: SessionMemoryReader,
        *,
        history_builder: SessionHistoryLedgerBuilder | None = None,
    ) -> None:
        self.provider = provider
        self.history = history_builder or SessionHistoryLedgerBuilder(history_reader)
        self.reader = history_reader
        self._historical_by_run: OrderedDict[str, frozenset[str]] = OrderedDict()
        self._lock = asyncio.Lock()

    async def observe_projection(
        self, run_id: str, projection: ContextProjection
    ) -> None:
        historical = frozenset(
            self.record_id(message)
            for message in projection.historical_messages
            if message.role != "system"
        )
        async with self._lock:
            self._historical_by_run[run_id] = historical
            self._historical_by_run.move_to_end(run_id)
            while len(self._historical_by_run) > 1_024:
                self._historical_by_run.popitem(last=False)

    async def recall(
        self,
        *,
        run_id: str,
        session_id: str,
        text: str,
        limit: int,
        tool_call_id: str | None = None,
    ) -> tuple[SessionMemoryHit, ...]:
        command = await self.reader.get_start_command(run_id)
        ledger = await self.history.rebuild(command, run_id=run_id)
        records = tuple(
            self._record(session_id, message, position)
            for position, message in enumerate(ledger)
            if message.role != "system" and self._content(message)
        )
        await self.provider.sync(records)
        async with self._lock:
            declared_history = self._historical_by_run.get(run_id)
        if not declared_history:
            # Missing projection and an explicit empty declaration both mean
            # that the reducer exposed no searchable history for this request.
            return ()
        current_call_records = {
            record.record_id
            for record in records
            if tool_call_id is not None
            and tool_call_id in record.source.get("tool_call_ids", ())
        }
        # The reducer plugin owns this boundary. Session Memory deliberately
        # does not infer history as "canonical ledger minus visible request".
        historical_record_ids = tuple(
            record.record_id
            for record in records
            if record.record_id in declared_history
            and record.record_id not in current_call_records
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
                excluded_record_ids=tuple(current_call_records),
            )
        )

    async def forget_session(self, session_id: str) -> None:
        await self.provider.forget_session(session_id)

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

"""Official conversation-summary store plugin: process-local reference store."""

from __future__ import annotations

import asyncio

from sagents.v2.context.summary import ConversationSummary


class InMemoryConversationSummaryStore:
    """Concurrency-safe reference store for embedded and test deployments."""

    plugin_id = "sage.context.summary-store.ephemeral"
    name = "Ephemeral conversation summary store"
    description = "In-memory conversation summaries without restart durability."

    def __init__(self) -> None:
        self._values: dict[str, ConversationSummary] = {}
        self._lock = asyncio.Lock()

    async def get(
        self, context_key: str, *, session_id: str | None = None
    ) -> ConversationSummary | None:
        del session_id
        async with self._lock:
            return self._values.get(context_key)

    async def save(
        self,
        summary: ConversationSummary,
        *,
        expected_revision: int | None,
    ) -> ConversationSummary:
        async with self._lock:
            current = self._values.get(summary.context_key)
            current_revision = current.revision if current is not None else None
            if current_revision != expected_revision:
                raise ValueError(
                    "conversation summary revision changed during compaction"
                )
            self._values[summary.context_key] = summary
            return summary

    async def delete(
        self,
        context_key: str,
        *,
        expected_revision: int | None = None,
        session_id: str | None = None,
    ) -> None:
        del session_id
        async with self._lock:
            current = self._values.get(context_key)
            if current is None:
                return
            if expected_revision is not None and current.revision != expected_revision:
                raise ValueError(
                    "conversation summary revision changed before deletion"
                )
            del self._values[context_key]


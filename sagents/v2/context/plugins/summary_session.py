"""Official conversation-summary store plugin: SessionStore derived state."""

from __future__ import annotations

import asyncio
from typing import Any

from sagents.v2.context.summary import ConversationSummary


class SessionDerivedConversationSummaryStore:
    """Persist summaries inside the selected SessionStore derived namespace.

    This adapter removes the former second summary database. Summary state is
    still non-authoritative: deleting it only forces context compression to be
    recomputed from canonical Session events.
    """

    plugin_id = "sage.context.summary-store.session-derived"
    namespace = "context-summary"

    def __init__(self, session_store: Any) -> None:
        self.session_store = session_store
        self._lock = asyncio.Lock()

    async def get(
        self, context_key: str, *, session_id: str | None = None
    ) -> ConversationSummary | None:
        resolved_session_id = session_id or self._legacy_session_id(context_key)
        value = await self.session_store.get_derived_state(
            resolved_session_id, self.namespace, context_key
        )
        if isinstance(value, dict) and "session_id" not in value:
            # V1 derived summaries predate the explicit Session ownership
            # field. They are non-authoritative and safe to upgrade on read.
            value = {**value, "session_id": resolved_session_id}
        return ConversationSummary.model_validate(value) if value is not None else None

    async def save(
        self,
        summary: ConversationSummary,
        *,
        expected_revision: int | None,
    ) -> ConversationSummary:
        async with self._lock:
            current = await self.get(summary.context_key, session_id=summary.session_id)
            current_revision = current.revision if current is not None else None
            if current_revision != expected_revision:
                raise ValueError(
                    "conversation summary revision changed during compaction"
                )
            await self.session_store.put_derived_state(
                summary.session_id,
                self.namespace,
                summary.context_key,
                summary.model_dump(mode="json"),
            )
            return summary

    async def delete(
        self,
        context_key: str,
        *,
        expected_revision: int | None = None,
        session_id: str | None = None,
    ) -> None:
        async with self._lock:
            current = await self.get(context_key, session_id=session_id)
            if current is None:
                return
            if expected_revision is not None and current.revision != expected_revision:
                raise ValueError(
                    "conversation summary revision changed before deletion"
                )
            await self.session_store.delete_derived_state(
                current.session_id, self.namespace, context_key
            )

    @staticmethod
    def _legacy_session_id(context_key: str) -> str:
        """Read keys written before summaries carried an explicit Session ID."""

        return context_key.split(":snapshot:", 1)[0]

from __future__ import annotations

from typing import List

from sagents.context.messages.message import MessageChunk


class NoopSessionMemoryBackend:
    """Placeholder backend that intentionally returns no recalled history."""

    def clear_cache(self) -> None:
        return None

    def retrieve_history_messages(
        self,
        messages: List[MessageChunk],
        query: str,
        history_budget: int,
    ) -> List[MessageChunk]:
        return []

    def retrieve_group_messages_by_chat(
        self,
        messages: List[MessageChunk],
        query: str,
        history_budget: int,
    ) -> List[MessageChunk]:
        return []

from __future__ import annotations

from typing import List, Protocol, runtime_checkable

from sagents.context.messages.message import MessageChunk


@runtime_checkable
class SessionMemoryBackend(Protocol):
    """Backend contract for session-history retrieval implementations."""

    def retrieve_history_messages(
        self,
        messages: List[MessageChunk],
        query: str,
        history_budget: int,
    ) -> List[MessageChunk]:
        ...

    def retrieve_group_messages_by_chat(
        self,
        messages: List[MessageChunk],
        query: str,
        history_budget: int,
    ) -> List[MessageChunk]:
        ...

    def clear_cache(self) -> None:
        ...

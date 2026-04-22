"""
Session-history retrieval manager.

The manager keeps the public runtime contract stable while delegating the
actual retrieval strategy to a backend implementation.
"""
from typing import List, Optional

from sagents.context.messages.message import MessageChunk

from .backend import SessionMemoryBackend
from .bm25_backend import Bm25SessionMemoryBackend


class SessionMemoryManager:
    """历史消息检索管理器。"""

    def __init__(self, backend: Optional[SessionMemoryBackend] = None):
        self.backend = backend or Bm25SessionMemoryBackend()

    def clear_cache(self) -> None:
        if hasattr(self.backend, "clear_cache"):
            self.backend.clear_cache()

    def retrieve_group_messages_by_chat(
        self,
        messages: List[MessageChunk],
        query: str,
        history_budget: int
    ) -> List[MessageChunk]:
        return self.backend.retrieve_group_messages_by_chat(messages, query, history_budget)
    
    def retrieve_history_messages(
        self,
        messages: List[MessageChunk],
        query: str,
        history_budget: int
    ) -> List[MessageChunk]:
        return self.backend.retrieve_history_messages(messages, query, history_budget)

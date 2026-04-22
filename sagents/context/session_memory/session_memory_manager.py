"""
Session-history retrieval manager.

The manager keeps the public runtime contract stable while delegating the
actual retrieval strategy to a backend implementation.
"""
import os
from typing import Any, Dict, List, Optional

from sagents.context.messages.message import MessageChunk

from .backend import SessionMemoryBackend
from .bm25_backend import Bm25SessionMemoryBackend


DEFAULT_SESSION_MEMORY_STRATEGY = "messages"
SUPPORTED_SESSION_MEMORY_STRATEGIES = ("grouped_chat", "messages")


def available_session_memory_strategy_names() -> List[str]:
    return list(SUPPORTED_SESSION_MEMORY_STRATEGIES)


def resolve_session_memory_strategy(
    strategy_name: Optional[str] = None,
    agent_config: Optional[Dict[str, Any]] = None,
) -> str:
    """Resolve the session-history retrieval strategy.

    Precedence:
    1. Explicit function argument
    2. Agent config (`memory_backends.session_history_strategy` or legacy `session_memory_strategy`)
    3. Environment variable
    4. Default strategy
    """
    if strategy_name:
        resolved = strategy_name.strip().lower()
    else:
        config = agent_config or {}
        memory_backends = config.get("memory_backends") or {}
        configured = (
            memory_backends.get("session_history_strategy")
            or config.get("session_memory_strategy")
            or os.environ.get("SAGE_SESSION_MEMORY_STRATEGY")
            or DEFAULT_SESSION_MEMORY_STRATEGY
        )
        resolved = str(configured).strip().lower()

    if resolved not in SUPPORTED_SESSION_MEMORY_STRATEGIES:
        supported = ", ".join(SUPPORTED_SESSION_MEMORY_STRATEGIES)
        raise ValueError(
            f"Unsupported session memory strategy: {resolved}. "
            f"Supported strategies: {supported}"
        )
    return resolved


class SessionMemoryManager:
    """历史消息检索管理器。"""

    def __init__(self, backend: Optional[SessionMemoryBackend] = None):
        self.backend = backend or Bm25SessionMemoryBackend()

    def clear_cache(self) -> None:
        if hasattr(self.backend, "clear_cache"):
            self.backend.clear_cache()

    def retrieve(
        self,
        messages: List[MessageChunk],
        query: str,
        history_budget: int,
        *,
        strategy: Optional[str] = None,
        agent_config: Optional[Dict[str, Any]] = None,
    ) -> List[MessageChunk]:
        resolved_strategy = resolve_session_memory_strategy(
            strategy_name=strategy,
            agent_config=agent_config,
        )
        if resolved_strategy == "grouped_chat":
            return self.backend.retrieve_group_messages_by_chat(messages, query, history_budget)
        return self.backend.retrieve_history_messages(messages, query, history_budget)

    def retrieve_group_messages_by_chat(
        self,
        messages: List[MessageChunk],
        query: str,
        history_budget: int
    ) -> List[MessageChunk]:
        return self.retrieve(
            messages,
            query,
            history_budget,
            strategy="grouped_chat",
        )
    
    def retrieve_history_messages(
        self,
        messages: List[MessageChunk],
        query: str,
        history_budget: int
    ) -> List[MessageChunk]:
        return self.retrieve(
            messages,
            query,
            history_budget,
            strategy="messages",
        )

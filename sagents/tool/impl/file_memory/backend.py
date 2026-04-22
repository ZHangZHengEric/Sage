from __future__ import annotations

from typing import Any, Dict, List, Protocol, runtime_checkable


@runtime_checkable
class FileMemoryBackend(Protocol):
    """Backend contract for file-memory retrieval implementations."""

    async def search(self, query: str, top_k: int, session_context) -> List[Dict[str, Any]]:
        ...

    def clear_cache(self) -> None:
        ...

from __future__ import annotations

from typing import Any, Dict, List


class NoopFileMemoryBackend:
    """Placeholder backend that intentionally returns no file-memory results."""

    def __init__(self, memory_tool):
        self.memory_tool = memory_tool

    def clear_cache(self) -> None:
        return None

    async def search(self, query: str, top_k: int, session_context) -> List[Dict[str, Any]]:
        return []

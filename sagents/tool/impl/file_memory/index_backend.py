from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List

from sagents.utils.logger import logger


@dataclass
class _FileIndexCacheEntry:
    index: Any
    last_refresh_at: float = 0.0


class ScopedIndexFileMemoryBackend:
    """Scoped file-memory backend backed by the current MemoryIndex implementation."""

    INDEX_REFRESH_INTERVAL_SECONDS = 10.0
    _index_cache: Dict[str, _FileIndexCacheEntry] = {}

    def __init__(self, memory_tool):
        self.memory_tool = memory_tool

    @classmethod
    def clear_shared_cache(cls) -> None:
        cls._index_cache.clear()

    def clear_cache(self) -> None:
        self.clear_shared_cache()

    @staticmethod
    def _build_scope_key(user_id: str, agent_id: str, workspace_path: str) -> str:
        scope = f"{user_id}|{agent_id}|{workspace_path}"
        return hashlib.md5(scope.encode("utf-8")).hexdigest()

    async def search(self, query: str, top_k: int, session_context) -> List[Dict[str, Any]]:
        try:
            sandbox = session_context.sandbox
            if not sandbox:
                logger.warning("MemoryTool: No sandbox available for file memory search")
                return []

            workspace_path = getattr(session_context, "sandbox_agent_workspace", None) or "/sage-workspace"
            agent_id = getattr(session_context, "agent_id", None)
            user_id = getattr(session_context, "user_id", None) or "default_user"

            if not agent_id:
                logger.warning("MemoryTool: Cannot get agent_id for file memory search")
                return []

            from ..memory_index import MemoryIndex

            scope_key = self._build_scope_key(user_id, agent_id, workspace_path)
            index_path = self.memory_tool._get_index_path(
                user_id=user_id,
                agent_id=agent_id,
                workspace_path=workspace_path,
            )
            cache_entry = self._index_cache.get(scope_key)

            if not cache_entry:
                cache_entry = _FileIndexCacheEntry(
                    index=MemoryIndex(sandbox, workspace_path, index_path)
                )
                self._index_cache[scope_key] = cache_entry
            else:
                cache_entry.index.sandbox = sandbox
                cache_entry.index.workspace_path = workspace_path.rstrip("/")

            now = time.time()
            should_refresh = (
                not cache_entry.index.has_search_index()
                or (now - cache_entry.last_refresh_at) >= self.INDEX_REFRESH_INTERVAL_SECONDS
            )
            if should_refresh:
                stats = await cache_entry.index.update_index()
                cache_entry.last_refresh_at = now
                logger.info(f"MemoryTool: File memory index update stats: {stats}")

            results = cache_entry.index.search(query, top_k)

            formatted_results = []
            for result in results:
                snippets = []
                if result.content:
                    snippet_matches = re.findall(r"\[Line (\d+)\] (.*?)(?=\n\n|\Z)", result.content, re.DOTALL)
                    for line_num, snippet_text in snippet_matches:
                        snippets.append(
                            {
                                "line_number": int(line_num),
                                "text": snippet_text.strip(),
                            }
                        )

                formatted_results.append(
                    {
                        "path": result.path,
                        "snippets": snippets,
                    }
                )

            return formatted_results

        except Exception as e:
            logger.error(f"MemoryTool: File memory search failed: {e}")
            return []

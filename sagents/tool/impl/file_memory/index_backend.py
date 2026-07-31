from __future__ import annotations

import asyncio
import hashlib
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List

from sagents.utils.logger import logger


@dataclass
class _FileIndexCacheEntry:
    index: Any = None
    last_refresh_at: float = 0.0
    active_searches: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


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

    @classmethod
    def _acquire_scope(cls, scope_key: str) -> _FileIndexCacheEntry:
        """Register a search before it waits for the scope lock."""
        cache_entry = cls._index_cache.get(scope_key)
        if cache_entry is None:
            cache_entry = _FileIndexCacheEntry()
            cls._index_cache[scope_key] = cache_entry
        cache_entry.active_searches += 1
        return cache_entry

    @classmethod
    def _release_scope(
        cls, scope_key: str, cache_entry: _FileIndexCacheEntry
    ) -> None:
        """Drop the scoped index as soon as its last active search finishes."""
        cache_entry.active_searches -= 1
        if cache_entry.active_searches < 0:
            logger.error(
                "MemoryTool: File memory scope active search count became negative"
            )
            cache_entry.active_searches = 0

        if (
            cache_entry.active_searches == 0
            and cls._index_cache.get(scope_key) is cache_entry
        ):
            cls._index_cache.pop(scope_key, None)
            cache_entry.index = None

    @classmethod
    def _release_cancelled_scope_when_done(
        cls,
        operation_task: asyncio.Task,
        scope_key: str,
        cache_entry: _FileIndexCacheEntry,
    ) -> None:
        """Keep the scope alive until a shielded operation really stops."""
        try:
            error = operation_task.exception()
            if error is not None:
                logger.warning(
                    "MemoryTool: Cancelled file memory operation finished with "
                    f"an error: {error}"
                )
        except asyncio.CancelledError:
            pass
        finally:
            cls._release_scope(scope_key, cache_entry)

    async def _search_scope(
        self,
        cache_entry: _FileIndexCacheEntry,
        memory_index_type,
        sandbox,
        workspace_path: str,
        index_path: str,
        query: str,
        top_k: int,
    ):
        async with cache_entry.lock:
            if cache_entry.index is None:
                cache_entry.index = await asyncio.to_thread(
                    memory_index_type,
                    sandbox,
                    workspace_path,
                    index_path,
                )
            else:
                cache_entry.index.sandbox = sandbox
                cache_entry.index.workspace_path = workspace_path.rstrip("/")

            now = time.time()
            has_search_index = await asyncio.to_thread(
                cache_entry.index.has_search_index
            )
            should_refresh = (
                not has_search_index
                or (now - cache_entry.last_refresh_at)
                >= self.INDEX_REFRESH_INTERVAL_SECONDS
            )
            if should_refresh:
                stats = await cache_entry.index.update_index()
                cache_entry.last_refresh_at = now
                logger.debug(f"MemoryTool: File memory index update stats: {stats}")

            return await asyncio.to_thread(cache_entry.index.search, query, top_k)

    async def search(
        self, query: str, top_k: int, session_context
    ) -> List[Dict[str, Any]]:
        try:
            sandbox = session_context.sandbox
            if not sandbox:
                logger.warning(
                    "MemoryTool: No sandbox available for file memory search"
                )
                return []

            workspace_path = (
                getattr(session_context, "sandbox_agent_workspace", None)
                or "/sage-workspace"
            )
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
            cache_entry = self._acquire_scope(scope_key)
            operation_task = asyncio.create_task(
                self._search_scope(
                    cache_entry,
                    MemoryIndex,
                    sandbox,
                    workspace_path,
                    index_path,
                    query,
                    top_k,
                )
            )
            release_deferred = False
            try:
                results = await asyncio.shield(operation_task)
            except asyncio.CancelledError:
                release_deferred = True
                operation_task.add_done_callback(
                    lambda task: self._release_cancelled_scope_when_done(
                        task, scope_key, cache_entry
                    )
                )
                raise
            finally:
                if not release_deferred:
                    self._release_scope(scope_key, cache_entry)

            formatted_results = []
            for result in results:
                snippets = []
                if result.content:
                    snippet_matches = re.findall(
                        r"\[Line (\d+)\] (.*?)(?=\n\n|\Z)", result.content, re.DOTALL
                    )
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

#!/usr/bin/env python3
"""
Memory tool for workspace file memory and session-history retrieval.

File memory currently uses a scoped chunk index; session history keeps the
existing BM25-based retrieval path.
"""
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, Optional, List
from ..tool_base import tool
from sagents.utils.logger import logger
from sagents.utils.agent_session_helper import get_session_sandbox as _get_session_sandbox_util


@dataclass
class _FileIndexCacheEntry:
    index: Any
    last_refresh_at: float = 0.0


@dataclass
class _SessionHistoryCacheEntry:
    messages_fingerprint: str
    agent_config_fingerprint: str
    history_messages: List[Any]


class FileMemoryRetriever:
    """文件级长期记忆检索。

    作用域按 user + agent + workspace 区分，避免不同工作区/Agent 串用索引。
    """

    INDEX_REFRESH_INTERVAL_SECONDS = 10.0
    _index_cache: Dict[str, _FileIndexCacheEntry] = {}

    def __init__(self, memory_tool: "MemoryTool"):
        self.memory_tool = memory_tool

    @classmethod
    def clear_cache(cls) -> None:
        cls._index_cache.clear()

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

            from .memory_index import MemoryIndex

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
                # 同作用域下复用 MemoryIndex，但每次绑定当前 session 的 sandbox 引用。
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
                    snippet_matches = re.findall(r'\[Line (\d+)\] (.*?)(?=\n\n|\Z)', result.content, re.DOTALL)
                    for line_num, snippet_text in snippet_matches:
                        snippets.append({
                            "line_number": int(line_num),
                            "text": snippet_text.strip()
                        })

                formatted_results.append({
                    "path": result.path,
                    "snippets": snippets,
                })

            return formatted_results

        except Exception as e:
            logger.error(f"MemoryTool: File memory search failed: {e}")
            return []


class SessionHistoryRetriever:
    """会话级历史记忆检索。

    保持当前 history_messages 的语义边界不变，只优化 prepare/BM25 的重复开销。
    """

    _history_cache: Dict[str, _SessionHistoryCacheEntry] = {}

    def __init__(self, memory_tool: "MemoryTool"):
        self.memory_tool = memory_tool

    @classmethod
    def clear_cache(cls) -> None:
        cls._history_cache.clear()

    @staticmethod
    def _serialize_message_content(content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        return json.dumps(content, ensure_ascii=False, sort_keys=True, default=str)

    def _fingerprint_messages(self, messages: List[Any]) -> str:
        digests: List[str] = []
        for msg in messages:
            content = self._serialize_message_content(msg.get_content())
            content_hash = hashlib.md5(content.encode("utf-8")).hexdigest()
            normalized_type = msg.normalized_message_type() if hasattr(msg, "normalized_message_type") else None
            digests.append(
                f"{msg.message_id}|{msg.role}|{normalized_type or ''}|{content_hash}"
            )
        return hashlib.md5("\n".join(digests).encode("utf-8")).hexdigest()

    @staticmethod
    def _fingerprint_agent_config(agent_config: Dict[str, Any]) -> str:
        try:
            serialized = json.dumps(agent_config or {}, ensure_ascii=False, sort_keys=True, default=str)
        except Exception:
            serialized = str(agent_config or {})
        return hashlib.md5(serialized.encode("utf-8")).hexdigest()

    def _get_history_messages(self, session_id: str, session_context) -> List[Any]:
        message_manager = session_context.message_manager
        agent_config = getattr(session_context, "agent_config", {}) or {}

        messages_fingerprint = self._fingerprint_messages(message_manager.messages)
        agent_config_fingerprint = self._fingerprint_agent_config(agent_config)

        cache_entry = self._history_cache.get(session_id)
        if (
            cache_entry
            and cache_entry.messages_fingerprint == messages_fingerprint
            and cache_entry.agent_config_fingerprint == agent_config_fingerprint
        ):
            return cache_entry.history_messages

        prepare_result = message_manager.prepare_history_split(agent_config)
        history_messages = prepare_result["split_result"]["history_messages"]
        self._history_cache[session_id] = _SessionHistoryCacheEntry(
            messages_fingerprint=messages_fingerprint,
            agent_config_fingerprint=agent_config_fingerprint,
            history_messages=history_messages,
        )
        return history_messages

    def search(self, query: str, top_k: int, session_id: str, session_context) -> List[Dict[str, Any]]:
        try:
            history_messages = self._get_history_messages(session_id, session_context)
            if not history_messages:
                logger.debug("MemoryTool: No history messages to search")
                return []

            session_memory_manager = session_context.session_memory_manager
            retrieved_messages = session_memory_manager.retrieve_history_messages(
                messages=history_messages,
                query=query,
                history_budget=top_k * 200
            )
            retrieved_messages = retrieved_messages[:top_k]

            logger.info(f"MemoryTool: Retrieved {len(retrieved_messages)} history messages for query '{query}'")

            formatted_results = []
            for msg in retrieved_messages:
                content = msg.content or ""
                snippet = self.memory_tool._extract_history_snippet(content, query.lower().split())
                formatted_results.append({
                    "role": msg.role,
                    "content_preview": snippet,
                    "timestamp": getattr(msg, 'timestamp', None)
                })

            return formatted_results

        except Exception as e:
            logger.error(f"MemoryTool: Session history search failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []


class MemoryTool:
    """
    Agent memory tool - BM25 index search based on file system and session history
    
    Features:
    1. Auto build/update BM25 index of workspace files through sandbox
    2. Search related files based on filename and content
    3. Search session history messages
    4. Use file extension whitelist and directory blacklist managed by MemoryIndex
    """

    def __init__(self):
        self.file_memory_retriever = FileMemoryRetriever(self)
        self.session_history_retriever = SessionHistoryRetriever(self)

    @staticmethod
    def _build_search_response(
        status: str,
        message: str,
        query: Optional[str] = None,
        long_term_memory: Optional[List[Dict[str, Any]]] = None,
        session_history: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        response = {
            "status": status,
            "message": message,
            "long_term_memory": long_term_memory or [],
            "session_history": session_history or [],
        }
        if query is not None:
            response["query"] = query
        return response

    def _get_sandbox(self, session_id: str):
        """通过 session_id 获取沙箱。详见
        ``sagents.utils.agent_session_helper.get_session_sandbox``。
        """
        return _get_session_sandbox_util(session_id, log_prefix="MemoryTool")

    def _get_workspace_path(self, session_id: str) -> Optional[str]:
        """Get workspace virtual path from session"""
        try:
            from sagents.utils.agent_session_helper import get_live_session
            session = get_live_session(session_id, log_prefix="MemoryTool")

            if not session:
                logger.warning(f"MemoryTool: Session not found: {session_id}")
                return None

            session_context = session.session_context
            
            # Get sandbox_agent_workspace path
            if hasattr(session_context, 'sandbox_agent_workspace') and session_context.sandbox_agent_workspace:
                return session_context.sandbox_agent_workspace

            # Fallback to default
            return "/sage-workspace"
            
        except Exception as e:
            logger.error(f"MemoryTool: Get workspace failed: {e}")
            return None

    def _get_agent_id(self, session_id: str) -> Optional[str]:
        """Get agent_id from session"""
        try:
            from sagents.utils.agent_session_helper import get_live_session
            session = get_live_session(session_id, log_prefix="MemoryTool")

            if not session:
                logger.warning(f"MemoryTool: Session not found: {session_id}")
                return None

            session_context = session.session_context
            
            # Get agent_id from session_context
            if hasattr(session_context, 'agent_id') and session_context.agent_id:
                return session_context.agent_id
            
            logger.warning(f"MemoryTool: agent_id not found for session {session_id}")
            return None
            
        except Exception as e:
            logger.error(f"MemoryTool: Get agent_id failed: {e}")
            return None

    def _get_index_path(self, user_id: str, agent_id: str, workspace_path: str) -> str:
        """Get scoped index file path (stored on host).

        文件长期记忆按 user + agent + workspace 隔离，避免不同作用域复用同一个磁盘索引。
        """
        # Get MEMORY_ROOT_PATH from environment variable
        memory_root = os.environ.get('MEMORY_ROOT_PATH')
        if not memory_root:
            # 默认使用用户主目录下的 .sage/memory
            user_home = Path.home()
            memory_root = user_home / ".sage" / "memory"
        
        # Create memory directory
        memory_dir = Path(memory_root)
        memory_dir.mkdir(parents=True, exist_ok=True)

        workspace_hash = hashlib.md5(workspace_path.encode("utf-8")).hexdigest()[:12]
        safe_user_id = re.sub(r"[^A-Za-z0-9._-]+", "_", user_id or "default_user")
        safe_agent_id = re.sub(r"[^A-Za-z0-9._-]+", "_", agent_id or "default_agent")
        index_path = memory_dir / f"{safe_user_id}__{safe_agent_id}__{workspace_hash}.pkl"
        logger.debug(f"MemoryTool: Index path: {index_path}")
        
        return str(index_path)

    @tool(
        description_i18n={
            "zh": "搜索 Agent 的记忆。包括工作空间中的长期记忆（代码文件、文档等）和本次会话的历史对话。返回最相关的内容。",
            "en": "Search Agent's memory. Includes long-term memory (code files, docs) in workspace and current session history."
        },
        param_description_i18n={
            "query": {
                "zh": "搜索关键词。可以是文件名、函数描述、代码片段、历史对话内容等。支持中文和英文。",
                "en": "Search query. Can be filename, function description, code snippet, history message, etc. Supports Chinese and English."
            },
            "top_k": {
                "zh": "返回结果数量，默认 5",
                "en": "Number of results to return, default 5"
            },
            "session_id": {
                "zh": "会话 ID（必填，自动注入）",
                "en": "Session ID (Required, Auto-injected)"
            }
        }
    )
    async def search_memory(
        self,
        query: str,
        top_k: int = 5,
        session_id: str = None
    ) -> Dict[str, Any]:
        """
        Search memory (files and session history)
        
        Args:
            query: Search query
            top_k: Number of results to return
            session_id: Session ID (required)
        
        Returns:
            Search results including files and history messages
        """
        if not session_id:
            return self._build_search_response(
                status="error",
                message="Session ID not provided",
            )

        if not query or not query.strip():
            return self._build_search_response(
                status="error",
                message="Search query cannot be empty",
            )
        
        try:
            # 1. Search file memory
            file_results = await self._search_file_memory(query, top_k, session_id)
            
            # 2. Search session history
            history_results = await self._search_session_history(query, top_k, session_id)
            
            return self._build_search_response(
                status="success",
                message=f"Found {len(file_results)} files and {len(history_results)} history messages",
                query=query,
                long_term_memory=file_results,
                session_history=history_results,
            )

        except Exception as e:
            logger.error(f"MemoryTool: Search failed: {e}")
            return self._build_search_response(
                status="error",
                message=f"Search failed: {str(e)}",
                query=query,
            )

    async def _search_file_memory(self, query: str, top_k: int, session_id: str) -> List[Dict[str, Any]]:
        """Search file memory using the scoped file-memory index through sandbox."""
        try:
            from sagents.utils.agent_session_helper import get_live_session

            session = get_live_session(session_id, log_prefix="MemoryTool")
            if not session or not session.session_context:
                logger.warning(f"MemoryTool: Session not found for file memory search: {session_id}")
                return []

            return await self.file_memory_retriever.search(query, top_k, session.session_context)

        except Exception as e:
            logger.error(f"MemoryTool: File memory search failed: {e}")
            return []

    async def _search_session_history(self, query: str, top_k: int, session_id: str) -> List[Dict[str, Any]]:
        """
        Search session history messages using BM25 retrieval
        
        流程：准备历史上下文 -> 使用 session_memory_manager 检索 -> 返回结果
        """
        try:
            from sagents.utils.agent_session_helper import get_live_session

            session = get_live_session(session_id, log_prefix="MemoryTool")

            if not session:
                logger.warning(f"MemoryTool: Session not found: {session_id}")
                return []
            
            session_context = session.session_context
            return self.session_history_retriever.search(query, top_k, session_id, session_context)

        except Exception as e:
            logger.error(f"MemoryTool: Session history search failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []

    def _extract_history_snippet(self, content: str, query_terms: List[str], snippet_size: int = 100) -> str:
        """Extract snippet from history message containing query terms"""
        if not content:
            return ""
        
        content_lower = content.lower()
        
        # Find first match position
        first_match_pos = len(content)
        for term in query_terms:
            pos = content_lower.find(term)
            if pos != -1 and pos < first_match_pos:
                first_match_pos = pos
        
        if first_match_pos == len(content):
            # No match found, return first part
            return content[:snippet_size] + "..." if len(content) > snippet_size else content
        
        # Extract snippet around match
        start = max(0, first_match_pos - snippet_size // 2)
        end = min(len(content), first_match_pos + snippet_size // 2)
        
        snippet = content[start:end]
        
        # Add ellipsis
        if start > 0:
            snippet = "..." + snippet
        if end < len(content):
            snippet = snippet + "..."
        
        return snippet.strip()

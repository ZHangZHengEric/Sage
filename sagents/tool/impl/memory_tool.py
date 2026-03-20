#!/usr/bin/env python3
"""
Memory tool based on BM25 file system - Sandbox version
Get workspace through session_id, build file index and support search
"""
import os
import re
from pathlib import Path
from typing import Dict, Any, Optional, List
from ..tool_base import tool
from sagents.utils.logger import logger


class MemoryTool:
    """
    Agent memory tool - BM25 index search based on file system and session history
    
    Features:
    1. Auto build/update BM25 index of workspace files through sandbox
    2. Search related files based on filename and content
    3. Search session history messages
    4. Use file extension whitelist and directory blacklist managed by MemoryIndex
    """

    def _get_sandbox(self, session_id: str):
        """通过 session_id 获取沙箱"""
        from sagents.session_runtime import get_global_session_manager
        session_manager = get_global_session_manager()
        session = session_manager.get(session_id)
        if not session or not session.session_context:
            raise ValueError(f"MemoryTool: Invalid session_id={session_id}")

        sandbox = session.session_context.sandbox
        if not sandbox:
            raise ValueError(f"MemoryTool: No sandbox available for session_id={session_id}")

        return sandbox

    def _get_workspace_path(self, session_id: str) -> Optional[str]:
        """Get workspace virtual path from session"""
        try:
            from sagents.session_runtime import get_global_session_manager
            session_manager = get_global_session_manager()
            session = session_manager.get(session_id)
            
            if not session:
                logger.warning(f"MemoryTool: Session not found: {session_id}")
                return None
            
            session_context = session.session_context
            
            # Get virtual workspace path
            if hasattr(session_context, 'virtual_workspace') and session_context.virtual_workspace:
                return session_context.virtual_workspace
            
            # Fallback to default
            return "/sage-workspace"
            
        except Exception as e:
            logger.error(f"MemoryTool: Get workspace failed: {e}")
            return None

    def _get_agent_id(self, session_id: str) -> Optional[str]:
        """Get agent_id from session"""
        try:
            from sagents.session_runtime import get_global_session_manager
            session_manager = get_global_session_manager()
            session = session_manager.get(session_id)
            
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

    def _get_index_path(self, agent_id: str) -> str:
        """Get index file path for agent (stored on host)
        
        Args:
            agent_id: Agent ID (not session_id)
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
        
        index_path = memory_dir / f"{agent_id}.pkl"
        logger.debug(f"MemoryTool: Index path: {index_path}")
        
        return str(index_path)

    @tool(
        description_i18n={
            "zh": "搜索 Agent 的记忆。包括工作空间中的长期记忆（代码文件、文档等）和本次会话的历史对话。返回最相关的内容。",
            "en": "Search Agent's memory. Includes long-term memory (code files, docs) in workspace and current session history. Uses BM25 algorithm."
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
            return {
                "status": "error",
                "message": "Session ID not provided",
                "results": [],
                "history_results": []
            }
        
        if not query or not query.strip():
            return {
                "status": "error",
                "message": "Search query cannot be empty",
                "results": [],
                "history_results": []
            }
        
        try:
            # 1. Search file memory
            file_results = await self._search_file_memory(query, top_k, session_id)
            
            # 2. Search session history
            history_results = await self._search_session_history(query, top_k, session_id)
            
            return {
                "status": "success",
                "message": f"Found {len(file_results)} files and {len(history_results)} history messages",
                "query": query,
                "long_term_memory": file_results,
                "session_history": history_results
            }
            
        except Exception as e:
            logger.error(f"MemoryTool: Search failed: {e}")
            return {
                "status": "error",
                "message": f"Search failed: {str(e)}",
                "results": [],
                "history_results": []
            }

    async def _search_file_memory(self, query: str, top_k: int, session_id: str) -> List[Dict[str, Any]]:
        """Search file memory using BM25 index through sandbox"""
        try:
            # Get sandbox and workspace path
            sandbox = self._get_sandbox(session_id)
            workspace_path = self._get_workspace_path(session_id)
            if not workspace_path:
                logger.warning(f"MemoryTool: Cannot get workspace path for session {session_id}")
                return []
            
            # Get agent_id and index path (stored on host, keyed by agent_id)
            agent_id = self._get_agent_id(session_id)
            if not agent_id:
                logger.warning(f"MemoryTool: Cannot get agent_id for session {session_id}")
                return []
            
            index_path = self._get_index_path(agent_id)
            
            # Load/build index
            from .memory_index import MemoryIndex
            index = MemoryIndex(sandbox, workspace_path, index_path)
            
            # Auto update index (fast check if no changes)
            stats = await index.update_index()
            logger.info(f"MemoryTool: Index update stats: {stats}")
            
            # Search
            results = index.search(query, top_k)
            
            # Format results with snippets
            formatted_results = []
            for r in results:
                # Extract snippets from the content preview
                snippets = []
                if r.content:
                    # Split by line number markers
                    snippet_matches = re.findall(r'\[Line (\d+)\] (.*?)(?=\n\n|\Z)', r.content, re.DOTALL)
                    for line_num, snippet_text in snippet_matches:
                        snippets.append({
                            "line_number": int(line_num),
                            "text": snippet_text.strip()
                        })
                
                formatted_results.append({
                    "path": r.path,
                    "snippets": snippets,
                })
            
            return formatted_results
            
        except Exception as e:
            logger.error(f"MemoryTool: File memory search failed: {e}")
            return []

    async def _search_session_history(self, query: str, top_k: int, session_id: str) -> List[Dict[str, Any]]:
        """
        Search session history messages using BM25 retrieval
        
        流程：准备历史上下文 -> 使用 session_memory_manager 检索 -> 返回结果
        """
        try:
            from sagents.session_runtime import get_global_session_manager
            
            session_manager = get_global_session_manager()
            session = session_manager.get(session_id)
            
            if not session:
                logger.warning(f"MemoryTool: Session not found: {session_id}")
                return []
            
            session_context = session.session_context
            message_manager = session_context.message_manager
            session_memory_manager = session_context.session_memory_manager
            
            # 1. 准备历史上下文（计算预算、切分消息）
            agent_config = getattr(session_context, 'agent_config', {})
            prepare_result = message_manager.prepare_history_split(agent_config)
            
            # 2. 获取历史消息（排除最近的消息）
            history_messages = prepare_result['split_result']['history_messages']
            
            if not history_messages:
                logger.debug("MemoryTool: No history messages to search")
                return []
            
            # 3. 使用 session_memory_manager 进行 BM25 检索
            retrieved_messages = session_memory_manager.retrieve_history_messages(
                messages=history_messages,
                query=query,
                history_budget=top_k * 200  # 估算每个消息约500字符
            )
            
            # 4. 限制返回数量
            retrieved_messages = retrieved_messages[:top_k]
            
            logger.info(f"MemoryTool: Retrieved {len(retrieved_messages)} history messages for query '{query}'")
            
            # 5. 格式化结果
            formatted_results = []
            for msg in retrieved_messages:
                content = msg.content or ""
                
                # 提取包含查询词的片段
                snippet = self._extract_history_snippet(content, query.lower().split())
                
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

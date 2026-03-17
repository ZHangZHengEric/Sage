#!/usr/bin/env python3
"""
Memory tool based on BM25 file system - search version
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
    1. Auto build/update BM25 index of workspace files
    2. Search related files based on filename and content
    3. Search session history messages
    4. Use file extension whitelist and directory blacklist managed by MemoryIndex
    """

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
                "zh": "会话 ID（可选，自动注入，无需填写）",
                "en": "Session ID (Optional, Auto-injected)"
            }
        }
    )
    async def search_memory(
        self,
        query: str,
        top_k: int = 5,
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Search memory (files and session history)
        
        Args:
            query: Search query
            top_k: Number of results to return
            session_id: Session ID
        
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
            
            # 3. Build narrative memory description
            memory_narrative = self._build_memory_narrative(query, file_results, history_results)
            
            return {
                "status": "success",
                "message": f"Found {len(file_results)} files and {len(history_results)} history messages",
                "query": query,
                "memory_summary": memory_narrative,
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

    def _build_memory_narrative(self, query: str, file_results: List[Dict], history_results: List[Dict]) -> str:
        """Build a narrative description of the found memories"""
        parts = []
        
        if file_results:
            parts.append(f"关于 '{query}'，我在工作空间中找到了 {len(file_results)} 个相关文件：")
            for i, item in enumerate(file_results[:3], 1):
                filename = os.path.basename(item.get('path', ''))
                snippets = item.get('snippets', [])
                if snippets:
                    preview = snippets[0].get('text', '')[:80]
                    parts.append(f"  {i}. {filename}: {preview}...")
                else:
                    parts.append(f"  {i}. {filename}")
        
        if history_results:
            if parts:
                parts.append("")
            parts.append(f"另外，在之前的对话中，我们讨论过 '{query}' 相关的内容：")
            for i, item in enumerate(history_results[:2], 1):
                role = "你" if item.get('role') == 'user' else "我"
                preview = item.get('content_preview', '')[:80]
                parts.append(f"  {i}. {role}提到: {preview}...")
        
        if not parts:
            return f"没有找到关于 '{query}' 的相关记忆。"
        
        return "\n".join(parts)

    async def _search_file_memory(self, query: str, top_k: int, session_id: str) -> List[Dict[str, Any]]:
        """Search file memory using BM25 index"""
        try:
            # Get workspace path
            workspace_path = self._get_workspace_path(session_id)
            if not workspace_path:
                logger.warning(f"MemoryTool: Cannot get workspace path for session {session_id}")
                return []
            
            # Get index path for this workspace
            index_path = self._get_index_path(session_id)
            
            # Load/build index
            from .memory_index import MemoryIndex
            index = MemoryIndex(workspace_path, index_path)
            
            # Auto update index (fast check if no changes)
            stats = index.update_index()
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
                history_budget=top_k * 200  # 估算每个消息约200字符
            )
            
            # 4. 限制返回数量
            retrieved_messages = retrieved_messages[:top_k]
            
            logger.info(f"Memory
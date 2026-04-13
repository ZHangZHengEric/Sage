"""Agent Client for IM Server.

Provides unified interface to communicate with Sage Agent via API.
"""

import asyncio
import os
import json
import logging
from typing import Optional, Dict, Any, List
from pathlib import Path

import httpx

# Import Sage's message management classes
try:
    from sagents.context.messages import MessageChunk, MessageManager
    from sagents.context.messages.message import MessageRole
    SAGE_MESSAGE_AVAILABLE = True
except ImportError:
    SAGE_MESSAGE_AVAILABLE = False
    MessageChunk = None
    MessageManager = None
    MessageRole = None

# IM Server file sending tool will be imported lazily to avoid circular imports
SEND_FILE_AVAILABLE = None  # Will be determined on first use
send_file_through_im = None

def _ensure_send_file_import():
    """Lazily import send_file_through_im to avoid circular imports."""
    global SEND_FILE_AVAILABLE, send_file_through_im
    if SEND_FILE_AVAILABLE is not None:
        return SEND_FILE_AVAILABLE
    
    try:
        from mcp_servers.im_server.im_server import send_file_through_im as _send_file
        send_file_through_im = _send_file
        SEND_FILE_AVAILABLE = True
        logger.debug("[AgentClient] send_file_through_im imported successfully")
    except Exception as e:
        logger.warning(f"[AgentClient] Failed to import send_file_through_im: {e}")
        SEND_FILE_AVAILABLE = False
        send_file_through_im = None
    
    return SEND_FILE_AVAILABLE

logger = logging.getLogger("AgentClient")


class AgentClient:
    """Client for communicating with Sage Agent."""
    
    def __init__(self, base_url: Optional[str] = None, timeout: float = 300.0):
        """
        Initialize Agent client.
        
        Args:
            base_url: Sage API base URL (default: http://localhost:{SAGE_PORT})
            timeout: Request timeout in seconds
        """
        self.base_url = base_url or self._get_default_base_url()
        self.timeout = timeout
        
    def _get_default_base_url(self) -> str:
        """Get default API base URL from environment."""
        port = os.getenv("SAGE_PORT", "8080")
        return f"http://localhost:{port}"
    
    def _parse_stream_response(self, response: httpx.Response) -> List[Any]:
        """
        Parse streaming response from Sage API using MessageChunk.
        
        Only collects and merges chunks by message_id. Returns raw messages list.
        Analysis (tool check, response extraction) should be done after stream ends.
        
        Args:
            response: HTTPX response object
            
        Returns:
            List of MessageChunk objects (or dicts in fallback mode)
        """
        if not SAGE_MESSAGE_AVAILABLE:
            logger.warning("Sage message classes not available, using fallback parsing")
            return self._parse_stream_response_fallback(response)
        
        # Use MessageManager to manage messages (only collects and merges)
        message_manager = MessageManager()
        
        for line in response.iter_lines():
            if not line:
                continue
                
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            
            # Skip control messages
            msg_type = data.get("type")
            if msg_type in ("chunk_start", "chunk_end", "json_chunk"):
                continue
            
            # Parse message data
            try:
                # Create MessageChunk from data
                chunk = self._create_message_chunk(data)
                if chunk:
                    message_manager.add_messages(chunk)
            except Exception as e:
                logger.warning(f"Failed to create MessageChunk: {e}, data: {data}")
                continue
        
        # Return raw messages - analysis will be done after stream ends
        return message_manager.messages
    
    def _check_im_tool_in_messages(self, messages: List[Any]) -> bool:
        """Check if any message contains send_message_through_im tool call."""
        for msg in messages:
            # Handle both MessageChunk objects and dicts (fallback mode)
            if isinstance(msg, dict):
                if msg.get("role") != "assistant":
                    continue
                tool_calls = msg.get("tool_calls", [])
            else:
                # MessageChunk object
                if SAGE_MESSAGE_AVAILABLE and MessageRole:
                    if msg.role != MessageRole.ASSISTANT.value:
                        continue
                tool_calls = msg.tool_calls if hasattr(msg, 'tool_calls') else []
            
            if not tool_calls:
                continue
                
            for tool_call in tool_calls:
                tool_name = self._extract_tool_name(tool_call)
                if tool_name == "send_message_through_im":
                    return True
        return False
    
    def _extract_tool_name(self, tool_call: Any) -> Optional[str]:
        """Extract tool name from tool_call object."""
        if isinstance(tool_call, dict):
            return tool_call.get("function", {}).get("name") or tool_call.get("name")
        elif hasattr(tool_call, 'function'):
            return getattr(tool_call.function, 'name', None)
        return None
    
    def _extract_last_assistant_response(self, messages: List[Any], has_im_tool: bool) -> str:
        """Extract the last non-empty assistant message content."""
        if has_im_tool:
            return ""  # No text response when tool is called
        
        # Find the last assistant message with non-empty content
        for msg in reversed(messages):
            # Handle both MessageChunk objects and dicts (fallback mode)
            if isinstance(msg, dict):
                if msg.get("role") != "assistant":
                    continue
                content = msg.get("content", "")
            else:
                # MessageChunk object
                if SAGE_MESSAGE_AVAILABLE and MessageRole:
                    if msg.role != MessageRole.ASSISTANT.value:
                        continue
                content = msg.content if hasattr(msg, 'content') else ""
            
            if not content:
                continue
            if isinstance(content, str) and content.strip():
                return content
        return ""
    
    def _extract_tool_arguments(self, tool_call: Any) -> Dict[str, Any]:
        """Extract tool arguments from tool_call object."""
        if isinstance(tool_call, dict):
            args_str = tool_call.get("function", {}).get("arguments", "{}")
        elif hasattr(tool_call, 'function'):
            args_str = getattr(tool_call.function, 'arguments', "{}")
        else:
            return {}
        
        try:
            if isinstance(args_str, str):
                return json.loads(args_str)
            elif isinstance(args_str, dict):
                return args_str
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse tool arguments: {args_str}")
        return {}
    
    def _extract_file_paths_from_messages(self, messages: List[Any]) -> List[str]:
        """
        Extract file paths from file_write and send_file_through_im tool calls.
        
        Returns list of file paths that Agent created or tried to send.
        """
        file_paths = []
        
        for msg in messages:
            # Handle both MessageChunk objects and dicts (fallback mode)
            if isinstance(msg, dict):
                if msg.get("role") != "assistant":
                    continue
                tool_calls = msg.get("tool_calls", [])
            else:
                if SAGE_MESSAGE_AVAILABLE and MessageRole:
                    if msg.role != MessageRole.ASSISTANT.value:
                        continue
                tool_calls = msg.tool_calls if hasattr(msg, 'tool_calls') else []
            
            if not tool_calls:
                continue
            
            for tool_call in tool_calls:
                tool_name = self._extract_tool_name(tool_call)
                
                if tool_name in ("file_write", "send_file_through_im"):
                    args = self._extract_tool_arguments(tool_call)
                    file_path = args.get("file_path")
                    if file_path and file_path not in file_paths:
                        file_paths.append(file_path)
                        logger.debug(f"[AgentClient] Found file path from {tool_name}: {file_path}")
        
        return file_paths
    
    def _convert_virtual_to_host_path(self, virtual_path: str, agent_id: str) -> Optional[str]:
        """
        Convert virtual path to host file system path.
        
        Args:
            virtual_path: Path like /sage-workspace/outputs/file.txt
            agent_id: Agent ID to determine the host workspace
            
        Returns:
            Host path or None if conversion fails
        """
        # Get Sage home directory
        sage_home = Path.home() / ".sage"
        agent_workspace = sage_home / "agents" / agent_id
        
        # Common virtual path prefixes
        virtual_prefixes = ["/sage-workspace", "/workspace"]
        
        for prefix in virtual_prefixes:
            if virtual_path.startswith(prefix + "/") or virtual_path == prefix:
                # Replace virtual prefix with actual path
                relative_path = virtual_path[len(prefix):].lstrip("/")
                host_path = agent_workspace / relative_path
                
                if host_path.exists():
                    return str(host_path)
                else:
                    # Try to find file in common subdirectories
                    for subdir in ["outputs", "data", "temp"]:
                        candidate = agent_workspace / subdir / relative_path
                        if candidate.exists():
                            return str(candidate)
                        # Also try if relative_path already contains subdir
                        candidate2 = agent_workspace / relative_path
                        if candidate2.exists():
                            return str(candidate2)
        
        # If path doesn't match virtual prefixes, check if it exists as-is (might be already host path)
        if os.path.exists(virtual_path):
            return virtual_path
        
        # Try relative to agent workspace
        direct_path = agent_workspace / virtual_path.lstrip("/")
        if direct_path.exists():
            return str(direct_path)
        
        logger.warning(f"[AgentClient] Could not convert virtual path to host path: {virtual_path}")
        return None
    
    async def _send_files_to_im(self, file_paths: List[str], agent_id: str, 
                                provider: str, user_id: str, chat_id: Optional[str]) -> List[Dict[str, Any]]:
        """
        Send files to IM user.
        
        Args:
            file_paths: List of file paths (virtual or host paths)
            agent_id: Agent ID for path conversion
            provider: IM provider name
            user_id: User ID
            chat_id: Chat ID (optional)
            
        Returns:
            List of send results
        """
        # Ensure import is attempted
        if not _ensure_send_file_import():
            logger.warning("[AgentClient] send_file_through_im not available, cannot send files")
            return []
        
        results = []
        for virtual_path in file_paths:
            # Convert to host path
            host_path = self._convert_virtual_to_host_path(virtual_path, agent_id)
            if not host_path:
                logger.warning(f"[AgentClient] Skipping file (path not found): {virtual_path}")
                continue
            
            try:
                logger.info(f"[AgentClient] Sending file to {provider}: {host_path}")
                result = await send_file_through_im(
                    file_path=host_path,
                    provider=provider,
                    agent_id=agent_id,
                    user_id=user_id,
                    chat_id=chat_id
                )
                results.append({
                    "virtual_path": virtual_path,
                    "host_path": host_path,
                    "result": result
                })
                logger.info(f"[AgentClient] File send result: {result}")
            except Exception as e:
                logger.error(f"[AgentClient] Failed to send file {host_path}: {e}")
                results.append({
                    "virtual_path": virtual_path,
                    "host_path": host_path,
                    "error": str(e)
                })
        
        # Send confirmation message after files are sent
        success_count = len([r for r in results if not r.get("error")])
        if success_count > 0:
            try:
                await self._send_confirmation_message(
                    agent_id=agent_id,
                    provider=provider,
                    user_id=user_id,
                    chat_id=chat_id,
                    success_count=success_count,
                    failed_count=len(results) - success_count
                )
            except Exception as e:
                logger.error(f"[AgentClient] Failed to send confirmation message: {e}")
        
        return results
    
    async def _send_confirmation_message(self, agent_id: str, provider: str, 
                                         user_id: str, chat_id: Optional[str],
                                         success_count: int, failed_count: int) -> None:
        """
        Send confirmation message after files are sent.
        
        Args:
            agent_id: Agent ID for configuration lookup
            provider: IM provider name
            user_id: User ID
            chat_id: Chat ID (optional)
            success_count: Number of successfully sent files
            failed_count: Number of failed file sends
        """
        try:
            from mcp_servers.im_server.im_server import send_message_through_im
            
            # Construct confirmation message
            if success_count == 1:
                message = "📎 文件已发送成功！请查收。"
            else:
                message = f"📎 {success_count} 个文件已发送成功！请查收。"
            
            if failed_count > 0:
                message += f"\n⚠️ {failed_count} 个文件发送失败，请稍后重试。"
            
            logger.info(f"[AgentClient] Sending confirmation message to {provider}, user={user_id}")
            
            # Call send_message_through_im with correct parameter order
            result = await send_message_through_im(
                message,      # content
                provider,     # provider
                agent_id,     # agent_id
                user_id,      # user_id
                chat_id       # chat_id
            )
            logger.info(f"[AgentClient] Confirmation message result: {result}")
            
        except Exception as e:
            logger.error(f"[AgentClient] Failed to send confirmation message: {e}", exc_info=True)
    
    def _create_message_chunk(self, data: Dict[str, Any]) -> Optional[Any]:
        """Create MessageChunk from response data."""
        if not MessageChunk:
            return None
        
        # Extract fields
        role = data.get("role")
        if not role:
            return None
        
        content = data.get("content")
        tool_calls = data.get("tool_calls")
        message_id = data.get("message_id")
        
        # Skip empty messages
        if not content and not tool_calls:
            return None
        
        try:
            return MessageChunk(
                role=role,
                content=content,
                tool_calls=tool_calls,
                message_id=message_id,
                type=data.get("type", "normal"),
                metadata=data.get("metadata", {})
            )
        except Exception as e:
            logger.warning(f"Failed to create MessageChunk: {e}")
            return None
    
    def _parse_stream_response_fallback(self, response: httpx.Response) -> List[Dict[str, Any]]:
        """Fallback parsing when Sage message classes are not available."""
        messages = []  # Simple dict-based messages
        
        for line in response.iter_lines():
            if not line:
                continue
                
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            
            msg_type = data.get("type")
            if msg_type in ("chunk_start", "chunk_end", "json_chunk"):
                continue
            
            role = data.get("role")
            if not role:
                continue
            
            # Simple message accumulation
            content = data.get("content", "")
            tool_calls = data.get("tool_calls", [])
            message_id = data.get("message_id", "unknown")
            
            # Find existing message with same ID
            existing = None
            for msg in messages:
                if msg.get("message_id") == message_id:
                    existing = msg
                    break
            
            if existing:
                # Append content
                if content:
                    existing["content"] = (existing.get("content") or "") + content
                # Merge tool calls
                if tool_calls:
                    existing["tool_calls"] = existing.get("tool_calls", []) + tool_calls
            else:
                messages.append({
                    "role": role,
                    "content": content,
                    "tool_calls": tool_calls,
                    "message_id": message_id
                })
        
        return messages
    
    async def _send_progress_message(
        self,
        message: str,
        provider: str,
        agent_id: str,
        user_id: Optional[str],
        chat_id: Optional[str]
    ) -> None:
        """
        Send a progress message to IM user during agent processing.
        
        Args:
            message: Progress message content
            provider: IM provider name
            agent_id: Agent ID
            user_id: User ID
            chat_id: Chat ID (optional)
        """
        try:
            from mcp_servers.im_server.im_server import send_message_through_im
            
            logger.info(f"[AgentClient] Sending progress message: {message}")
            
            result = await send_message_through_im(
                message,
                provider,
                agent_id,
                user_id,
                chat_id
            )
            
            # Small delay to ensure message order
            await asyncio.sleep(0.5)
            
            logger.debug(f"[AgentClient] Progress message result: {result}")
            
        except Exception as e:
            logger.warning(f"[AgentClient] Failed to send progress message: {e}")
    
    def _generate_step_description(self, tool_name: str, arguments: str, step_num: int) -> str:
        """
        Generate human-readable description for a tool execution step.
        
        Args:
            tool_name: Name of the tool being called
            arguments: JSON string of tool arguments
            step_num: Step number in execution sequence
            
        Returns:
            Human-readable description of what the step does
        """
        try:
            args = json.loads(arguments) if arguments else {}
        except json.JSONDecodeError:
            args = {}
        
        # Dynamic descriptions based on tool and arguments
        descriptions = {
            "file_write": lambda: f"创建文件 `{args.get('file_path', '未知文件')}`",
            "file_update": lambda: f"更新文件 `{args.get('file_path', '未知文件')}`",
            "file_read": lambda: f"读取文件 `{args.get('file_path', '未知文件')}`",
            "execute_shell_command": lambda: f"执行命令 `{args.get('command', '未知命令')[:30]}...`" if len(args.get('command', '')) > 30 else f"执行命令 `{args.get('command', '未知命令')}`",
            "execute_python_code": lambda: f"执行 Python 代码 ({len(args.get('code', ''))} 字符)",
            "search_web_page": lambda: f"搜索: {args.get('keyword', '未知关键词')}",
            "fetch_webpages": lambda: f"获取网页: {args.get('url', '未知URL')[:40]}..." if len(args.get('url', '')) > 40 else f"获取网页: {args.get('url', '未知URL')}",
            "todo_write": lambda: f"更新任务列表",
            "todo_read": lambda: f"查看任务列表",
            "list_tasks": lambda: f"列出所有任务",
            "add_task": lambda: f"添加任务: {args.get('title', '未命名')}",
            "sys_spawn_agent": lambda: f"创建子智能体: {args.get('name', '未命名')}",
            "sys_delegate_task": lambda: f"分配任务给子智能体",
            "sys_finish_task": lambda: f"完成任务",
            "load_skill": lambda: f"加载技能: {args.get('skill_name', '未知技能')}",
            "search_memory": lambda: f"搜索记忆: {args.get('query', '未知查询')}",
            "generate_image": lambda: f"生成图片: {args.get('prompt', '未指定')[:30]}..." if len(args.get('prompt', '')) > 30 else f"生成图片: {args.get('prompt', '未指定')}",
            "send_message_through_im": lambda: f"发送 IM 消息",
            "send_file_through_im": lambda: f"发送文件",
        }
        
        # Get dynamic description or use default
        if tool_name in descriptions:
            return descriptions[tool_name]()
        else:
            # For unknown tools, show name with underscores replaced
            readable_name = tool_name.replace('_', ' ')
            return f"执行 {readable_name}"
    
    def _extract_tool_info(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extract tool call information from stream data."""
        # Check for delta format (OpenAI streaming)
        delta = data.get("delta")
        if delta and isinstance(delta, dict):
            tool_calls = delta.get("tool_calls")
            if tool_calls:
                data = delta
        
        # Check for tool_calls in various formats
        tool_calls = data.get("tool_calls")
        
        # Also check for tool_call field (singular)
        if not tool_calls:
            tool_call = data.get("tool_call")
            if tool_call:
                tool_calls = [tool_call]
        
        # Check for function_call (older format)
        if not tool_calls:
            function_call = data.get("function_call")
            if function_call:
                return {
                    "name": function_call.get("name"),
                    "arguments": function_call.get("arguments", "{}")
                }
        
        if not tool_calls:
            return None
        
        if isinstance(tool_calls, list) and len(tool_calls) > 0:
            tool_call = tool_calls[0]
            if isinstance(tool_call, dict):
                function = tool_call.get("function", {})
                name = function.get("name") or tool_call.get("name")
                arguments = function.get("arguments") or tool_call.get("arguments", "{}")
                if name:
                    return {
                        "name": name,
                        "arguments": arguments
                    }
        return None
    
    async def send_message(
        self,
        session_id: str,
        agent_id: str,
        content: str,
        user_id: str = "im_user",
        user_name: Optional[str] = None,
        chat_id: Optional[str] = None,
        provider: str = "unknown",
        force_summary: bool = True,
        file_info: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Async version of send_message with real-time progress updates.

        Args:
            session_id: Sage session ID
            agent_id: Agent ID to send to
            content: Message content
            user_id: User identifier
            user_name: Display name of the user
            chat_id: Chat/Group ID (optional)
            provider: IM provider name (for context)
            force_summary: Whether to force summary generation
            file_info: File information dict (optional) - {name, size, mime_type, local_path}

        Returns:
            Dict with 'success', 'has_im_tool', 'response' (optional), or 'error'
        """
        try:
            # Add platform context to content with comprehensive information
            is_file_message = file_info is not None
            
            if is_file_message:
                platform_info = f"【IM文件消息 - 平台: {provider}"
            else:
                platform_info = f"【IM消息 - 平台: {provider}"
            
            if user_name:
                platform_info += f", 用户: {user_name}"
            else:
                platform_info += ", 用户：未知"

            if user_id:
                platform_info += f", 用户ID: {user_id}"
            if chat_id:
                platform_info += f", 群聊ID: {chat_id}"
            platform_info += "】\n\n"

            # 构建消息内容 - 始终提供完整的工具提示
            if is_file_message:
                file_desc = f"文件名: {file_info.get('name', 'unknown')}\n"
                file_desc += f"文件大小: {file_info.get('size', 0)} 字节\n"
                file_desc += f"文件类型: {file_info.get('mime_type', 'unknown')}\n"
                file_desc += f"本地路径: {file_info.get('local_path', 'unknown')}\n"
                
                full_content = platform_info + content + "\n" + file_desc
            else:
                full_content = platform_info + content
            
            # 统一添加工具使用提示
            full_content += f"\n\n【可用工具】"
            full_content += f"\n- 发送文本: send_message_through_im(provider='{provider}', agent_id='{agent_id}', user_id='{user_id or ''}', chat_id='{chat_id or ''}', content='消息内容')"
            full_content += f"\n- 发送文件: send_file_through_im(provider='{provider}', agent_id='{agent_id}', user_id='{user_id or ''}', chat_id='{chat_id or ''}', file_path='文件的绝对路径')"
            
            # 添加 IM 交互指南
            full_content += f"\n\n【IM 交互指南】"
            full_content += f"\n你可以自主决定何时向用户发送消息："
            full_content += f"\n1. 任务较简单：直接处理，最后一次性返回结果"
            full_content += f"\n2. 任务较复杂/耗时长：可以先用 send_message_through_im 发送进度消息（如'正在搜索相关资料...'），让用户知道你在工作"
            full_content += f"\n3. 多步骤任务：可以在关键步骤完成后发送进度更新"
            full_content += f"\n4. 需要用户等待时：主动告知预计等待时间或当前进展"
            full_content += f"\n\n注意：不要过度发送消息，保持自然、友好的沟通节奏。"
            
            payload = {
                "agent_id": agent_id,
                "messages": [{"role": "user", "content": full_content}],
                "session_id": session_id,
                "force_summary": force_summary,
            }
            
            logger.info(f"Sending async message to agent {agent_id}...")
            
            chunks = []
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/api/chat",
                    json=payload,
                    headers={"X-Sage-Internal-UserId": "im_client"}
                ) as response:
                    response.raise_for_status()
                    
                    # Process stream and collect chunks
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        
                        chunks.append(line)
                        
                        try:
                            data = json.loads(line)
                            logger.debug(f"[AgentClient] Stream data: {data}")
                        except json.JSONDecodeError:
                            continue
            
            # Stream ended - create mock response and parse
            class MockResponse:
                def __init__(self, chunks):
                    self._chunks = chunks
                def iter_lines(self):
                    return iter(self._chunks)
            
            mock_response = MockResponse(chunks)
            messages = self._parse_stream_response(mock_response)
            
            # Stream ended - now analyze the collected messages
            logger.debug(f"[AgentClient] Collected {len(messages)} messages from stream")
            for i, msg in enumerate(messages):
                logger.debug(f"[AgentClient] Message {i}: role={msg.get('role') if isinstance(msg, dict) else getattr(msg, 'role', 'unknown')}, "
                           f"content_length={len(msg.get('content', '')) if isinstance(msg, dict) else len(getattr(msg, 'content', '') or '')}")
            
            has_im_tool = self._check_im_tool_in_messages(messages)
            response_text = self._extract_last_assistant_response(messages, has_im_tool)
            
            logger.debug(f"[AgentClient] Analysis result: has_im_tool={has_im_tool}, response_length={len(response_text)}")
            
            # Wait a bit to ensure progress messages arrive before final response
            await asyncio.sleep(1)
            
            if has_im_tool:
                logger.info("[AgentClient] Agent called send_message_through_im tool, no text response needed")
                return {
                    "success": True,
                    "has_im_tool": True,
                    "response": None
                }
            else:
                logger.info(f"[AgentClient] Agent response received. Length: {len(response_text)}")
                if response_text:
                    logger.debug(f"[AgentClient] Response preview: {response_text[:100]}...")
                return {
                    "success": True,
                    "has_im_tool": False,
                    "response": response_text
                }
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to send async message to agent: {error_msg}")
            return {"success": False, "error": error_msg}
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Check if Agent API is accessible.
        
        Returns:
            Dict with 'success' and 'status' or 'error'
        """
        try:
            async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
                response = await client.get(
                    f"{self.base_url}/health",
                    headers={"X-Sage-Internal-UserId": "im_client"},
                )
                response.raise_for_status()
                return {"success": True, "status": "healthy"}
        except Exception as e:
            return {"success": False, "error": str(e)}


# Global client instance
_agent_client: Optional[AgentClient] = None


def get_agent_client() -> AgentClient:
    """Get or create global Agent client instance."""
    global _agent_client
    if _agent_client is None:
        _agent_client = AgentClient()
    return _agent_client

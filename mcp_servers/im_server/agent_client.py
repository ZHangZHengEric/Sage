"""Agent Client for IM Server.

Provides unified interface to communicate with Sage Agent via API.
"""

import os
import json
import logging
from typing import Optional, Dict, Any, List

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
    
    async def send_message(
        self,
        session_id: str,
        agent_id: str,
        content: str,
        user_id: str = "im_user",
        user_name: Optional[str] = None,
        provider: str = "unknown",
        force_summary: bool = True
    ) -> Dict[str, Any]:
        """
        Async version of send_message.
        
        Args:
            session_id: Sage session ID
            agent_id: Agent ID to send to
            content: Message content
            user_id: User identifier
            user_name: Display name of the user
            provider: IM provider name (for context)
            force_summary: Whether to force summary generation
            
        Returns:
            Dict with 'success', 'has_im_tool', 'response' (optional), or 'error'
        """
        try:
            # Add platform context to content
            platform_info = f"【来自IM: {provider}"
            if user_name:
                platform_info += f" - {user_name}"
            platform_info += "】\n\n"
            
            full_content = platform_info + content +"\n(P.S. 过程中使用 send_message_through_im 工具与用户进行IM互动)"
            
            payload = {
                "agent_id": agent_id,
                "messages": [{"role": "user", "content": full_content}],
                "session_id": session_id,
                "force_summary": force_summary,
                # "user_id": user_id,
            }
            
            logger.info(f"Sending async message to agent {agent_id}...")
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/api/chat",
                    json=payload,
                    headers={"X-Sage-Internal-UserId": "im_client"}
                ) as response:
                    response.raise_for_status()
                    
                    # Collect all chunks
                    chunks = []
                    async for line in response.aiter_lines():
                        if line:
                            chunks.append(line)
            
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
    
    def health_check(self) -> Dict[str, Any]:
        """
        Check if Agent API is accessible.
        
        Returns:
            Dict with 'success' and 'status' or 'error'
        """
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(f"{self.base_url}/health", headers={"X-Sage-Internal-UserId": "im_client"})
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

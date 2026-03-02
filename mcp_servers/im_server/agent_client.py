"""Agent Client for IM Server.

Provides unified interface to communicate with Sage Agent via API.
"""

import os
import json
import logging
from typing import Optional, Dict, Any

import httpx

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
    
    def _parse_stream_response(self, response: httpx.Response) -> str:
        """
        Parse streaming response from Sage API.
        
        Handles chunked JSON responses and extracts assistant content.
        
        Args:
            response: HTTPX response object
            
        Returns:
            Extracted content string
        """
        buffer = {}
        full_content = []
        
        for line in response.iter_lines():
            if not line:
                continue
                
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
                
            msg_type = data.get("type")
            
            if msg_type == "chunk_start":
                total_chunks = data.get("total_chunks", 0)
                if total_chunks > 0:
                    buffer[data["message_id"]] = [""] * total_chunks
                continue
                
            elif msg_type == "json_chunk":
                msg_id = data.get("message_id")
                idx = data.get("chunk_index")
                if msg_id in buffer and idx is not None:
                    if idx < len(buffer[msg_id]):
                        buffer[msg_id][idx] = data.get("chunk_data", "")
                continue
                
            elif msg_type == "chunk_end":
                msg_id = data.get("message_id")
                if msg_id in buffer:
                    full_json_str = "".join(buffer[msg_id])
                    del buffer[msg_id]
                    try:
                        obj = json.loads(full_json_str)
                        if obj.get("role") == "assistant" and obj.get("content"):
                            content = obj.get("content")
                            if isinstance(content, str):
                                full_content.append(content)
                    except json.JSONDecodeError:
                        pass
                continue
                
            # Direct message format
            role = data.get("role")
            content = data.get("content")
            if role == "assistant" and content and isinstance(content, str):
                full_content.append(content)
                
        return "".join(full_content)
    
    def send_message(
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
        Send message to agent and get response.
        
        Args:
            session_id: Sage session ID
            agent_id: Agent ID to send to
            content: Message content
            user_id: User identifier
            user_name: Display name of the user
            provider: IM provider name (for context)
            force_summary: Whether to force summary generation
            
        Returns:
            Dict with 'success' and 'response' or 'error'
        """
        try:
            # Add platform context to content
            platform_info = f"【来自 {provider}"
            if user_name:
                platform_info += f" - {user_name}"
            platform_info += "】\n\n"
            
            full_content = platform_info + content
            
            payload = {
                "agent_id": agent_id,
                "messages": [{"role": "user", "content": full_content}],
                "session_id": session_id,
                "force_summary": force_summary,
                "user_id": user_id,
            }
            
            logger.info(f"Sending message to agent {agent_id} at {self.base_url}...")
            
            full_response_text = ""
            
            with httpx.Client(timeout=self.timeout) as client:
                with client.stream(
                    "POST", 
                    f"{self.base_url}/api/chat", 
                    json=payload
                ) as response:
                    response.raise_for_status()
                    full_response_text = self._parse_stream_response(response)
                    
            logger.info(f"Agent response received. Length: {len(full_response_text)}")
            return {
                "success": True,
                # "response": full_response_text
            }
            
        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP error {e.response.status_code}: {e.response.text}"
            logger.error(f"Failed to send message to agent: {error_msg}")
            return {"success": False, "error": error_msg}
            
        except httpx.RequestError as e:
            error_msg = f"Request error: {str(e)}"
            logger.error(f"Failed to send message to agent: {error_msg}")
            return {"success": False, "error": error_msg}
            
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            logger.error(f"Failed to send message to agent: {error_msg}")
            return {"success": False, "error": error_msg}
    
    async def send_message_async(
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
            Dict with 'success' and 'response' or 'error'
        """
        try:
            # Add platform context to content
            platform_info = f"【来自 {provider}"
            if user_name:
                platform_info += f" - {user_name}"
            platform_info += "】\n\n"
            
            full_content = platform_info + content
            
            payload = {
                "agent_id": agent_id,
                "messages": [{"role": "user", "content": full_content}],
                "session_id": session_id,
                "force_summary": force_summary,
                "user_id": user_id,
            }
            
            logger.info(f"Sending async message to agent {agent_id}...")
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/api/chat",
                    json=payload
                ) as response:
                    response.raise_for_status()
                    
                    # Collect all chunks
                    chunks = []
                    async for line in response.aiter_lines():
                        if line:
                            chunks.append(line)
                            
                    # Parse response
                    full_response = self._parse_stream_response_from_chunks(chunks)
                    
            logger.info(f"Agent async response received. Length: {len(full_response)}")
            return {
                "success": True,
                "response": full_response
            }
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to send async message to agent: {error_msg}")
            return {"success": False, "error": error_msg}
    
    def _parse_stream_response_from_chunks(self, chunks: list) -> str:
        """Parse stream response from collected chunks."""
        buffer = {}
        full_content = []
        
        for line in chunks:
            if not line:
                continue
                
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
                
            msg_type = data.get("type")
            
            if msg_type == "chunk_start":
                total_chunks = data.get("total_chunks", 0)
                if total_chunks > 0:
                    buffer[data["message_id"]] = [""] * total_chunks
                    
            elif msg_type == "json_chunk":
                msg_id = data.get("message_id")
                idx = data.get("chunk_index")
                if msg_id in buffer and idx is not None:
                    if idx < len(buffer[msg_id]):
                        buffer[msg_id][idx] = data.get("chunk_data", "")
                        
            elif msg_type == "chunk_end":
                msg_id = data.get("message_id")
                if msg_id in buffer:
                    full_json_str = "".join(buffer[msg_id])
                    del buffer[msg_id]
                    try:
                        obj = json.loads(full_json_str)
                        if obj.get("role") == "assistant" and obj.get("content"):
                            content = obj.get("content")
                            if isinstance(content, str):
                                full_content.append(content)
                    except json.JSONDecodeError:
                        pass
                        
            else:
                role = data.get("role")
                content = data.get("content")
                if role == "assistant" and content and isinstance(content, str):
                    full_content.append(content)
                    
        return "".join(full_content)
    
    def health_check(self) -> Dict[str, Any]:
        """
        Check if Agent API is accessible.
        
        Returns:
            Dict with 'success' and 'status' or 'error'
        """
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(f"{self.base_url}/health")
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

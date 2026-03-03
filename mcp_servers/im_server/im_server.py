"""IM Server MCP - Unified bidirectional messaging for all IM platforms.

Supported Platforms:
- Feishu (飞书): WebSocket mode
- DingTalk (钉钉): Stream mode  
- WeChat Work (企业微信): Webhook mode
- iMessage (macOS only): Database polling mode

Architecture:
1. All providers use unified SessionManager for state management
2. Single tool 'send_message_through_im' for all operations
3. Persistent session bindings stored in ~/.sage/im_session_bindings.json
4. Automatic message routing based on session bindings
"""

import os
import json
import logging
import threading
import asyncio
from typing import Optional, Dict, Any, List
from datetime import datetime

from mcp.server.fastmcp import FastMCP
from sagents.tool.mcp_tool_base import sage_mcp_tool

from .im_providers import get_im_provider, list_supported_providers
from .config import get_im_config, load_im_config, is_provider_enabled
from .session_manager import get_session_manager
from .agent_client import get_agent_client, AgentClient

# iMessage support (macOS only)
import platform
if platform.system() == "Darwin":
    try:
        from .providers.imessage import get_imessage_manager, iMessageManager
        IMESSAGE_AVAILABLE = True
    except ImportError:
        IMESSAGE_AVAILABLE = False
else:
    IMESSAGE_AVAILABLE = False

# Feishu WebSocket support
try:
    from .providers.feishu import FeishuWebSocketClient
    FEISHU_WS_AVAILABLE = True
except ImportError:
    FEISHU_WS_AVAILABLE = False
    logger.warning("Feishu WebSocket not available, install websockets: pip install websockets")

# DingTalk Stream support
try:
    from .providers.dingtalk import DingTalkStreamClient
    DINGTALK_STREAM_AVAILABLE = True
except ImportError:
    DINGTALK_STREAM_AVAILABLE = False
    logger.warning("DingTalk Stream not available, install: pip install dingtalk-stream")

# Initialize FastMCP server
mcp = FastMCP("IM Service")

# Constants
logger = logging.getLogger("IMServer")

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


async def _send_message_to_agent(
    session_id: str,
    agent_id: str,
    content: str,
    user_id: str = "im_user",
    provider: str = "unknown",
    user_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Send a message to agent and get response."""
    client = get_agent_client()
    return await client.send_message(
        session_id=session_id,
        agent_id=agent_id,
        content=content,
        user_id=user_id,
        user_name=user_name,
        provider=provider
    )


@mcp.tool()
@sage_mcp_tool(server_name="IM Service")
async def send_message_through_im(
    session_id: str,
    content: str,
) -> str:
    """
    Send message to IM user through the bound provider.

    [Effect]
    - Sends a message to IM user bound to the session
    - Session must be pre-bound to a provider and user

    [When to Use]
    - To reply to users who sent IM messages
    - To send notifications via IM

    [Workflow]
    1. User sends IM message (Feishu/DingTalk/WeChat/iMessage)
    2. System auto-creates session binding
    3. Agent receives message in the session
    4. Agent calls this tool to reply

    Args:
        session_id: Sage session ID (auto-bound when user sends first message)
        content: Message content to send

    Returns:
        Send result message

    Example:
        send_message_through_im(
            session_id="session_xxx",
            content="Hello! This is the reply."
        )
    """
    session_mgr = get_session_manager()

    # Get binding for this session
    binding = session_mgr.get_binding(session_id)
    if not binding:
        return f"Error: No IM binding found for session {session_id}. User must send message first to establish binding."

    provider_name = binding.get("provider")
    user_id_bound = binding.get("user_id")
    chat_id = binding.get("chat_id")

    # Check if provider is enabled
    if not is_provider_enabled(provider_name):
        return f"Error: Provider '{provider_name}' is not enabled"

    # Get provider config and instance
    try:
        config = get_im_config(provider_name)
        if not config:
            return f"Error: No configuration found for provider '{provider_name}'"

        provider_instance = get_im_provider(provider_name, config)
        result = await provider_instance.send_message(
            content=content,
            chat_id=chat_id,
            user_id=user_id_bound,
            msg_type="text"
        )

        if result.get("success"):
            return f"Message sent via {provider_name} to {user_id_bound}"
        else:
            return f"Error: {result.get('error')}"

    except Exception as e:
        return f"Error sending message: {str(e)}"


# --- Default Agent Resolution ---

# Cache for default agent ID
_default_agent_id: Optional[str] = None


async def get_default_agent_id() -> str:
    """
    Get the default agent ID from API.
    Gets first available agent from /api/agent/list.
    Falls back to 'default' if no agent found.
    """
    global _default_agent_id
    
    if _default_agent_id is not None:
        return _default_agent_id
    
    # Try to get first available agent from API
    try:
        import httpx
        port = os.getenv("SAGE_PORT", "8080")
        base_url = f"http://localhost:{port}"
        
        logger.info(f"[IM] Fetching agent list from {base_url}/api/agent/list")
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{base_url}/api/agent/list")
            logger.info(f"[IM] Agent list response status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"[IM] Agent list response: {data}")
                
                if (data.get("success") or data.get("code") == 200) and data.get("data"):
                    agents = data["data"]
                    if len(agents) > 0:
                        # Use first agent as default
                        first_agent = agents[0]
                        _default_agent_id = first_agent.get("id") or first_agent.get("agent_id", "default")
                        logger.info(f"[IM] Using first available agent as default: {_default_agent_id}")
                        return _default_agent_id
                    else:
                        logger.warning("[IM] Agent list is empty")
                else:
                    logger.warning(f"[IM] Agent list response invalid: success={data.get('success')}, has_data={data.get('data') is not None}")
            else:
                logger.warning(f"[IM] Agent list request failed: {response.status_code} - {response.text}")
    except Exception as e:
        logger.error(f"[IM] Failed to get agent list: {e}", exc_info=True)
    
    # Fallback to default
    logger.info("[IM] No agent found, using 'default' as fallback")
    _default_agent_id = "default"
    return _default_agent_id


def reset_default_agent_cache():
    """Reset the default agent cache. Call this when agents are modified."""
    global _default_agent_id
    _default_agent_id = None
    logger.info("[IM] Default agent cache reset")


# --- Incoming Message Handlers ---


async def handle_incoming_message(
    provider: str,
    user_id: str,
    content: str,
    chat_id: Optional[str] = None,
    user_name: Optional[str] = None,
    default_agent_id: Optional[str] = None,
    session_webhook: Optional[str] = None,
    sender_staff_id: Optional[str] = None,
    session_webhook_expired_time: Optional[int] = None
) -> Dict[str, Any]:
    """
    Handle incoming message from any IM provider.

    This function should be called by:
    - Webhook handlers (Feishu, DingTalk, WeChat Work)
    - iMessage listener
    - Other incoming message sources

    Args:
        provider: IM provider name
        user_id: User ID in the IM platform
        content: Message content
        chat_id: Chat/Group ID (optional)
        user_name: Display name (optional)
        default_agent_id: Default agent to route to (optional, auto-detected if not provided)

    Returns:
        Dict with success status and session_id
    """
    # Get default agent ID if not provided
    if default_agent_id is None:
        default_agent_id = await get_default_agent_id()
    
    session_mgr = get_session_manager()

    # Find or create session
    session_id = session_mgr.find_or_create_session(
        provider=provider,
        user_id=user_id,
        agent_id=default_agent_id,
        chat_id=chat_id,
        user_name=user_name
    )

    # Send to agent
    result = await _send_message_to_agent(
        session_id=session_id,
        agent_id=default_agent_id,
        content=content,
        user_id=user_id,
        provider=provider,
        user_name=user_name
    )

    if result.get("success"):
        # Send response back via IM
        response = result.get("response", "")
        has_im_tool = result.get("has_im_tool", False)
        
        logger.info(f"[IM] Agent response: success=True, has_im_tool={has_im_tool}, response_length={len(response) if response else 0}")
        
        if has_im_tool:
            logger.info("[IM] Agent used send_message_through_im tool, skipping automatic response")
        elif response:
            try:
                binding = session_mgr.get_binding(session_id)
                logger.info(f"[IM] Sending response back to {provider}: chat_id={chat_id}, user_id={user_id}")
                
                if binding:
                    config = get_im_config(provider)
                    if config:
                        provider_instance = get_im_provider(provider, config)
                        logger.info(f"[IM] Calling {provider}.send_message with content length: {len(response)}")
                        
                        # Prepare send parameters
                        # Note: For DingTalk, msg_type defaults to markdown for better formatting
                        send_params = {
                            "content": response,
                            "chat_id": chat_id,
                            "user_id": user_id,
                        }
                        
                        # Add session_webhook for DingTalk (if available)
                        if provider == "dingtalk":
                            # Default to markdown for DingTalk
                            send_params["msg_type"] = "markdown"
                            if session_webhook:
                                send_params["session_webhook"] = session_webhook
                            if sender_staff_id:
                                send_params["sender_staff_id"] = sender_staff_id
                            if session_webhook_expired_time:
                                send_params["session_webhook_expired_time"] = session_webhook_expired_time
                        else:
                            # Other providers use text by default
                            send_params["msg_type"] = "text"
                        
                        send_result = await provider_instance.send_message(**send_params)
                        logger.info(f"[IM] send_message result: {send_result}")
                    else:
                        logger.error(f"[IM] No config found for provider: {provider}")
                else:
                    logger.error(f"[IM] No binding found for session: {session_id}")
            except Exception as e:
                logger.error(f"[IM] Failed to send response back: {e}", exc_info=True)
        else:
            logger.warning("[IM] Agent returned empty response")

        return {"success": True, "session_id": session_id}
    else:
        return {"success": False, "error": result.get("error")}


# --- Background Tasks ---


async def _imessage_background_task():
    """Background task to process incoming iMessage messages."""
    if not IMESSAGE_AVAILABLE:
        return

    # Get iMessage config with allowed_senders whitelist
    im_config = get_im_config("imessage") or {}
    im_mgr = get_imessage_manager(config=im_config)
    im_mgr.start()

    while True:
        try:
            messages = im_mgr.get_pending_messages()

            for msg in messages:
                await handle_incoming_message(
                    provider="imessage",
                    user_id=msg.get("sender"),
                    content=msg.get("content")
                )

            await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Error in iMessage background task: {e}")
            await asyncio.sleep(5)


def _handle_feishu_message(message: Dict[str, Any]):
    """Handle incoming Feishu message from WebSocket."""
    import asyncio
    
    # Run async handler in sync context
    # Note: Feishu SDK runs in its own thread, so we need to use the main event loop
    try:
        # Get the main event loop (from the main thread)
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Use run_coroutine_threadsafe to safely schedule from another thread
            asyncio.run_coroutine_threadsafe(
                handle_incoming_message(
                    provider="feishu",
                    user_id=message.get("user_id"),
                    content=message.get("content", {}).get("text", ""),
                    chat_id=message.get("chat_id"),
                    user_name=message.get("user_name")
                ),
                loop
            )
            logger.info(f"[Feishu] Scheduled message handling in main loop: {message.get('content', {}).get('text', '')[:50]}...")
    except Exception as e:
        logger.error(f"[Feishu] Error handling message: {e}", exc_info=True)


async def _start_feishu_websocket():
    """Start Feishu WebSocket listener."""
    if not FEISHU_WS_AVAILABLE:
        logger.info("Feishu WebSocket not available")
        return
    
    config = get_im_config("feishu")
    if not config:
        logger.info("Feishu not configured")
        return
    
    if not config.get("enabled"):
        logger.info("Feishu not enabled")
        return
    
    app_id = config.get("app_id")
    app_secret = config.get("app_secret")
    
    if not app_id or not app_secret:
        logger.warning("Feishu app_id or app_secret not configured")
        return
    
    try:
        client = FeishuWebSocketClient(app_id, app_secret, _handle_feishu_message)
        client.start()  # This now starts its own thread internally
        
        logger.info("Feishu WebSocket listener started")
        
        # Keep the task alive
        while True:
            await asyncio.sleep(60)
            
    except Exception as e:
        logger.error(f"Feishu WebSocket error: {e}")


async def initialize_im_server():
    """Initialize IM server and start background tasks."""
    logger.info("Initializing IM server...")

    # Load configuration first
    logger.info("[IM Server] Loading IM configuration...")
    from .config import load_im_config
    config = await load_im_config()
    if not config:
        logger.error("[IM Server] Failed to load IM configuration")
        return

    logger.info(f"[IM Server] IM configuration loaded: {config}")

    # Start iMessage background task (if configured)
    if IMESSAGE_AVAILABLE:
        im_config = get_im_config("imessage")
        if im_config and im_config.get("enabled"):
            asyncio.create_task(_imessage_background_task())
            logger.info("iMessage background task started")

    # Start Feishu WebSocket listener (if configured)
    if FEISHU_WS_AVAILABLE:
        asyncio.create_task(_start_feishu_websocket())

    # Start DingTalk Stream listener (if configured)
    if DINGTALK_STREAM_AVAILABLE:
        asyncio.create_task(_start_dingtalk_stream())

    logger.info("IM server initialized")


async def _start_dingtalk_stream():
    """Start DingTalk Stream listener."""
    if not DINGTALK_STREAM_AVAILABLE:
        logger.info("DingTalk Stream not available")
        return

    config = get_im_config("dingtalk")
    if not config:
        logger.info("DingTalk not configured")
        return

    if not config.get("enabled"):
        logger.info("DingTalk not enabled")
        return

    # Support both client_id/client_secret and app_key/app_secret
    client_id = config.get("client_id") or config.get("app_key")
    client_secret = config.get("client_secret") or config.get("app_secret")

    if not client_id or not client_secret:
        logger.warning("DingTalk client_id/app_key or client_secret/app_secret not configured")
        return

    try:
        client = DingTalkStreamClient(client_id, client_secret, _handle_dingtalk_message)
        client.start()
        logger.info("DingTalk Stream listener started")

        # Keep the task alive
        while True:
            await asyncio.sleep(60)

    except Exception as e:
        logger.error(f"DingTalk Stream error: {e}")


def _handle_dingtalk_message(message: Dict[str, Any]):
    """Handle incoming DingTalk message from Stream."""
    import asyncio

    # Run async handler in sync context
    # Note: DingTalk SDK runs in its own thread, so we need to use the main event loop
    try:
        # Get the main event loop (from the main thread)
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Use run_coroutine_threadsafe to safely schedule from another thread
            asyncio.run_coroutine_threadsafe(
                handle_incoming_message(
                    provider="dingtalk",
                    user_id=message.get("user_id"),
                    content=message.get("content", {}).get("text", ""),
                    chat_id=message.get("chat_id"),
                    user_name=message.get("user_name"),
                    session_webhook=message.get("session_webhook"),
                    sender_staff_id=message.get("sender_staff_id"),
                    session_webhook_expired_time=message.get("session_webhook_expired_time")
                ),
                loop
            )
            logger.info(f"[DingTalk] Scheduled message handling in main loop: {message.get('content', {}).get('text', '')[:50]}...")
    except Exception as e:
        logger.error(f"[DingTalk] Error handling message: {e}", exc_info=True)


# Note: This module is imported by ToolManager, not run directly
# The initialize_im_server() should be called by the main application
# when it starts up, not here.

# Example usage in main application:
# from mcp_servers.im_server.im_server import initialize_im_server
# asyncio.create_task(initialize_im_server())

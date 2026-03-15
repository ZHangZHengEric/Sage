"""IM Server MCP - Unified bidirectional messaging for all IM platforms.

Supported Platforms:
- Feishu (飞书): WebSocket mode
- DingTalk (钉钉): Stream mode
- WeChat Work (企业微信): Webhook mode
- iMessage (macOS only): Database polling mode

Architecture:
1. All providers use unified SessionManager for state management
2. Single tool 'send_message_through_im' for all operations
3. Persistent session bindings stored in SQLite database
4. Automatic message routing based on session bindings
5. Multi-tenant: Each Sage user can have their own IM configurations
"""

import os
import logging
from typing import Optional, Dict, Any

from mcp.server.fastmcp import FastMCP
from sagents.tool.mcp_tool_base import sage_mcp_tool

from .im_providers import get_im_provider
from .db import get_im_db
from .session_manager import get_session_manager
from .agent_client import get_agent_client
from .service_manager import get_service_manager

# Constants
logger = logging.getLogger("IMServer")

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# Initialize FastMCP server
mcp = FastMCP("IM Service")

# Register file tools
try:
    from .tools.file_tools import register_file_tools
    register_file_tools(mcp)
    logger.info("[IM Server] File tools registered")
except Exception as e:
    logger.warning(f"[IM Server] Failed to register file tools: {e}")

# Default Sage user ID for desktop app
DEFAULT_SAGE_USER_ID = "desktop_default_user"


def is_provider_enabled(provider: str) -> bool:
    """Check if a provider is enabled for the default user."""
    db = get_im_db()
    config = db.get_user_config(DEFAULT_SAGE_USER_ID, provider)
    enabled = config.get("enabled", False) if config else False
    logger.info(f"[IM Tool] Checking provider {provider}: enabled={enabled}, config={config}")
    return enabled


def get_provider_config(provider: str) -> Optional[Dict[str, Any]]:
    """Get provider config for the default user."""
    db = get_im_db()
    config_data = db.get_user_config(DEFAULT_SAGE_USER_ID, provider)
    if config_data:
        return config_data.get("config", {})
    return None


async def _send_message_to_agent(
    session_id: str,
    agent_id: str,
    content: str,
    user_id: str = "im_user",
    provider: str = "unknown",
    user_name: Optional[str] = None,
    file_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Send a message to agent and get response."""
    client = get_agent_client()
    return await client.send_message(
        session_id=session_id,
        agent_id=agent_id,
        content=content,
        user_id=user_id,
        user_name=user_name,
        provider=provider,
        file_info=file_info
    )


@mcp.tool()
@sage_mcp_tool(server_name="IM Service")
async def send_message_through_im(
    content: str,
    provider: str,
    user_id: Optional[str] = None,
    chat_id: Optional[str] = None,
) -> str:
    """向 IM 用户发送消息。支持飞书、钉钉、企业微信、iMessage。

    参数:
        content: 消息内容
        provider: 平台名称 - feishu(飞书)、dingtalk(钉钉)、wechat_work(企业微信)、imessage
        user_id: 用户ID（私聊必填）- 飞书:user_id, 钉钉:user_id, 企业微信:user_id, iMessage:手机号/邮箱
        chat_id: 群聊ID（群聊必填）

    示例:
        send_message_through_im(provider="feishu", user_id="ou_xxx", content="你好")
        send_message_through_im(provider="dingtalk", chat_id="chat_xxx", content="群消息")
        send_message_through_im(provider="wechat_work", user_id="userid_xxx", content="企业微信消息")
        send_message_through_im(provider="imessage", user_id="+86xxx", content="iMessage")
    """
    logger.info(f"[IM Tool] send_message_through_im called: provider={provider}, user_id={user_id}, chat_id={chat_id}, content_length={len(content) if content else 0}")

    # Validate required parameters
    if not content:
        logger.warning("[IM Tool] Error: content is required")
        return "Error: content is required"

    if not provider:
        logger.warning("[IM Tool] Error: provider is required")
        return "Error: provider is required"

    if not user_id and not chat_id:
        logger.warning("[IM Tool] Error: either user_id or chat_id is required")
        return "Error: either user_id or chat_id is required"

    # Use provided parameters directly
    provider_name = provider
    target_user_id = user_id
    target_chat_id = chat_id

    logger.info(f"[IM Tool] Processing message: provider={provider_name}, user_id={target_user_id}, chat_id={target_chat_id}")

    # Check if provider is enabled
    logger.info(f"[IM Tool] Checking if provider {provider_name} is enabled...")
    if not is_provider_enabled(provider_name):
        logger.error(f"[IM Tool] Provider '{provider_name}' is not enabled")
        return f"Error: Provider '{provider_name}' is not enabled"

    logger.info(f"[IM Tool] Provider {provider_name} is enabled, getting config...")

    # Get provider config and instance
    try:
        config = get_provider_config(provider_name)
        logger.info(f"[IM Tool] Got provider config: {config}")
        if not config:
            logger.error(f"[IM Tool] No configuration found for provider '{provider_name}'")
            return f"Error: No configuration found for provider '{provider_name}'"

        logger.info(f"[IM Tool] Creating provider instance for {provider_name}...")
        provider_instance = get_im_provider(provider_name, config)
        logger.info("[IM Tool] Provider instance created, sending message...")

        # WeChat Work aibot_send_msg only supports markdown, others support text
        msg_type = "markdown" if provider_name == "wechat_work" else "text"
        result = await provider_instance.send_message(
            content=content,
            chat_id=target_chat_id,
            user_id=target_user_id,
            msg_type=msg_type
        )

        logger.info(f"[IM Tool] send_message result: {result}")

        if result.get("success"):
            target = f"group {target_chat_id}" if target_chat_id else f"user {target_user_id}"
            logger.info(f"[IM Tool] Message sent successfully to {target}")
            return f"Message sent via {provider_name} to {target}"
        else:
            error = result.get('error', 'Unknown error')
            logger.error(f"[IM Tool] Failed to send message: {error}")
            return f"Error: {error}"

    except Exception as e:
        logger.error(f"[IM Tool] Exception sending message: {e}", exc_info=True)
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
    session_webhook_expired_time: Optional[int] = None,
    file_info: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Handle incoming message from any IM provider.

    This function should be called by ServiceManager when messages are received.

    Args:
        provider: IM provider name
        user_id: User ID in the IM platform
        content: Message content
        chat_id: Chat/Group ID (optional)
        user_name: Display name (optional)
        default_agent_id: Default agent to route to (optional, auto-detected if not provided)
        session_webhook: DingTalk session webhook (optional)
        sender_staff_id: DingTalk sender staff ID (optional)
        session_webhook_expired_time: DingTalk webhook expiry (optional)
        file_info: File information dict (optional) - {name, size, mime_type, local_path}

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
        user_name=user_name,
        file_info=file_info
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
                    # 首先尝试从 service_manager 获取正在运行的 provider（复用现有连接）
                    from .service_manager import get_service_manager
                    sm = get_service_manager()
                    
                    # 通过 provider + user_id 查找正在运行的 provider
                    provider_instance = sm.find_provider_by_user(provider, user_id)
                    
                    if provider_instance:
                        logger.info(f"[IM] Reusing existing provider connection for {provider}:{user_id}")
                    else:
                        # 如果没有运行的 provider，创建新实例
                        logger.warning(f"[IM] No running provider for {provider}:{user_id}, creating new instance")
                        config = get_provider_config(provider)
                        if config:
                            provider_instance = get_im_provider(provider, config)
                        else:
                            logger.error(f"[IM] No config found for provider: {provider}")
                            return {"success": True, "session_id": session_id}

                    logger.info(f"[IM] Calling {provider}.send_message with content length: {len(response)}")

                    # Prepare send parameters
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
                    elif provider == "wechat_work":
                        # WeChat Work aibot_send_msg only supports markdown/template_card
                        send_params["msg_type"] = "markdown"
                    else:
                        # Other providers use text by default
                        send_params["msg_type"] = "text"

                    send_result = await provider_instance.send_message(**send_params)
                    logger.info(f"[IM] send_message result: {send_result}")
                else:
                    logger.error(f"[IM] No binding found for session: {session_id}")
            except Exception as e:
                logger.error(f"[IM] Failed to send response back: {e}", exc_info=True)
        else:
            logger.warning("[IM] Agent returned empty response")

        return {"success": True, "session_id": session_id}
    else:
        return {"success": False, "error": result.get("error")}


# --- Server Initialization ---


async def initialize_im_server():
    """Initialize IM server and start Service Manager."""
    logger.info("=" * 50)
    logger.info("[IM Server] ========== Initializing IM Server ==========")
    logger.info("=" * 50)

    # Start service manager for multi-tenant IM management
    logger.info("[IM Server] Starting Service Manager...")
    service_manager = get_service_manager()
    await service_manager.start()
    logger.info("[IM Server] Service Manager started")

    logger.info("[IM Server] ========== IM Server Initialized ==========")
    logger.info("=" * 50)


async def reload_im_server():
    """Reload IM server configuration and restart if needed.

    This function is called when configuration is updated via API.
    """
    logger.info("[IM Server] ========== Reloading IM Server ==========")

    # Stop service manager
    service_manager = get_service_manager()
    await service_manager.stop()
    logger.info("[IM Server] Service Manager stopped")

    # Re-initialize
    await initialize_im_server()

    logger.info("[IM Server] ========== IM Server Reloaded ==========")


# Note: This module is imported by ToolManager, not run directly
# The initialize_im_server() should be called by the main application
# when it starts up, not here.

# Example usage in main application:
# from mcp_servers.im_server.im_server import initialize_im_server
# asyncio.create_task(initialize_im_server())

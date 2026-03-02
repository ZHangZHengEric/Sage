"""IM Server MCP - Send and receive messages via IM platforms (Feishu, DingTalk, WeChat Work).

Architecture:
- Feishu & DingTalk: Use WebSocket long connection (no public IP needed)
- WeChat Work: Requires webhook callback URL (needs public IP or tunneling)

TODO: Backend API Integration
- Fetch IM configurations from backend API instead of env vars
- Store session-to-IM mappings in backend
- Message history storage
"""

import os
import json
import logging
import threading
from typing import Optional, Dict, Any

import httpx
from mcp.server.fastmcp import FastMCP
from sagents.tool.mcp_tool_base import sage_mcp_tool

from .im_providers import get_im_provider
from .config import get_im_config, load_im_config

# Initialize FastMCP server
mcp = FastMCP("IM Service")

# Constants
logger = logging.getLogger("IMServer")

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# TODO: Session-to-IM mappings should be fetched from backend API
# For now, using in-memory cache
_session_im_mappings: Dict[str, Dict[str, Any]] = {}


def _get_api_base_url() -> str:
    """Get the API base URL for the Sage server."""
    port = os.getenv("SAGE_PORT", "8080")
    return f"http://localhost:{port}"


def _parse_stream_response(response: httpx.Response) -> str:
    """Parse the streaming response from Sage API."""
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

        role = data.get("role")
        content = data.get("content")
        if role == "assistant" and content and isinstance(content, str):
            full_content.append(content)

    return "".join(full_content)


def _send_message_to_agent_sync(
    session_id: str,
    agent_id: str,
    content: str,
    user_id: str = "im_user",
    provider: str = "unknown",
    user_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Synchronously send a message to agent and get response."""
    try:
        # Add platform and user info to content
        platform_info = f"【来自 {provider}"
        if user_name:
            platform_info += f" - {user_name}"
        platform_info += "】\n\n"

        full_content = platform_info + content

        payload = {
            "agent_id": agent_id,
            "messages": [{"role": "user", "content": full_content}],
            "session_id": session_id,
            "force_summary": True,
            "user_id": user_id,
        }

        api_base_url = _get_api_base_url()
        logger.info(f"Sending IM message to agent {agent_id} via API at {api_base_url}...")

        full_response_text = ""

        with httpx.Client(timeout=300.0) as client:
            with client.stream(
                "POST", f"{api_base_url}/api/chat", json=payload
            ) as response:
                response.raise_for_status()
                full_response_text = _parse_stream_response(response)

        logger.info(f"Agent response received. Length: {len(full_response_text)}")
        return {"success": True, "response": full_response_text}

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Failed to send message to agent: {error_msg}")
        return {"success": False, "error": error_msg}


# TODO: Fetch session-to-IM mapping from backend API
def _get_session_im_mapping(session_id: str) -> Optional[Dict[str, Any]]:
    """
    Get IM mapping for a session.

    TODO: Implement backend API call:
    GET /api/v1/sessions/{session_id}/im-mapping

    Returns:
        {
            "provider": "feishu",
            "chat_id": "oc_xxx",
            "user_id": "ou_xxx",
            "webhook_url": "..."  # Optional
        }
    """
    return _session_im_mappings.get(session_id)


# TODO: Store session-to-IM mapping in backend API
def _set_session_im_mapping(session_id: str, mapping: Dict[str, Any]) -> None:
    """
    Store IM mapping for a session.

    TODO: Implement backend API call:
    POST /api/v1/sessions/{session_id}/im-mapping
    """
    _session_im_mappings[session_id] = mapping


# --- MCP Tools ---


@mcp.tool()
# @sage_mcp_tool(server_name="im_server")
async def send_message_through_im(
    session_id: str,
    content: str,
    msg_type: str = "text",
) -> str:
    """
    Send a message through IM platform.

    [Effect]
    - Sends a message to the configured IM platform associated with the session.

    [When to Use]
    - Use this to send notifications or messages to users via IM.
    - Use this to forward agent responses to IM users.

    Args:
        session_id: The session ID associated with this message.
        content: The message content to send.
        msg_type: Message type - 'text' or 'markdown'. Default is 'text'.

    Returns:
        Confirmation message with send status.
    """
    try:
        # TODO: Get mapping from backend API
        mapping = _get_session_im_mapping(session_id)
        if not mapping:
            return f"Error: No IM configuration bound to session '{session_id}'."

        provider_name = mapping.get("provider")
        chat_id = mapping.get("chat_id")
        user_id = mapping.get("user_id")

        # Get IM configuration
        config = get_im_config(provider_name)
        if not config:
            # Try to load config
            config = await load_im_config(provider_name)
            if not config:
                return f"Error: No configuration found for provider '{provider_name}'."

        # Send message via provider
        provider = get_im_provider(provider_name, config)
        result = await provider.send_message(
            content=content,
            chat_id=chat_id,
            user_id=user_id,
            msg_type=msg_type,
        )

        # TODO: Store message in backend API for history tracking
        # POST /api/v1/messages

        if result.get("success"):
            return f"Message sent successfully via {provider_name}."
        else:
            error = result.get("error", "Unknown error")
            return f"Error sending message: {error}"

    except Exception as e:
        return f"Error sending message: {str(e)}"


# --- WebSocket Long Connection Support (Feishu & DingTalk) ---


async def start_feishu_websocket_listener(
    app_id: str,
    app_secret: str,
    session_id: str,
    agent_id: str,
) -> None:
    """
    Start WebSocket listener for Feishu.

    Feishu supports WebSocket long connection for receiving messages
    without needing a public IP or webhook callback URL.

    TODO: Implement WebSocket connection using feishu-python-sdk
    or native websockets library.

    Reference: https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/event-subscription/overview
    """
    # TODO: Implement Feishu WebSocket event subscription
    # 1. Get tenant access token using app_id and app_secret
    # 2. Establish WebSocket connection to Feishu event gateway
    # 3. Subscribe to im.message.receive_v1 event
    # 4. Handle incoming messages and forward to agent
    logger.info(f"TODO: Implement Feishu WebSocket listener for session {session_id}")


async def start_dingtalk_stream_listener(
    app_key: str,
    app_secret: str,
    session_id: str,
    agent_id: str,
) -> None:
    """
    Start Stream listener for DingTalk.

    DingTalk Stream mode uses WebSocket for receiving messages
    without needing a public IP or webhook callback URL.

    TODO: Implement using dingtalk-stream-sdk-python

    Reference: https://open.dingtalk.com/document/resourcedownload/introduction-to-stream-mode
    """
    # TODO: Implement DingTalk Stream mode
    # 1. Use dingtalk-stream-sdk to establish connection
    # 2. Register callback for incoming messages
    # 3. Handle messages and forward to agent
    logger.info(f"TODO: Implement DingTalk Stream listener for session {session_id}")


# --- Webhook Handler (for WeChat Work and fallback) ---


async def handle_im_webhook(
    provider: str,
    data: Dict[str, Any],
    signature: Optional[str] = None,
    default_agent_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Handle incoming webhook from IM platform.

    This is used for:
    - WeChat Work (requires public IP)
    - Fallback for Feishu/DingTalk if WebSocket is not available

    This function should be called by the main Sage server when receiving
    webhook callbacks from IM platforms.

    TODO: The main Sage server should add routes:
    - POST /webhook/im/wechat_work
    - POST /webhook/im/feishu (fallback)
    - POST /webhook/im/dingtalk (fallback)
    """
    try:
        # Get config for this provider
        config = get_im_config(provider)
        if not config:
            config = await load_im_config(provider)
            if not config:
                return {"success": False, "error": f"No config for provider: {provider}"}

        # Parse incoming message
        provider_instance = get_im_provider(provider, config)
        parsed = provider_instance.parse_incoming_message(data)

        if not parsed:
            return {"success": False, "error": "Failed to parse message"}

        # Handle challenge request (Feishu)
        if parsed.get("type") == "challenge":
            return {"success": True, "challenge": parsed.get("challenge")}

        # Get message details
        content = parsed.get("content", "")
        if isinstance(content, dict):
            content = content.get("text", "")

        im_chat_id = parsed.get("chat_id")
        im_user_id = parsed.get("user_id")
        user_name = parsed.get("user_name")
        msg_provider = parsed.get("provider", provider)

        # TODO: Find or create session mapping from backend API
        # GET /api/v1/im-mappings?provider={provider}&chat_id={chat_id}&user_id={user_id}

        # For now, create a new session
        import uuid

        session_id = f"im_{provider}_{uuid.uuid4().hex[:8]}"

        # Store mapping
        _set_session_im_mapping(
            session_id,
            {
                "provider": provider,
                "chat_id": im_chat_id,
                "user_id": im_user_id,
            },
        )

        agent_id = default_agent_id
        if not agent_id:
            return {"success": False, "error": "No agent_id configured for this IM"}

        # Process message in background thread
        thread = threading.Thread(
            target=_process_incoming_message,
            args=(
                session_id,
                agent_id,
                content,
                msg_provider,
                im_chat_id,
                im_user_id,
                user_name,
            ),
            daemon=True,
        )
        thread.start()

        return {"success": True, "session_id": session_id}

    except Exception as e:
        logger.error(f"Error handling IM webhook: {e}")
        return {"success": False, "error": str(e)}


def _process_incoming_message(
    session_id: str,
    agent_id: str,
    content: str,
    provider: str,
    im_chat_id: Optional[str] = None,
    im_user_id: Optional[str] = None,
    user_name: Optional[str] = None,
) -> None:
    """Process incoming message from IM in background thread."""
    try:
        # TODO: Store incoming message in backend API
        # POST /api/v1/messages

        # Send to agent and get response
        result = _send_message_to_agent_sync(
            session_id=session_id,
            agent_id=agent_id,
            content=content,
            user_id=im_user_id or "im_user",
            provider=provider,
            user_name=user_name,
        )

        if result.get("success"):
            # Send agent response back to IM
            response = result.get("response", "")
            if response:
                # Get config
                config = get_im_config(provider)
                if config:
                    import asyncio

                    im_provider = get_im_provider(provider, config)

                    # TODO: Store outgoing message in backend API
                    # POST /api/v1/messages

                    # Send message (run async in sync context)
                    try:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        send_result = loop.run_until_complete(
                            im_provider.send_message(
                                content=response,
                                chat_id=im_chat_id,
                                user_id=im_user_id,
                                msg_type="text",
                            )
                        )
                        loop.close()

                        if not send_result.get("success"):
                            logger.error(f"Failed to send response: {send_result.get('error')}")
                    except Exception as e:
                        logger.error(f"Error sending response: {e}")

    except Exception as e:
        logger.error(f"Error processing incoming message: {e}")


# --- Startup: Initialize WebSocket listeners ---


async def initialize_im_listeners(agent_id: str) -> None:
    """
    Initialize WebSocket listeners for all configured IM platforms.

    TODO: This should be called on server startup.
    For each configured provider:
    - Feishu: Start WebSocket listener
    - DingTalk: Start Stream listener
    - WeChat Work: Skip (requires webhook)
    """
    # TODO: Fetch all IM configurations from backend API
    # GET /api/v1/im/configs

    providers = ["feishu", "dingtalk"]  # WebSocket-supported providers

    for provider in providers:
        config = await load_im_config(provider)
        if not config:
            continue

        app_id = config.get("app_id")
        app_secret = config.get("app_secret")

        if not app_id or not app_secret:
            logger.warning(f"Missing credentials for {provider}")
            continue

        if provider == "feishu":
            # TODO: Start Feishu WebSocket listener
            # await start_feishu_websocket_listener(app_id, app_secret, session_id, agent_id)
            pass
        elif provider == "dingtalk":
            # TODO: Start DingTalk Stream listener
            # await start_dingtalk_stream_listener(app_id, app_secret, session_id, agent_id)
            pass


if __name__ == "__main__":
    mcp.run()

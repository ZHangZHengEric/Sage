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
import time
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

# --- Health Check & Connection Management ---

class IMConnectionHealthMonitor:
    """
    IM 连接健康监控器
    用于监控飞书、钉钉等 IM 渠道的健康状态
    """
    
    def __init__(self, check_interval: int = 60):
        self.check_interval = check_interval  # 检查间隔（秒）
        self._last_message_time: Dict[str, float] = {}  # 各渠道最后收到消息的时间
        self._connection_status: Dict[str, bool] = {}  # 各渠道连接状态
        self._lock = threading.Lock()
        self._running = False
        self._check_task: Optional[asyncio.Task] = None
        
    def update_message_time(self, provider: str):
        """更新最后收到消息的时间"""
        with self._lock:
            self._last_message_time[provider] = time.time()
            self._connection_status[provider] = True
            
    def get_last_message_time(self, provider: str) -> Optional[float]:
        """获取最后收到消息的时间"""
        with self._lock:
            return self._last_message_time.get(provider)
            
    def set_connection_status(self, provider: str, status: bool):
        """设置连接状态"""
        with self._lock:
            self._connection_status[provider] = status
            
    def get_connection_status(self, provider: str) -> bool:
        """获取连接状态"""
        with self._lock:
            return self._connection_status.get(provider, False)
    
    def is_healthy(self, provider: str, timeout: int = 3600) -> bool:
        """
        检查渠道是否健康
        
        注意：飞书和钉钉 SDK 都有自己的重连机制，
        我们只需要检查连接状态是否已建立，不需要根据"最后消息时间"来判断。
        
        Args:
            provider: 渠道名称
            timeout: 超时时间（秒），默认1小时，主要是为了兼容
            
        Returns:
            是否健康 - 只看连接状态，不看最后消息时间
        """
        with self._lock:
            # 只看连接状态，不根据最后消息时间判断
            return self._connection_status.get(provider, False)
    
    def get_all_status(self) -> Dict[str, Dict[str, Any]]:
        """获取所有渠道的状态"""
        with self._lock:
            status = {}
            for provider in self._connection_status:
                last_time = self._last_message_time.get(provider)
                status[provider] = {
                    "connected": self._connection_status[provider],
                    "last_message_time": datetime.fromtimestamp(last_time).isoformat() if last_time else None,
                    "seconds_since_last_message": time.time() - last_time if last_time else None,
                    "healthy": self.is_healthy(provider)
                }
            return status
    
    async def start_monitoring(self):
        """启动健康检查监控"""
        self._running = True
        while self._running:
            try:
                await self._check_health()
                await asyncio.sleep(self.check_interval)
            except Exception as e:
                logger.error(f"[HealthMonitor] Error during health check: {e}")
                await asyncio.sleep(5)
    
    async def _check_health(self):
        """执行健康检查 - 只检查连接状态"""
        with self._lock:
            providers = list(self._connection_status.keys())
        
        for provider in providers:
            is_healthy = self.is_healthy(provider)
            status_str = "✓ 已连接" if is_healthy else "✗ 未连接"
            logger.info(f"[HealthMonitor] {provider}: {status_str}")
    
    def stop(self):
        """停止监控"""
        self._running = False
        if self._check_task:
            self._check_task.cancel()

# 全局健康监控器实例
_health_monitor = IMConnectionHealthMonitor()

def get_health_monitor() -> IMConnectionHealthMonitor:
    """获取健康监控器实例"""
    return _health_monitor


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
        logger.info("[iMessage] Not available, skipping")
        return

    # Get iMessage config with allowed_senders whitelist
    im_config = get_im_config("imessage") or {}
    
    # 捕获启动异常，避免阻塞其他 IM 服务
    try:
        im_mgr = get_imessage_manager(config=im_config)
        im_mgr.start()
    except Exception as e:
        logger.error(f"[iMessage] Failed to start: {e}", exc_info=True)
        logger.warning("[iMessage] Disabling iMessage to allow other IM services to work")
        # 不 return，继续运行但不处理 iMessage
        im_mgr = None

    while True:
        try:
            # 如果 iMessage 管理器没有成功启动，跳过
            if im_mgr is None:
                await asyncio.sleep(5)
                continue
                
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
    
    logger.info(f"[Feishu] ========== Received message ==========")
    logger.info(f"[Feishu] Raw message: {message}")
    
    # 更新健康监控器 - 记录收到消息的时间
    health_monitor = get_health_monitor()
    health_monitor.update_message_time("feishu")
    
    # Run async handler in sync context
    # Note: Feishu SDK runs in its own thread, so we need to use the main event loop
    try:
        # Get the main event loop (from the main thread)
        loop = asyncio.get_event_loop()
        if loop.is_running():
            logger.info(f"[Feishu] Scheduling message handling in main loop...")
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
            content = message.get("content", {})
            text = content.get("text", "") if isinstance(content, dict) else str(content)
            logger.info(f"[Feishu] Scheduled message handling: {text[:50]}...")
        else:
            logger.warning(f"[Feishu] Event loop not running, cannot schedule message")
    except Exception as e:
        logger.error(f"[Feishu] Error handling message: {e}", exc_info=True)


async def _start_feishu_websocket():
    """Start Feishu WebSocket listener."""
    logger.info("[Feishu] ========== Starting Feishu WebSocket ==========")
    
    if not FEISHU_WS_AVAILABLE:
        logger.error("[Feishu] WebSocket not available - FEISHU_WS_AVAILABLE=False")
        return
    
    from .config import get_im_config
    config = get_im_config("feishu")
    if not config:
        logger.error("[Feishu] No configuration found")
        return
    
    if not config.get("enabled"):
        logger.error("[Feishu] Not enabled in config")
        return
    
    app_id = config.get("app_id")
    app_secret = config.get("app_secret")
    
    if not app_id or not app_secret:
        logger.error(f"[Feishu] Missing credentials - app_id={bool(app_id)}, app_secret={bool(app_secret)}")
        return
    
    logger.info(f"[Feishu] Config loaded - app_id: {app_id[:10]}..." if app_id else "[Feishu] Config loaded - no app_id")
    
    health_monitor = get_health_monitor()
    
    while True:
        client = None
        try:
            logger.info(f"[Feishu] Starting WebSocket client...")
            client = FeishuWebSocketClient(app_id, app_secret, _handle_feishu_message)
            client.start()
            
            # 设置连接状态为已连接
            health_monitor.set_connection_status("feishu", True)
            logger.info("[Feishu] WebSocket listener started successfully")
            
            # 飞书 SDK 会在自己的线程中运行，直到连接断开
            # 我们在这里等待，SDK 会自动重连
            while True:
                await asyncio.sleep(60)
                    
        except Exception as e:
            logger.error(f"[Feishu] WebSocket error: {e}")
            
            # 设置连接状态为断开
            health_monitor.set_connection_status("feishu", False)
            
            # 等待后重试
            logger.info("[Feishu] Reconnecting in 5 seconds...")
            await asyncio.sleep(5)


async def initialize_im_server():
    """Initialize IM server and start background tasks."""
    logger.info("=" * 50)
    logger.info("[IM Server] ========== Initializing IM Server ==========")
    logger.info("=" * 50)

    # Load configuration first
    logger.info("[IM Server] Loading IM configuration...")
    from .config import load_im_config, get_im_config, is_provider_enabled
    config = await load_im_config()
    if not config:
        logger.error("[IM Server] Failed to load IM configuration - no config found")
        return

    logger.info(f"[IM Server] IM configuration loaded: {config}")
    
    # Check each provider's enabled status
    feishu_enabled = is_provider_enabled("feishu")
    dingtalk_enabled = is_provider_enabled("dingtalk")
    imessage_enabled = is_provider_enabled("imessage")
    
    logger.info(f"[IM Server] Provider status:")
    logger.info(f"  - Feishu: enabled={feishu_enabled}, ws_available={FEISHU_WS_AVAILABLE}")
    logger.info(f"  - DingTalk: enabled={dingtalk_enabled}, stream_available={DINGTALK_STREAM_AVAILABLE}")
    logger.info(f"  - iMessage: enabled={imessage_enabled}, available={IMESSAGE_AVAILABLE}")
    
    if not feishu_enabled and not dingtalk_enabled and not imessage_enabled:
        logger.warning("[IM Server] No IM providers enabled, exiting")
        return

    # 启动健康检查监控器
    health_monitor = get_health_monitor()
    asyncio.create_task(health_monitor.start_monitoring())
    logger.info("[IM Server] Health monitor started (check interval: 30s)")

    # Start iMessage background task (if configured)
    if IMESSAGE_AVAILABLE:
        im_config = get_im_config("imessage")
        if im_config and im_config.get("enabled"):
            asyncio.create_task(_imessage_background_task())
            logger.info("iMessage background task started")
        else:
            logger.info("iMessage not enabled or not configured")

    # Start Feishu WebSocket listener (if configured)
    if FEISHU_WS_AVAILABLE:
        if feishu_enabled:
            asyncio.create_task(_start_feishu_websocket())
            logger.info("[IM Server] Feishu WebSocket task started")
        else:
            logger.info("[IM Server] Feishu not enabled, skipping")
    else:
        logger.warning("[IM Server] Feishu WebSocket not available (FEISHU_WS_AVAILABLE=False)")

    # Start DingTalk Stream listener (if configured)
    if DINGTALK_STREAM_AVAILABLE:
        if dingtalk_enabled:
            asyncio.create_task(_start_dingtalk_stream())
            logger.info("[IM Server] DingTalk Stream task started")
        else:
            logger.info("[IM Server] DingTalk not enabled, skipping")
    else:
        logger.warning("[IM Server] DingTalk Stream not available (DINGTALK_STREAM_AVAILABLE=False)")

    logger.info("[IM Server] ========== IM Server Initialized ==========")
    logger.info("=" * 50)


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

    health_monitor = get_health_monitor()
    
    while True:
        client = None
        try:
            logger.info(f"[DingTalk] Starting Stream client...")
            client = DingTalkStreamClient(client_id, client_secret, _handle_dingtalk_message)
            client.start()

            # 设置连接状态为已连接
            health_monitor.set_connection_status("dingtalk", True)
            logger.info("[DingTalk] Stream listener started successfully")

            # Keep the task alive - 这个循环会在连接断开后退出
            while True:
                await asyncio.sleep(60)

        except Exception as e:
            logger.error(f"[DingTalk] Stream error: {e}")

            # 设置连接状态为断开
            health_monitor.set_connection_status("dingtalk", False)

            # 等待后重试
            logger.info("[DingTalk] Reconnecting in 5 seconds...")
            await asyncio.sleep(5)


def _handle_dingtalk_message(message: Dict[str, Any]):
    """Handle incoming DingTalk message from Stream."""
    import asyncio

    # 更新健康监控器 - 记录收到消息的时间
    health_monitor = get_health_monitor()
    health_monitor.update_message_time("dingtalk")

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

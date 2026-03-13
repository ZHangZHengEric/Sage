"""
Multi-tenant IM Service Manager

Manages IM connections for multiple Sage users.
Each user can have multiple IM channels (Feishu, DingTalk, iMessage).
"""

import asyncio
import logging
import threading
from typing import Dict, Optional, Any, List
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from .db import get_im_db

logger = logging.getLogger("IMServiceManager")


class ChannelStatus(Enum):
    """Channel status enumeration."""
    INACTIVE = "inactive"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"
    STOPPING = "stopping"


@dataclass
class ChannelConfig:
    """Channel configuration."""
    sage_user_id: str
    provider_type: str
    config: Dict[str, Any]
    is_enabled: bool = True
    status: ChannelStatus = ChannelStatus.INACTIVE
    error_message: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


@dataclass
class ConnectionState:
    """Connection runtime state."""
    sage_user_id: str
    provider_type: str
    status: ChannelStatus
    started_at: Optional[datetime] = None
    last_heartbeat: Optional[datetime] = None
    error_message: Optional[str] = None
    task: Optional[asyncio.Task] = None


class IMServiceManager:
    """
    Multi-tenant IM Service Manager.
    
    Manages IM connections for multiple Sage users.
    Each user can have multiple channels (Feishu, DingTalk, iMessage).
    """
    
    def __init__(self):
        self._lock = threading.RLock()
        self._connections: Dict[str, ConnectionState] = {}  # key: "user_id:provider"
        self._db = get_im_db()
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None
        
    def _make_key(self, sage_user_id: str, provider_type: str) -> str:
        """Make connection key."""
        return f"{sage_user_id}:{provider_type}"
    
    async def start(self):
        """Start the service manager."""
        with self._lock:
            if self._running:
                logger.warning("[ServiceManager] Already running")
                return
            
            self._running = True
            logger.info("[ServiceManager] Starting...")
            
            # Start health monitor
            self._monitor_task = asyncio.create_task(self._health_monitor())
            
            # Auto-start enabled channels
            await self._auto_start_channels()
            
            logger.info("[ServiceManager] Started")
    
    async def stop(self):
        """Stop the service manager and all connections."""
        with self._lock:
            if not self._running:
                return
            
            self._running = False
            logger.info("[ServiceManager] Stopping...")
            
            # Stop all connections
            for key, state in list(self._connections.items()):
                await self.stop_channel(state.sage_user_id, state.provider_type)
            
            # Stop monitor
            if self._monitor_task:
                self._monitor_task.cancel()
                try:
                    await self._monitor_task
                except asyncio.CancelledError:
                    pass
            
            logger.info("[ServiceManager] Stopped")
    
    async def _auto_start_channels(self):
        """Auto-start all enabled channels from database."""
        logger.info("[ServiceManager] Auto-starting enabled channels...")

        try:
            # Get default user configs from database
            db = get_im_db()
            from .im_server import DEFAULT_SAGE_USER_ID
            configs = db.list_user_configs(DEFAULT_SAGE_USER_ID)

            logger.info(f"[ServiceManager] Found {len(configs)} configs for user {DEFAULT_SAGE_USER_ID}")

            for config in configs:
                provider = config.get('provider')
                enabled = config.get('enabled', False)
                logger.info(f"[ServiceManager] Config: provider={provider}, enabled={enabled}")

                if enabled and provider:
                    logger.info(f"[ServiceManager] Auto-starting {provider} channel...")
                    try:
                        await self.start_channel(DEFAULT_SAGE_USER_ID, provider)
                    except Exception as e:
                        logger.error(f"[ServiceManager] Failed to auto-start {provider}: {e}")

        except Exception as e:
            logger.error(f"[ServiceManager] Auto-start error: {e}", exc_info=True)
    
    async def start_channel(self, sage_user_id: str, provider_type: str) -> bool:
        """
        Start a channel for a user.
        
        Args:
            sage_user_id: Sage user ID
            provider_type: IM provider type (feishu/dingtalk/imessage)
            
        Returns:
            True if started successfully
        """
        key = self._make_key(sage_user_id, provider_type)
        
        with self._lock:
            # Check if already running or starting
            if key in self._connections:
                state = self._connections[key]
                if state.status in [ChannelStatus.CONNECTED, ChannelStatus.CONNECTING]:
                    logger.info(f"[ServiceManager] Channel {key} already running (status={state.status.value})")
                    return True
                elif state.status == ChannelStatus.ERROR:
                    # If previous attempt failed, remove it and try again
                    logger.warning(f"[ServiceManager] Channel {key} was in ERROR state, will retry")
                    del self._connections[key]
            
            # Get config from database
            config_data = self._db.get_user_config(sage_user_id, provider_type)
            if not config_data:
                logger.error(f"[ServiceManager] No config found for {key}")
                return False
            
            if not config_data.get('enabled', True):
                logger.info(f"[ServiceManager] Channel {key} is disabled")
                return False
            
            # Create connection state
            state = ConnectionState(
                sage_user_id=sage_user_id,
                provider_type=provider_type,
                status=ChannelStatus.CONNECTING,
                started_at=datetime.now()
            )
            self._connections[key] = state
        
        # Start connection (outside lock)
        try:
            logger.info(f"[ServiceManager] Starting channel {key}...")
            
            # Start provider-specific connection
            if provider_type == "feishu":
                task = asyncio.create_task(
                    self._run_feishu_channel(sage_user_id, config_data['config'])
                )
            elif provider_type == "dingtalk":
                task = asyncio.create_task(
                    self._run_dingtalk_channel(sage_user_id, config_data['config'])
                )
            elif provider_type == "imessage":
                task = asyncio.create_task(
                    self._run_imessage_channel(sage_user_id, config_data['config'])
                )
            elif provider_type == "wechat_work":
                task = asyncio.create_task(
                    self._run_wechat_work_channel(sage_user_id, config_data['config'])
                )
            else:
                raise ValueError(f"Unknown provider: {provider_type}")
            
            state.task = task
            
            # Wait a bit to check if connection started
            await asyncio.sleep(2)
            
            if state.status == ChannelStatus.ERROR:
                logger.error(f"[ServiceManager] Channel {key} failed to start: {state.error_message}")
                return False
            
            logger.info(f"[ServiceManager] Channel {key} started")
            return True
            
        except Exception as e:
            logger.error(f"[ServiceManager] Failed to start channel {key}: {e}")
            state.status = ChannelStatus.ERROR
            state.error_message = str(e)
            return False
    
    async def stop_channel(self, sage_user_id: str, provider_type: str) -> bool:
        """
        Stop a channel for a user.
        
        Args:
            sage_user_id: Sage user ID
            provider_type: IM provider type
            
        Returns:
            True if stopped successfully
        """
        key = self._make_key(sage_user_id, provider_type)
        
        with self._lock:
            if key not in self._connections:
                logger.warning(f"[ServiceManager] Channel {key} not found")
                return False
            
            state = self._connections[key]
            state.status = ChannelStatus.STOPPING
            
            # Cancel the task
            if state.task and not state.task.done():
                state.task.cancel()
        
        # Wait for task to complete (outside lock)
        try:
            if state.task:
                await state.task
        except asyncio.CancelledError:
            pass
        
        with self._lock:
            if key in self._connections:
                del self._connections[key]
        
        logger.info(f"[ServiceManager] Channel {key} stopped")
        return True
    
    async def restart_channel(self, sage_user_id: str, provider_type: str) -> bool:
        """Restart a channel."""
        logger.info(f"[ServiceManager] Restarting channel {sage_user_id}:{provider_type}...")
        
        await self.stop_channel(sage_user_id, provider_type)
        await asyncio.sleep(1)  # Wait for cleanup
        
        return await self.start_channel(sage_user_id, provider_type)
    
    async def update_channel_config(
        self,
        sage_user_id: str,
        provider_type: str,
        config: Dict[str, Any]
    ) -> bool:
        """
        Update channel configuration and restart if running.
        
        Args:
            sage_user_id: Sage user ID
            provider_type: IM provider type
            config: New configuration
            
        Returns:
            True if updated successfully
        """
        key = self._make_key(sage_user_id, provider_type)
        
        # Save to database
        result = self._db.save_user_config(sage_user_id, provider_type, config)
        if not result:
            logger.error(f"[ServiceManager] Failed to save config for {key}")
            return False
        
        logger.info(f"[ServiceManager] Config updated for {key}")
        
        # Restart if running
        with self._lock:
            is_running = key in self._connections
        
        if is_running:
            logger.info(f"[ServiceManager] Restarting channel {key} with new config...")
            return await self.restart_channel(sage_user_id, provider_type)
        
        return True
    
    def get_channel_status(self, sage_user_id: str, provider_type: str) -> Optional[Dict[str, Any]]:
        """Get channel status."""
        key = self._make_key(sage_user_id, provider_type)
        
        with self._lock:
            if key not in self._connections:
                # Check if enabled in DB
                config = self._db.get_user_config(sage_user_id, provider_type)
                if config:
                    return {
                        "sage_user_id": sage_user_id,
                        "provider_type": provider_type,
                        "status": ChannelStatus.INACTIVE.value,
                        "is_enabled": config.get('enabled', True),
                        "error_message": None
                    }
                return None
            
            state = self._connections[key]
            return {
                "sage_user_id": state.sage_user_id,
                "provider_type": state.provider_type,
                "status": state.status.value,
                "started_at": state.started_at.isoformat() if state.started_at else None,
                "last_heartbeat": state.last_heartbeat.isoformat() if state.last_heartbeat else None,
                "error_message": state.error_message
            }
    
    def list_user_channels(self, sage_user_id: str) -> List[Dict[str, Any]]:
        """List all channels for a user."""
        configs = self._db.list_user_configs(sage_user_id)
        
        channels = []
        for config in configs:
            provider_type = config['provider']
            status = self.get_channel_status(sage_user_id, provider_type)
            if status:
                channels.append(status)
        
        return channels
    
    def list_all_channels(self) -> List[Dict[str, Any]]:
        """List all channels (admin use)."""
        # This would need a DB method to get all users
        # For now, return only active connections
        with self._lock:
            return [
                {
                    "sage_user_id": state.sage_user_id,
                    "provider_type": state.provider_type,
                    "status": state.status.value,
                    "started_at": state.started_at.isoformat() if state.started_at else None,
                    "last_heartbeat": state.last_heartbeat.isoformat() if state.last_heartbeat else None,
                    "error_message": state.error_message
                }
                for state in self._connections.values()
            ]
    
    async def _health_monitor(self):
        """Monitor health of all connections."""
        logger.info("[ServiceManager] Health monitor started")
        
        while self._running:
            try:
                await asyncio.sleep(30)  # Check every 30 seconds
                
                with self._lock:
                    for key, state in list(self._connections.items()):
                        # Check if task is still running
                        if state.task and state.task.done():
                            # Task exited unexpectedly
                            if state.status != ChannelStatus.STOPPING:
                                logger.error(f"[ServiceManager] Channel {key} exited unexpectedly")
                                state.status = ChannelStatus.ERROR
                                state.error_message = "Connection task exited"
                                
                                # Auto-retry after delay
                                asyncio.create_task(self._auto_retry(state.sage_user_id, state.provider_type))
                        
                        # Update heartbeat
                        if state.status == ChannelStatus.CONNECTED:
                            state.last_heartbeat = datetime.now()
                            
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[ServiceManager] Health monitor error: {e}")
        
        logger.info("[ServiceManager] Health monitor stopped")
    
    async def _auto_retry(self, sage_user_id: str, provider_type: str, delay: int = 60):
        """Auto-retry connection after delay."""
        logger.info(f"[ServiceManager] Auto-retry {sage_user_id}:{provider_type} in {delay}s...")
        await asyncio.sleep(delay)
        await self.restart_channel(sage_user_id, provider_type)
    
    # === Provider-specific channel runners ===
    
    async def _run_feishu_channel(self, sage_user_id: str, config: Dict[str, Any]):
        """Run Feishu channel."""
        key = self._make_key(sage_user_id, "feishu")
        
        try:
            from .providers.feishu import FeishuWebSocketClient
            
            app_id = config.get('app_id')
            app_secret = config.get('app_secret')
            
            if not app_id or not app_secret:
                raise ValueError("Feishu app_id and app_secret required")
            
            # Create message handler for this channel
            message_handler = self._make_message_handler(sage_user_id, "feishu")
            
            # Create and start client
            client = FeishuWebSocketClient(app_id, app_secret, message_handler)
            client.start()
            
            # Update state to connected
            with self._lock:
                if key in self._connections:
                    self._connections[key].status = ChannelStatus.CONNECTED
            
            logger.info(f"[ServiceManager] Feishu channel {key} connected")
            
            # Keep running until cancelled
            while True:
                await asyncio.sleep(60)
                
        except asyncio.CancelledError:
            logger.info(f"[ServiceManager] Feishu channel {key} cancelled")
            raise
        except Exception as e:
            logger.error(f"[ServiceManager] Feishu channel {key} error: {e}")
            with self._lock:
                if key in self._connections:
                    self._connections[key].status = ChannelStatus.ERROR
                    self._connections[key].error_message = str(e)
            raise
    
    async def _run_dingtalk_channel(self, sage_user_id: str, config: Dict[str, Any]):
        """Run DingTalk channel."""
        key = self._make_key(sage_user_id, "dingtalk")
        
        try:
            from .providers.dingtalk import DingTalkStreamClient
            
            client_id = config.get('client_id') or config.get('app_key')
            client_secret = config.get('client_secret') or config.get('app_secret')
            
            if not client_id or not client_secret:
                raise ValueError("DingTalk client_id and client_secret required")
            
            # Create message handler for this channel
            message_handler = self._make_message_handler(sage_user_id, "dingtalk")
            
            # Create and start client
            client = DingTalkStreamClient(client_id, client_secret, message_handler)
            client.start()
            
            # Update state to connected
            with self._lock:
                if key in self._connections:
                    self._connections[key].status = ChannelStatus.CONNECTED
            
            logger.info(f"[ServiceManager] DingTalk channel {key} connected")
            
            # Keep running until cancelled
            while True:
                await asyncio.sleep(60)
                
        except asyncio.CancelledError:
            logger.info(f"[ServiceManager] DingTalk channel {key} cancelled")
            raise
        except Exception as e:
            logger.error(f"[ServiceManager] DingTalk channel {key} error: {e}")
            with self._lock:
                if key in self._connections:
                    self._connections[key].status = ChannelStatus.ERROR
                    self._connections[key].error_message = str(e)
            raise
    
    async def _run_imessage_channel(self, sage_user_id: str, config: Dict[str, Any]):
        """Run iMessage channel."""
        key = self._make_key(sage_user_id, "imessage")
        
        try:
            from .providers.imessage import iMessageDatabasePoller
            
            # Get allowed senders from config
            allowed_senders = config.get('allowed_senders', [])
            
            # Create message handler for this channel
            message_handler = self._make_message_handler(sage_user_id, "imessage")
            
            # Create and start poller
            poller = iMessageDatabasePoller(
                message_handler=message_handler,
                allowed_senders=allowed_senders
            )
            poller.start()
            
            # Update state to connected
            with self._lock:
                if key in self._connections:
                    self._connections[key].status = ChannelStatus.CONNECTED
            
            logger.info(f"[ServiceManager] iMessage channel {key} started polling")
            
            # Keep running until cancelled
            while True:
                await asyncio.sleep(60)
                
        except asyncio.CancelledError:
            logger.info(f"[ServiceManager] iMessage channel {key} cancelled")
            raise
        except Exception as e:
            logger.error(f"[ServiceManager] iMessage channel {key} error: {e}")
            with self._lock:
                if key in self._connections:
                    self._connections[key].status = ChannelStatus.ERROR
                    self._connections[key].error_message = str(e)
            raise
    
    async def _run_wechat_work_channel(self, sage_user_id: str, config: Dict[str, Any]):
        """Run WeChat Work channel using WebSocket long connection."""
        key = self._make_key(sage_user_id, "wechat_work")
        
        try:
            from .providers.wechat_work import WeChatWorkProvider
            
            bot_id = config.get('bot_id') or config.get('client_id')
            secret = config.get('secret') or config.get('client_secret')
            
            if not bot_id or not secret:
                raise ValueError("WeChat Work bot_id and secret required")
            
            # Create message handler for this channel
            message_handler = self._make_message_handler(sage_user_id, "wechat_work")
            
            # 确保 enabled 被设置为 True (从数据库读取时可能在单独字段)
            provider_config = {
                **config,
                'enabled': True,  # 强制启用，因为已通过启用检查
                'bot_id': bot_id,
                'secret': secret
            }
            
            # Create provider and start WebSocket client
            provider = WeChatWorkProvider(provider_config)
            if not provider.start_client(message_handler):
                raise ValueError("Failed to start WeChat Work WebSocket client")
            
            # Update state to connected
            with self._lock:
                if key in self._connections:
                    self._connections[key].status = ChannelStatus.CONNECTED
            
            logger.info(f"[ServiceManager] WeChat Work channel {key} connected")
            
            # Keep running until cancelled
            while True:
                await asyncio.sleep(60)
                
        except asyncio.CancelledError:
            logger.info(f"[ServiceManager] WeChat Work channel {key} cancelled")
            # Stop the client
            try:
                from .providers.wechat_work import WeChatWorkProvider
                provider = WeChatWorkProvider(config)
                provider.stop_client()
            except Exception:
                pass
            raise
        except Exception as e:
            logger.error(f"[ServiceManager] WeChat Work channel {key} error: {e}")
            with self._lock:
                if key in self._connections:
                    self._connections[key].status = ChannelStatus.ERROR
                    self._connections[key].error_message = str(e)
            raise
    
    def _make_message_handler(self, sage_user_id: str, provider_type: str):
        """
        Create message handler for a channel.

        This handler routes incoming IM messages to the Sage Agent via handle_incoming_message.
        """
        async def handler(message: Dict[str, Any]):
            """Handle incoming message from IM provider."""
            try:
                logger.info(f"[ServiceManager] Message from {sage_user_id}:{provider_type}: {message}")

                # Extract message details
                # iMessage uses 'sender', others use 'user_id'
                user_id = message.get('user_id') or message.get('sender')
                chat_id = message.get('chat_id')
                content = message.get('content', {})
                user_name = message.get('user_name') or message.get('sender_name')

                # Extract text content
                if isinstance(content, dict):
                    text = content.get('text', '')
                else:
                    text = str(content)

                if not text:
                    logger.warning(f"[ServiceManager] Empty message from {provider_type}")
                    return

                # Import here to avoid circular import
                from .im_server import handle_incoming_message

                # Call the centralized message handler
                await handle_incoming_message(
                    provider=provider_type,
                    user_id=user_id,
                    content=text,
                    chat_id=chat_id,
                    user_name=user_name
                )

            except Exception as e:
                logger.error(f"[ServiceManager] Error handling message: {e}", exc_info=True)

        return handler
    
    async def _get_default_agent_id(self) -> str:
        """Get default agent ID."""
        try:
            import httpx
            import os
            
            port = os.getenv("SAGE_PORT", "8080")
            base_url = f"http://localhost:{port}"
            
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{base_url}/api/agent/list")
                
                if response.status_code == 200:
                    data = response.json()
                    if (data.get("success") or data.get("code") == 200) and data.get("data"):
                        agents = data["data"]
                        if len(agents) > 0:
                            return agents[0].get("id") or agents[0].get("agent_id", "default")
            
            return "default"
        except Exception as e:
            logger.error(f"[ServiceManager] Failed to get default agent: {e}")
            return "default"
    
    async def _send_response_back(
        self,
        sage_user_id: str,
        provider_type: str,
        user_id: Optional[str],
        chat_id: Optional[str],
        content: str
    ):
        """Send agent response back to user via IM."""
        try:
            from .im_providers import get_im_provider
            
            # Get config from database
            config_data = self._db.get_user_config(sage_user_id, provider_type)
            if not config_data:
                logger.error(f"[ServiceManager] No config found for {sage_user_id}:{provider_type}")
                return
            
            # Get provider instance
            provider = get_im_provider(provider_type, config_data['config'])
            
            # Send message
            result = await provider.send_message(
                content=content,
                user_id=user_id,
                chat_id=chat_id,
                msg_type="text"
            )
            
            if result.get('success'):
                logger.info("[ServiceManager] Response sent back to user")
            else:
                logger.error(f"[ServiceManager] Failed to send response: {result.get('error')}")
                
        except Exception as e:
            logger.error(f"[ServiceManager] Error sending response back: {e}")


# Global service manager instance
_service_manager: Optional[IMServiceManager] = None


def get_service_manager() -> IMServiceManager:
    """Get or create global service manager instance."""
    global _service_manager
    if _service_manager is None:
        _service_manager = IMServiceManager()
    return _service_manager

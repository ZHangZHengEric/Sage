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
from .agent_config import get_agent_im_config, list_all_agents, get_default_agent_id

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
    provider: Optional[Any] = None  # Provider 实例，用于发送消息时复用


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
        """Auto-start all enabled channels from database and Agent configs."""
        logger.info("[ServiceManager] Auto-starting enabled channels...")

        try:
            # 1. Start default user configs from database (backward compatibility)
            db = get_im_db()
            from .im_server import DEFAULT_SAGE_USER_ID
            configs = db.list_user_configs(DEFAULT_SAGE_USER_ID)

            logger.info(f"[ServiceManager] Found {len(configs)} legacy configs for user {DEFAULT_SAGE_USER_ID}")

            for config in configs:
                provider = config.get('provider')
                enabled = config.get('enabled', False)
                logger.info(f"[ServiceManager] Legacy config: provider={provider}, enabled={enabled}")

                if enabled and provider:
                    logger.info(f"[ServiceManager] Auto-starting legacy {provider} channel...")
                    try:
                        await self.start_channel(DEFAULT_SAGE_USER_ID, provider)
                    except Exception as e:
                        logger.error(f"[ServiceManager] Failed to auto-start legacy {provider}: {e}")

            # 2. Start Agent-level configs
            try:
                agents = list_all_agents()
                logger.info(f"[ServiceManager] Found {len(agents)} agents with IM config: {agents}")
                
                for agent_id in agents:
                    try:
                        from .agent_config import get_agent_im_config
                        agent_config = get_agent_im_config(agent_id)
                        all_channels = agent_config.get_all_channels()
                        logger.info(f"[ServiceManager] Agent {agent_id} channels: {list(all_channels.keys())}")
                        
                        for provider, channel_data in all_channels.items():
                            logger.info(f"[ServiceManager] Checking {provider} for {agent_id}: enabled={channel_data.get('enabled')}")
                            if channel_data.get('enabled'):
                                logger.info(f"[ServiceManager] Auto-starting {provider} for agent={agent_id}")
                                try:
                                    await self.start_channel(agent_id, provider)
                                except Exception as e:
                                    logger.error(f"[ServiceManager] Failed to auto-start {provider} for {agent_id}: {e}")
                    except Exception as e:
                        logger.warning(f"[ServiceManager] Failed to process agent {agent_id}: {e}", exc_info=True)
                        
            except Exception as e:
                logger.warning(f"[ServiceManager] Failed to auto-start Agent configs: {e}", exc_info=True)

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
            
            # Get config: try Agent-level config first, then fallback to database
            config_data = None
            try:
                from .agent_config import get_agent_im_config
                agent_config = get_agent_im_config(sage_user_id)
                # Use get_all_channels to get config even if not enabled (we'll check enabled below)
                all_channels = agent_config.get_all_channels()
                channel_info = all_channels.get(provider_type)
                if channel_info:
                    config_data = {
                        'enabled': channel_info.get('enabled', False),
                        'config': channel_info.get('config', {})
                    }
                    logger.info(f"[ServiceManager] Using Agent-level config for {key}, enabled={config_data['enabled']}")
            except Exception as e:
                logger.info(f"[ServiceManager] Failed to get Agent config for {key}: {e}", exc_info=True)
            
            # Fallback to database config
            if not config_data:
                config_data = self._db.get_user_config(sage_user_id, provider_type)
                if config_data:
                    logger.info(f"[ServiceManager] Using database config for {key}")
            
            if not config_data:
                logger.error(f"[ServiceManager] No config found for {key}")
                return False
            
            if not config_data.get('enabled', False):
                logger.info(f"[ServiceManager] Channel {key} is disabled, not starting")
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
            elif provider_type == "wechat_personal":
                task = asyncio.create_task(
                    self._run_wechat_personal_channel(sage_user_id, config_data['config'])
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
            
            # Save provider reference before cancelling
            provider = state.provider
            
            # Cancel the task
            if state.task and not state.task.done():
                state.task.cancel()
        
        # Stop the provider (outside lock to avoid deadlock)
        if provider:
            try:
                logger.info(f"[ServiceManager] Stopping provider for {key}")
                provider.stop_client()
                # Give time for connection to close gracefully
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.warning(f"[ServiceManager] Error stopping provider: {e}")
        
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
    
    def get_provider(self, sage_user_id: str, provider_type: str) -> Optional[Any]:
        """
        获取正在运行的 Provider 实例
        
        用于发送消息时复用现有的 WebSocket 连接，避免创建临时连接。
        
        Args:
            sage_user_id: Sage user ID
            provider_type: IM provider type
            
        Returns:
            Provider 实例，如果没有运行则返回 None
        """
        key = self._make_key(sage_user_id, provider_type)
        
        with self._lock:
            state = self._connections.get(key)
            if state and state.status == ChannelStatus.CONNECTED and state.provider:
                return state.provider
        
        return None
    
    def find_provider_by_user(self, provider_type: str, user_id: str) -> Optional[Any]:
        """
        通过 provider + user_id 查找正在运行的 Provider 实例
        
        用于从 IM 会话中查找对应的 provider 连接。
        
        Args:
            provider_type: IM provider type (wechat_work, feishu, etc.)
            user_id: 用户在 IM 平台的 user_id
            
        Returns:
            Provider 实例，如果没有运行则返回 None
        """
        # 遍历所有连接，查找匹配的 provider
        # 对于企业微信，只有一个连接（通过 bot_id），所以直接返回第一个匹配的
        with self._lock:
            for key, state in self._connections.items():
                if (state.provider_type == provider_type and 
                    state.status == ChannelStatus.CONNECTED and 
                    state.provider):
                    # 找到匹配的 provider
                    logger.debug(f"[ServiceManager] Found provider for {provider_type}:{user_id}")
                    return state.provider
        
        return None
    
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
            from .providers.feishu import FeishuWebSocketClient, FeishuProvider
            
            app_id = config.get('app_id')
            app_secret = config.get('app_secret')
            
            if not app_id or not app_secret:
                raise ValueError("Feishu app_id and app_secret required")
            
            # Create provider instance for file download
            provider_instance = FeishuProvider(config)
            
            # Create message handler with file download support
            message_handler = self._make_feishu_message_handler(
                sage_user_id, provider_instance
            )
            
            # Create and start client
            client = FeishuWebSocketClient(app_id, app_secret, message_handler)
            client.start()
            
            # Update state to connected
            with self._lock:
                if key in self._connections:
                    self._connections[key].status = ChannelStatus.CONNECTED
                    self._connections[key].provider = provider_instance
            
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
    
    def _make_feishu_message_handler(self, sage_user_id: str, provider: Any):
        """
        Create Feishu message handler with file download support.
        """
        import os
        from pathlib import Path
        
        async def handler(message: Dict[str, Any]):
            """Handle incoming Feishu message with file download."""
            try:
                logger.info(f"[ServiceManager] Feishu handler: {message}")
                
                msg_type = message.get('msg_type')
                
                # Check if it's a file/image message that needs download
                if msg_type == 'file':
                    content = message.get('content', {})
                    file_key = content.get('file_key')
                    file_name = content.get('file_name', 'unknown')
                    message_id = message.get('message_id')
                    
                    if file_key and message_id:
                        logger.info(f"[ServiceManager] Feishu file message detected: {file_name}, file_key={file_key}")
                        
                        # Determine save directory
                        sage_home = Path.home() / ".sage"
                        chat_type = "group" if message.get('chat_id') else "private"
                        save_dir = sage_home / "agents" / sage_user_id / "IM" / "feishu" / chat_type
                        
                        logger.info(f"[ServiceManager] Downloading Feishu file: {file_name}")
                        
                        # Download file using provider
                        download_result = await provider.download_file(
                            file_key=file_key,
                            message_id=message_id,
                            save_dir=str(save_dir),
                            file_name=file_name
                        )
                        
                        if download_result.get('success'):
                            local_path = download_result.get('file_path')
                            file_size = download_result.get('file_size', 0)
                            
                            logger.info(f"[ServiceManager] Feishu file downloaded: {local_path}, size={file_size}")
                            
                            # Get mime type
                            mime_type = self._get_mime_type(local_path)
                            
                            # Update message with file info
                            message['file_info'] = {
                                'name': file_name,
                                'size': file_size,
                                'mime_type': mime_type,
                                'local_path': local_path
                            }
                            
                            # Build message content based on file type
                            file_content_text = ""
                            
                            # For text files, read content
                            if mime_type and (mime_type.startswith('text/') or 
                                             mime_type == 'application/json' or
                                             mime_type == 'application/javascript'):
                                try:
                                    with open(local_path, 'r', encoding='utf-8', errors='ignore') as f:
                                        file_content = f.read()
                                    if file_content:
                                        file_content_text = f"\n\n[文件内容]:\n{file_content[:10000]}"
                                        logger.info(f"[ServiceManager] Added text file content, length={len(file_content)}")
                                except Exception as e:
                                    logger.warning(f"[ServiceManager] Failed to read text file: {e}")
                            else:
                                # For non-text files, add a note
                                file_content_text = f"\n\n[文件类型: {mime_type or '未知'}，已保存到工作区]"
                            
                            # Update message content with file info
                            message['content'] = {
                                'text': f"[文件: {file_name}]{file_content_text}"
                            }
                            
                        else:
                            error = download_result.get('error', 'Unknown error')
                            logger.error(f"[ServiceManager] Failed to download Feishu file: {error}")
                            message['file_info'] = {
                                'name': file_name,
                                'size': 0,
                                'mime_type': 'unknown',
                                'local_path': 'unknown',
                                'download_error': error
                            }
                            # Still provide a text content so it's not empty
                            message['content'] = {
                                'text': f"[文件: {file_name}]\n\n[文件下载失败: {error}]"
                            }
                
                # Now call the standard message handler
                standard_handler = self._make_message_handler(sage_user_id, "feishu")
                await standard_handler(message)
                
            except Exception as e:
                logger.error(f"[ServiceManager] Error in Feishu message handler: {e}", exc_info=True)
        
        return handler
    
    async def _run_dingtalk_channel(self, sage_user_id: str, config: Dict[str, Any]):
        """Run DingTalk channel."""
        key = self._make_key(sage_user_id, "dingtalk")
        
        try:
            from .providers.dingtalk import DingTalkStreamClient, DingTalkProvider
            
            client_id = config.get('client_id') or config.get('app_key')
            client_secret = config.get('client_secret') or config.get('app_secret')
            
            if not client_id or not client_secret:
                raise ValueError("DingTalk client_id and client_secret required")
            
            # Create provider instance for file download
            provider_instance = DingTalkProvider(config)
            
            # Create message handler with file download support
            message_handler = self._make_dingtalk_message_handler(
                sage_user_id, provider_instance
            )
            
            # Create and start client
            client = DingTalkStreamClient(client_id, client_secret, message_handler)
            client.start()
            
            # Update state to connected
            with self._lock:
                if key in self._connections:
                    self._connections[key].status = ChannelStatus.CONNECTED
                    self._connections[key].provider = provider_instance
            
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
    
    def _make_dingtalk_message_handler(self, sage_user_id: str, provider: Any):
        """
        Create DingTalk message handler with file download support.
        """
        import os
        from pathlib import Path
        
        async def handler(message: Dict[str, Any]):
            """Handle incoming DingTalk message with file download."""
            try:
                logger.info(f"[ServiceManager] DingTalk handler: {message}")
                
                # Check if it's a file/image message that needs download
                file_info = message.get('file_info')
                logger.info(f"[ServiceManager] DingTalk file_info check: {file_info}")
                if file_info and file_info.get('download_code'):
                    download_code = file_info.get('download_code')
                    logger.info(f"[ServiceManager] DingTalk file message detected, download_code: {download_code}")
                    
                    # Download the file
                    file_name = file_info.get('file_name', 'unknown')
                    file_type = file_info.get('type', 'file')
                    
                    # Determine save directory
                    sage_home = Path.home() / ".sage"
                    chat_type = "group" if message.get('chat_id') else "private"
                    save_dir = sage_home / "agents" / sage_user_id / "IM" / "dingtalk" / chat_type
                    
                    logger.info(f"[ServiceManager] Downloading DingTalk file: {file_name}, code={download_code[:20]}...")
                    
                    try:
                        # Download file using provider
                        download_result = await provider.download_file(
                            download_code=download_code,
                            save_dir=str(save_dir),
                            file_name=file_name
                        )
                        
                        if download_result.get('success'):
                            local_path = download_result.get('file_path')
                            file_size = download_result.get('file_size', 0)
                            
                            logger.info(f"[ServiceManager] DingTalk file downloaded: {local_path}, size={file_size}")
                            
                            # Update file_info with downloaded file details
                            # This format matches what agent_client expects
                            message['file_info'] = {
                                'name': file_name,
                                'size': file_size,
                                'mime_type': None,  # Will be detected by agent
                                'local_path': local_path
                            }
                            logger.info(f"[ServiceManager] Updated file_info: {message['file_info']}")
                            
                            # Handle additional images from rich text messages
                            additional_images = file_info.get('additional_images', [])
                            if additional_images:
                                logger.info(f"[ServiceManager] Downloading {len(additional_images)} additional images from rich text")
                                downloaded_images = []
                                for idx, add_download_code in enumerate(additional_images):
                                    add_file_name = f"rich_text_image_{idx + 1}.jpg"
                                    add_download_result = await provider.download_file(
                                        download_code=add_download_code,
                                        save_dir=str(save_dir),
                                        file_name=add_file_name
                                    )
                                    if add_download_result.get('success'):
                                        downloaded_images.append({
                                            'name': add_file_name,
                                            'size': add_download_result.get('file_size', 0),
                                            'mime_type': 'image/jpeg',
                                            'local_path': add_download_result.get('file_path')
                                        })
                                if downloaded_images:
                                    message['file_info']['additional_files'] = downloaded_images
                                    logger.info(f"[ServiceManager] Downloaded {len(downloaded_images)} additional images")
                            
                            # For text files, read content and add to message
                            mime_type = self._get_mime_type(local_path)
                            if mime_type and (mime_type.startswith('text/') or 
                                             mime_type == 'application/json' or
                                             mime_type == 'application/javascript' or
                                             mime_type == 'application/xml'):
                                try:
                                    with open(local_path, 'r', encoding='utf-8', errors='ignore') as f:
                                        file_content = f.read()
                                    if file_content:
                                        # Append file content to message text
                                        original_content = message.get('content', {})
                                        if isinstance(original_content, dict):
                                            original_text = original_content.get('text', '')
                                        else:
                                            original_text = str(original_content)
                                        
                                        # Truncate if too long
                                        max_chars = 10000
                                        if len(file_content) > max_chars:
                                            file_content = file_content[:max_chars] + f"\n\n[文件已截断，共 {len(file_content)} 字符]"
                                        
                                        message['content'] = {
                                            'text': f"{original_text}\n\n[文件内容]:\n{file_content}"
                                        }
                                        logger.info(f"[ServiceManager] Added text file content, length={len(file_content)}")
                                except Exception as e:
                                    logger.warning(f"[ServiceManager] Failed to read text file: {e}")
                            
                            # Update mime_type after detection
                            message['file_info']['mime_type'] = mime_type
                        else:
                            error = download_result.get('error', 'Unknown error')
                            logger.error(f"[ServiceManager] Failed to download DingTalk file: {error}")
                            # Keep original file_info but mark as failed
                            message['file_info'] = {
                                'name': file_name,
                                'size': 0,
                                'mime_type': 'unknown',
                                'local_path': 'unknown',
                                'download_error': error
                            }
                    except Exception as download_error:
                        logger.error(f"[ServiceManager] Exception during file download: {download_error}", exc_info=True)
                        message['file_info'] = {
                            'name': file_name,
                            'size': 0,
                            'mime_type': 'unknown',
                            'local_path': 'unknown',
                            'download_error': str(download_error)
                        }
                
                # Now call the standard message handler
                standard_handler = self._make_message_handler(sage_user_id, "dingtalk")
                await standard_handler(message)
                
            except Exception as e:
                logger.error(f"[ServiceManager] Error in DingTalk message handler: {e}", exc_info=True)
        
        return handler
    
    def _get_mime_type(self, file_path: str) -> Optional[str]:
        """Get MIME type for a file."""
        import mimetypes
        mime_type, _ = mimetypes.guess_type(file_path)
        return mime_type
    
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
            
            # Update state to connected and save provider instance
            with self._lock:
                if key in self._connections:
                    self._connections[key].status = ChannelStatus.CONNECTED
                    self._connections[key].provider = provider  # 保存 provider 实例供后续使用
            
            logger.info(f"[ServiceManager] WeChat Work channel {key} connected")
            
            # Keep running until cancelled
            while True:
                await asyncio.sleep(60)
                
        except asyncio.CancelledError:
            logger.info(f"[ServiceManager] WeChat Work channel {key} cancelled")
            # Stop the client - use the saved provider instance
            try:
                with self._lock:
                    saved_provider = self._connections.get(key, {}).get('provider')
                if saved_provider:
                    saved_provider.stop_client()
                    logger.info(f"[ServiceManager] WeChat Work client stopped for {key}")
            except Exception as e:
                logger.warning(f"[ServiceManager] Error stopping WeChat Work client: {e}")
            raise
        except Exception as e:
            logger.error(f"[ServiceManager] WeChat Work channel {key} error: {e}")
            with self._lock:
                if key in self._connections:
                    self._connections[key].status = ChannelStatus.ERROR
                    self._connections[key].error_message = str(e)
            raise
    
    async def _run_wechat_personal_channel(self, sage_user_id: str, config: Dict[str, Any]):
        """Run WeChat Personal (iLink) channel using HTTP long polling."""
        key = self._make_key(sage_user_id, "wechat_personal")
        
        try:
            from .providers.wechat_ilink import WeChatPersonalPoller
            
            bot_token = config.get('bot_token')
            if not bot_token:
                raise ValueError("WeChat Personal bot_token required")
            
            # Create message handler for this channel
            message_handler = self._make_message_handler(sage_user_id, "wechat_personal")
            
            # Create and start poller
            poller = WeChatPersonalPoller(
                message_handler=message_handler,
                bot_token=bot_token
            )
            poller.start()
            
            # Update state to connected
            with self._lock:
                if key in self._connections:
                    self._connections[key].status = ChannelStatus.CONNECTED
            
            logger.info(f"[ServiceManager] WeChat Personal channel {key} started polling")
            
            # Keep running until cancelled
            while True:
                await asyncio.sleep(60)
                
        except asyncio.CancelledError:
            logger.info(f"[ServiceManager] WeChat Personal channel {key} cancelled")
            raise
        except Exception as e:
            logger.error(f"[ServiceManager] WeChat Personal channel {key} error: {e}")
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
                logger.info(f"[ServiceManager] ====== Message handler START ======")
                logger.info(f"[ServiceManager] Message from {sage_user_id}:{provider_type}: {message}")

                # Filter out events (only handle actual user messages)
                msg_type = message.get('type')
                if msg_type == 'event':
                    logger.info(f"[ServiceManager] Ignoring event type message: {message.get('event_type')}")
                    return

                # Extract message details
                # iMessage uses 'sender', others use 'user_id'
                user_id = message.get('user_id') or message.get('sender')
                chat_id = message.get('chat_id')
                content = message.get('content', {})
                user_name = message.get('user_name') or message.get('sender_name')
                
                # Extract file info (if present) - for WeChat Work file messages
                file_info = message.get('file_info')
                if file_info:
                    logger.info(f"[ServiceManager] File message detected: {file_info.get('name')}")

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
                # Pass sage_user_id as default_agent_id to route to the correct agent
                logger.info(f"[ServiceManager] Calling handle_incoming_message with agent_id={sage_user_id}")
                await handle_incoming_message(
                    provider=provider_type,
                    user_id=user_id,
                    content=text,
                    chat_id=chat_id,
                    user_name=user_name,
                    default_agent_id=sage_user_id,  # Use the agent this channel belongs to
                    file_info=file_info
                )
                logger.info(f"[ServiceManager] ====== Message handler END ======")

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
        agent_id: str,
        provider_type: str,
        user_id: Optional[str],
        chat_id: Optional[str],
        content: str
    ):
        """
        Send agent response back to user via IM.
        
        Args:
            agent_id: Agent ID for configuration lookup
            provider_type: IM provider type
            user_id: User ID in IM platform
            chat_id: Chat/Group ID
            content: Message content to send
        """
        try:
            # First try to find running provider by agent_id + provider
            provider = self.find_provider_by_agent(agent_id, provider_type)
            
            if not provider:
                # No running provider, create new instance from Agent config
                logger.warning(f"[ServiceManager] No running provider for agent={agent_id}, provider={provider_type}, creating new instance")
                from .im_providers import get_im_provider
                
                # Get config from AgentIMConfig (new system)
                agent_config = get_agent_im_config(agent_id)
                provider_config = agent_config.get_provider_config(provider_type)
                
                if not provider_config:
                    logger.error(f"[ServiceManager] No config found for agent={agent_id}, provider={provider_type}")
                    return
                
                provider = get_im_provider(provider_type, provider_config)
            else:
                logger.info(f"[ServiceManager] Reusing existing provider for agent={agent_id}, provider={provider_type}")
            
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
            logger.error(f"[ServiceManager] Error sending response back: {e}", exc_info=True)
    
    def find_provider_by_agent(self, agent_id: str, provider_type: str) -> Optional[Any]:
        """
        Find running provider instance by agent_id + provider_type.
        
        Args:
            agent_id: Agent identifier
            provider_type: IM provider type (wechat_work, feishu, etc.)
            
        Returns:
            Provider instance if found and connected, None otherwise
        """
        with self._lock:
            # In the new architecture, we use agent_id as the key component
            # The connection key format is: "{agent_id}:{provider_type}"
            target_key = f"{agent_id}:{provider_type}"
            
            for key, state in self._connections.items():
                if (key == target_key or 
                    (state.provider_type == provider_type and 
                     state.status == ChannelStatus.CONNECTED and 
                     state.provider)):
                    logger.debug(f"[ServiceManager] Found provider for agent={agent_id}, provider={provider_type}")
                    return state.provider
        
        return None


# Global service manager instance
_service_manager: Optional[IMServiceManager] = None


def get_service_manager() -> IMServiceManager:
    """Get or create global service manager instance."""
    global _service_manager
    if _service_manager is None:
        _service_manager = IMServiceManager()
    return _service_manager

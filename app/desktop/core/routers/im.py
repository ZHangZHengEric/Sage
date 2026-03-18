"""
IM Channel configuration router.

This module provides API endpoints for managing IM channel configurations.
Supports both global config (backward compatible) and per-Agent config (new architecture).

New Agent-level endpoints:
- GET/POST /api/agent/{agent_id}/im_channels
- GET/PUT/DELETE /api/agent/{agent_id}/im_channels/{provider}
- POST /api/agent/{agent_id}/im_channels/{provider}/test
"""

import logging
from typing import Optional, Dict, Any

from fastapi import APIRouter, Path as FastApiPath
from pydantic import BaseModel, Field

from ..core.render import Response
from ..models import IMChannelConfigDao

# Import new Agent IM Config system
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from mcp_servers.im_server.agent_config import (
    get_agent_im_config, 
    AgentIMConfig,
    DEFAULT_AGENT_ID,
    IMESSAGE_PROVIDER,
    validate_provider_config
)

logger = logging.getLogger(__name__)

# Default Sage user ID for desktop app (backward compatibility)
DEFAULT_SAGE_USER_ID = "desktop_default_user"


# ============================================================================
# Pydantic Models
# ============================================================================

class FeishuConfig(BaseModel):
    """Feishu configuration."""
    enabled: bool = False
    app_id: Optional[str] = None
    app_secret: Optional[str] = None


class DingTalkConfig(BaseModel):
    """DingTalk configuration."""
    enabled: bool = False
    client_id: Optional[str] = None
    client_secret: Optional[str] = None


class WeChatWorkConfig(BaseModel):
    """WeChat Work (企业微信) configuration for long connection mode."""
    enabled: bool = False
    bot_id: Optional[str] = None  # 智能机器人 BotID
    secret: Optional[str] = None  # 长连接专用 Secret


class IMessageConfig(BaseModel):
    """iMessage configuration."""
    enabled: bool = False
    mode: str = "database_poll"
    allowed_senders: list = []


class IMServiceStatus(BaseModel):
    """IM service status."""
    running: bool = False


class IMConfig(BaseModel):
    """Complete IM configuration (backward compatible)."""
    feishu: FeishuConfig = FeishuConfig()
    dingtalk: DingTalkConfig = DingTalkConfig()
    wechat_work: WeChatWorkConfig = WeChatWorkConfig()  # 企业微信配置
    imessage: IMessageConfig = IMessageConfig()
    service: IMServiceStatus = IMServiceStatus()


# ============================================================================
# New Agent-level Configuration Models
# ============================================================================

class ProviderConfigRequest(BaseModel):
    """Request model for saving provider configuration."""
    enabled: bool = Field(default=False, description="Whether this channel is enabled")
    config: Dict[str, Any] = Field(default_factory=dict, description="Provider-specific configuration")


class ProviderConfigResponse(BaseModel):
    """Response model for provider configuration."""
    provider: str = Field(..., description="Provider type")
    enabled: bool = Field(..., description="Whether this channel is enabled")
    config: Dict[str, Any] = Field(..., description="Provider-specific configuration")
    created_at: Optional[str] = Field(None, description="Creation timestamp")
    updated_at: Optional[str] = Field(None, description="Last update timestamp")


class AgentChannelsResponse(BaseModel):
    """Response model for all channels of an agent."""
    agent_id: str = Field(..., description="Agent identifier")
    channels: Dict[str, ProviderConfigResponse] = Field(..., description="All configured channels")


class TestConnectionResponse(BaseModel):
    """Response model for connection test."""
    success: bool = Field(..., description="Whether the test was successful")
    message: str = Field(..., description="Test result message")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional test details")


# Router
im_router = APIRouter(prefix="/api/im", tags=["im"])


@im_router.get("/config")
async def get_im_config():
    """Get IM channel configuration for desktop app."""
    logger.info("[IM] ========== GET /api/im/config ==========")
    try:
        dao = IMChannelConfigDao()
        logger.info("[IM] DAO created")
        
        # Get all configs for default user
        all_configs = await dao.get_all_configs(sage_user_id=DEFAULT_SAGE_USER_ID)
        logger.info(f"[IM] Retrieved {len(all_configs)} provider configs")
        
        # Build response
        result = {
            "feishu": all_configs.get("feishu", {}),
            "dingtalk": all_configs.get("dingtalk", {}),
            "wechat_work": all_configs.get("wechat_work", {}),
            "imessage": all_configs.get("imessage", {}),
            "service": {"running": False}  # TODO: get actual service status
        }
        
        logger.info("[IM] Returning config from database:")
        logger.info(f"[IM]   feishu: {result['feishu']}")
        logger.info(f"[IM]   dingtalk: {result['dingtalk']}")
        logger.info(f"[IM]   wechat_work: {result['wechat_work']}")
        logger.info(f"[IM]   imessage: {result['imessage']}")
        logger.info("[IM] ========== END GET /api/im/config ==========")
        
        return await Response.succ(data=result, message="获取配置成功")
        
    except Exception as e:
        logger.error("[IM] ========== ERROR GET /api/im/config ==========")
        logger.error(f"[IM] Failed to get config: {e}", exc_info=True)
        logger.error("[IM] ========== END ERROR ==========")
        return await Response.error(code=500, message=f"获取配置失败: {str(e)}")


@im_router.post("/config")
async def save_im_config(config: IMConfig):
    """Save IM channel configuration for desktop app."""
    logger.info("[IM] ========== POST /api/im/config ==========")
    logger.info(f"[IM] Request data: {config.dict()}")

    try:
        dao = IMChannelConfigDao()
        logger.info("[IM] DAO created")

        # Save each provider config
        providers = [
            ("feishu", config.feishu.dict()),
            ("dingtalk", config.dingtalk.dict()),
            ("wechat_work", config.wechat_work.dict()),
            ("imessage", config.imessage.dict()),
        ]

        enabled_providers = []
        for provider_type, provider_config in providers:
            logger.info(f"[IM] Saving {provider_type} config: {provider_config}")
            await dao.save_config(provider_type, provider_config, sage_user_id=DEFAULT_SAGE_USER_ID)
            logger.info(f"[IM] {provider_type} config saved to database")
            if provider_config.get('enabled', False):
                enabled_providers.append(provider_type)

        logger.info("[IM] All configs saved successfully")

        # Also save to IM Server DB for multi-tenant support
        try:
            from mcp_servers.im_server.db import get_im_db
            im_db = get_im_db()
            
            for provider_type, provider_config in providers:
                # Save to IM server DB with default user ID
                im_db.save_user_config(
                    sage_user_id=DEFAULT_SAGE_USER_ID,
                    provider=provider_type,
                    config=provider_config,
                    enabled=provider_config.get('enabled', False)
                )
                logger.info(f"[IM] {provider_type} config saved to IM server DB")
        except Exception as e:
            logger.warning(f"[IM] Failed to save to IM server DB: {e}")
            # Don't fail if IM server DB save fails

        # Manage IM service channels - start enabled, stop disabled
        try:
            import asyncio
            from mcp_servers.im_server.service_manager import get_service_manager
            
            manager = get_service_manager()
            
            # Start service manager if not running
            await manager.start()
            
            # Process each provider: start if enabled, stop if disabled
            for provider_type, provider_config in providers:
                is_enabled = provider_config.get('enabled', False)
                
                if is_enabled:
                    # Start enabled channel
                    logger.info(f"[IM] Starting {provider_type} channel...")
                    asyncio.create_task(manager.start_channel(DEFAULT_SAGE_USER_ID, provider_type))
                    logger.info(f"[IM] {provider_type} channel started")
                else:
                    # Stop disabled channel
                    logger.info(f"[IM] Stopping {provider_type} channel (disabled)...")
                    await manager.stop_channel(DEFAULT_SAGE_USER_ID, provider_type)
                    logger.info(f"[IM] {provider_type} channel stopped")
            
            logger.info("[IM] IM service channels managed successfully")
        except Exception as e:
            logger.error(f"[IM] Failed to manage IM service channels: {e}")
            # Don't fail the save if service management fails

        logger.info("[IM] ========== END POST /api/im/config ==========")

        return await Response.succ(data=config.dict(), message="保存配置成功")

    except Exception as e:
        logger.error("[IM] ========== ERROR POST /api/im/config ==========")
        logger.error(f"[IM] Failed to save config: {e}", exc_info=True)
        logger.error("[IM] ========== END ERROR ==========")
        return await Response.error(code=500, message=f"保存配置失败: {str(e)}")


@im_router.get("/service/status")
async def get_im_service_status():
    """Get IM service status."""
    logger.info("[IM] GET /api/im/service/status")
    
    try:
        from mcp_servers.im_server.service_manager import get_service_manager
        
        manager = get_service_manager()
        channels = manager.list_user_channels(DEFAULT_SAGE_USER_ID)
        
        # Build status response
        providers_status = {
            "feishu": {"enabled": False, "connected": False, "status": "inactive"},
            "dingtalk": {"enabled": False, "connected": False, "status": "inactive"},
            "wechat_work": {"enabled": False, "connected": False, "status": "inactive"},
            "imessage": {"enabled": False, "connected": False, "status": "inactive"},
        }
        
        any_running = False
        for channel in channels:
            provider = channel.get('provider_type')
            if provider in providers_status:
                providers_status[provider] = {
                    "enabled": channel.get('is_enabled', False),
                    "connected": channel.get('status') == 'connected',
                    "status": channel.get('status', 'inactive'),
                    "error": channel.get('error_message')
                }
                if channel.get('status') in ['connected', 'connecting']:
                    any_running = True
        
        return await Response.succ(
            data={
                "running": any_running,
                "providers": providers_status
            },
            message="获取服务状态成功"
        )
        
    except Exception as e:
        logger.error(f"[IM] Failed to get service status: {e}")
        return await Response.succ(
            data={
                "running": False,
                "providers": {
                    "feishu": {"enabled": False, "connected": False, "status": "error", "error": str(e)},
                    "dingtalk": {"enabled": False, "connected": False, "status": "error", "error": str(e)},
                    "wechat_work": {"enabled": False, "connected": False, "status": "error", "error": str(e)},
                    "imessage": {"enabled": False, "connected": False, "status": "error", "error": str(e)},
                }
            },
            message="获取服务状态失败"
        )


@im_router.post("/service/start")
async def start_im_service():
    """Start IM service."""
    logger.info("[IM] POST /api/im/service/start")
    
    try:
        from mcp_servers.im_server.service_manager import get_service_manager
        
        manager = get_service_manager()
        await manager.start()
        
        return await Response.succ(message="IM服务已启动")
        
    except Exception as e:
        logger.error(f"[IM] Failed to start service: {e}")
        return await Response.error(code=500, message=f"启动IM服务失败: {str(e)}")


@im_router.post("/service/stop")
async def stop_im_service():
    """Stop IM service."""
    logger.info("[IM] POST /api/im/service/stop")
    
    try:
        from mcp_servers.im_server.service_manager import get_service_manager
        
        manager = get_service_manager()
        await manager.stop()
        
        return await Response.succ(message="IM服务已停止")
        
    except Exception as e:
        logger.error(f"[IM] Failed to stop service: {e}")
        return await Response.error(code=500, message=f"停止IM服务失败: {str(e)}")


@im_router.post("/channels/{provider_type}/restart")
async def restart_im_channel(provider_type: str):
    """Restart specific IM channel."""
    logger.info(f"[IM] POST /api/im/channels/{provider_type}/restart")
    
    try:
        from mcp_servers.im_server.service_manager import get_service_manager
        
        manager = get_service_manager()
        result = await manager.restart_channel(DEFAULT_SAGE_USER_ID, provider_type)
        
        if result:
            return await Response.succ(message=f"{provider_type}渠道已重启")
        else:
            return await Response.error(code=500, message=f"重启{provider_type}渠道失败")
        
    except Exception as e:
        logger.error(f"[IM] Failed to restart channel: {e}")
        return await Response.error(code=500, message=f"重启渠道失败: {str(e)}")
# Append to the end of app/desktop/core/routers/im.py


# ============================================================================
# New Agent-level IM Configuration API
# ============================================================================

@im_router.get("/agent/{agent_id}/im_channels")
async def get_agent_im_channels(agent_id: str = FastApiPath(..., description="Agent ID")):
    """
    Get all IM channel configurations for an Agent.
    
    Returns the complete IM channel configuration for the specified Agent,
    including all providers (wechat_work, dingtalk, feishu, imessage).
    """
    logger.info(f"[IM Agent] GET /api/agent/{agent_id}/im_channels")
    
    try:
        # Get Agent IM Config
        agent_config = get_agent_im_config(agent_id)
        channels = agent_config.get_all_channels()
        
        # Convert to response format
        result_channels = {}
        for provider, channel_data in channels.items():
            result_channels[provider] = ProviderConfigResponse(
                provider=provider,
                enabled=channel_data.get("enabled", False),
                config=channel_data.get("config", {}),
                updated_at=channel_data.get("updated_at")
            )
        
        return await Response.succ(
            data={
                "agent_id": agent_id,
                "channels": result_channels
            },
            message="获取成功"
        )
        
    except Exception as e:
        logger.error(f"[IM Agent] Failed to get channels: {e}", exc_info=True)
        return await Response.error(code=500, message=f"获取配置失败: {str(e)}")


@im_router.post("/agent/{agent_id}/im_channels")
async def save_agent_im_channels(
    agent_id: str = FastApiPath(..., description="Agent ID"),
    channels: Dict[str, ProviderConfigRequest] = None
):
    """
    Save all IM channel configurations for an Agent.
    
    Replaces the entire channel configuration for the Agent.
    Auto-restarts enabled channels after saving.
    """
    logger.info(f"[IM Agent] POST /api/agent/{agent_id}/im_channels")
    
    if channels is None:
        channels = {}
    
    try:
        agent_config = get_agent_im_config(agent_id)
        results = []
        restarted = []
        
        for provider, config_request in channels.items():
            # Validate (especially for iMessage)
            try:
                validate_provider_config(agent_id, provider, config_request.config)
                
                # Save config
                success = agent_config.set_provider_config(
                    provider=provider,
                    enabled=config_request.enabled,
                    config=config_request.config
                )
                
                if success:
                    results.append({"provider": provider, "status": "saved"})
                    logger.info(f"[IM Agent] Saved {provider} config for agent={agent_id}")
                    
                    # Auto-restart enabled channels
                    if config_request.enabled:
                        try:
                            from mcp_servers.im_server.service_manager import get_service_manager
                            manager = get_service_manager()
                            # Use agent_id as sage_user_id for channel management
                            restart_result = await manager.restart_channel(agent_id, provider)
                            if restart_result:
                                restarted.append(provider)
                                logger.info(f"[IM Agent] Auto-restarted {provider} channel for agent={agent_id}")
                        except Exception as e:
                            logger.warning(f"[IM Agent] Failed to auto-restart {provider}: {e}")
                else:
                    results.append({"provider": provider, "status": "failed", "error": "Save failed"})
                    
            except ValueError as ve:
                logger.warning(f"[IM Agent] Validation failed for {provider}: {ve}")
                results.append({"provider": provider, "status": "skipped", "error": str(ve)})
        
        msg = f"已保存 {len([r for r in results if r['status'] == 'saved'])} 个配置"
        if restarted:
            msg += f"，已重启 {', '.join(restarted)} 渠道"
        
        return await Response.succ(
            data={"agent_id": agent_id, "results": results, "restarted": restarted},
            message=msg
        )
        
    except Exception as e:
        logger.error(f"[IM Agent] Failed to save channels: {e}", exc_info=True)
        return await Response.error(code=500, message=f"保存配置失败: {str(e)}")


@im_router.get("/agent/{agent_id}/im_channels/{provider}")
async def get_agent_im_channel(
    agent_id: str = FastApiPath(..., description="Agent ID"),
    provider: str = FastApiPath(..., description="Provider type (wechat_work, dingtalk, feishu, imessage)")
):
    """Get specific IM channel configuration for an Agent."""
    logger.info(f"[IM Agent] GET /api/agent/{agent_id}/im_channels/{provider}")
    
    try:
        agent_config = get_agent_im_config(agent_id)
        config = agent_config.get_provider_config(provider)
        
        if config is None:
            # Channel not configured or disabled
            all_channels = agent_config.get_all_channels()
            if provider in all_channels:
                channel_data = all_channels[provider]
                return await Response.succ(
                    data=ProviderConfigResponse(
                        provider=provider,
                        enabled=channel_data.get("enabled", False),
                        config=channel_data.get("config", {}),
                        updated_at=channel_data.get("updated_at")
                    ),
                    message="获取成功"
                )
            else:
                return await Response.error(code=404, message=f"未找到 {provider} 配置")
        
        # Channel is enabled
        return await Response.succ(
            data=ProviderConfigResponse(
                provider=provider,
                enabled=True,
                config=config
            ),
            message="获取成功"
        )
        
    except Exception as e:
        logger.error(f"[IM Agent] Failed to get channel: {e}", exc_info=True)
        return await Response.error(code=500, message=f"获取配置失败: {str(e)}")


@im_router.put("/agent/{agent_id}/im_channels/{provider}")
async def update_agent_im_channel(
    agent_id: str = FastApiPath(..., description="Agent ID"),
    provider: str = FastApiPath(..., description="Provider type"),
    config_request: ProviderConfigRequest = None
):
    """
    Update specific IM channel configuration for an Agent.
    
    Creates new config if not exists, updates existing config.
    Validates iMessage restriction (only default agent).
    """
    logger.info(f"[IM Agent] PUT /api/agent/{agent_id}/im_channels/{provider}")
    
    if config_request is None:
        return await Response.error(code=400, message="请求体不能为空")
    
    try:
        # Validate (especially for iMessage)
        validate_provider_config(agent_id, provider, config_request.config)
        
        # Save config
        agent_config = get_agent_im_config(agent_id)
        success = agent_config.set_provider_config(
            provider=provider,
            enabled=config_request.enabled,
            config=config_request.config
        )
        
        if success:
            logger.info(f"[IM Agent] Updated {provider} config for agent={agent_id}")
            return await Response.succ(
                data={"agent_id": agent_id, "provider": provider, "enabled": config_request.enabled},
                message="保存成功"
            )
        else:
            return await Response.error(code=500, message="保存失败")
            
    except ValueError as ve:
        logger.warning(f"[IM Agent] Validation failed: {ve}")
        return await Response.error(code=403, message=str(ve))
    except Exception as e:
        logger.error(f"[IM Agent] Failed to update channel: {e}", exc_info=True)
        return await Response.error(code=500, message=f"保存失败: {str(e)}")


@im_router.delete("/agent/{agent_id}/im_channels/{provider}")
async def delete_agent_im_channel(
    agent_id: str = FastApiPath(..., description="Agent ID"),
    provider: str = FastApiPath(..., description="Provider type")
):
    """Delete specific IM channel configuration for an Agent."""
    logger.info(f"[IM Agent] DELETE /api/agent/{agent_id}/im_channels/{provider}")
    
    try:
        agent_config = get_agent_im_config(agent_id)
        success = agent_config.remove_provider(provider)
        
        if success:
            logger.info(f"[IM Agent] Deleted {provider} config for agent={agent_id}")
            return await Response.succ(message="删除成功")
        else:
            return await Response.error(code=500, message="删除失败")
            
    except Exception as e:
        logger.error(f"[IM Agent] Failed to delete channel: {e}", exc_info=True)
        return await Response.error(code=500, message=f"删除失败: {str(e)}")


class TestConnectionRequest(BaseModel):
    """Request model for testing connection with provided config."""
    config: Optional[Dict[str, Any]] = Field(None, description="Provider configuration to test")


@im_router.post("/agent/{agent_id}/im_channels/{provider}/test")
async def test_agent_im_connection(
    request: TestConnectionRequest,
    agent_id: str = FastApiPath(..., description="Agent ID"),
    provider: str = FastApiPath(..., description="Provider type")
):
    """
    Test IM connection for an Agent.
    
    Attempts to connect to the IM provider using the provided configuration
    or stored configuration and returns connection test result.
    """
    logger.info(f"[IM Agent] POST /api/agent/{agent_id}/im_channels/{provider}/test")
    
    try:
        # Get config: use provided config if available, otherwise use stored config
        if request.config:
            config = request.config
            logger.info(f"[IM Agent] Using provided config for testing {provider}")
        else:
            agent_config = get_agent_im_config(agent_id)
            config = agent_config.get_provider_config(provider)
            
        if not config:
            return await Response.error(
                code=404, 
                message=f"未找到 {provider} 配置或配置未启用，请先保存配置或传入配置参数"
            )
        
        # Test connection based on provider type
        if provider == "wechat_work":
            # Test WeChat Work connection using temporary WebSocket connection
            import asyncio
            import websockets
            import json
            
            bot_id = config.get("bot_id")
            secret = config.get("secret")
            
            if not bot_id or not secret:
                return await Response.succ(
                    data=TestConnectionResponse(
                        success=False,
                        message="缺少 BotID 或 Secret 配置",
                        details={}
                    ),
                    message="配置不完整"
                )
            
            try:
                # Use temporary WebSocket connection to test credentials
                ws_url = "wss://openws.work.weixin.qq.com"
                
                async def test_wechat_connection():
                    async with websockets.connect(ws_url, ping_interval=None) as ws:
                        # Send subscribe request
                        subscribe_msg = {
                            "cmd": "aibot_subscribe",
                            "headers": {"req_id": str(__import__('uuid').uuid4())},
                            "body": {"bot_id": bot_id, "secret": secret}
                        }
                        await ws.send(json.dumps(subscribe_msg))
                        
                        # Wait for subscribe response
                        response = await asyncio.wait_for(ws.recv(), timeout=10)
                        data = json.loads(response)
                        
                        return data.get("errcode", -1), data.get("errmsg", "未知错误")
                
                errcode, errmsg = await asyncio.wait_for(test_wechat_connection(), timeout=15)
                
                if errcode == 0:
                    return await Response.succ(
                        data=TestConnectionResponse(
                            success=True,
                            message="企业微信连接测试成功",
                            details={"bot_id": bot_id}
                        ),
                        message="连接测试成功"
                    )
                elif errcode == 40014:
                    return await Response.succ(
                        data=TestConnectionResponse(
                            success=False,
                            message="BotID 或 Secret 无效，请检查配置",
                            details={"error": errmsg, "errcode": errcode}
                        ),
                        message="连接测试失败"
                    )
                else:
                    return await Response.succ(
                        data=TestConnectionResponse(
                            success=False,
                            message=f"连接测试失败: {errmsg} (错误码: {errcode})",
                            details={"errcode": errcode}
                        ),
                        message="连接测试失败"
                    )
                    
            except asyncio.TimeoutError:
                logger.error("[IM Agent] WeChat Work test connection timeout")
                return await Response.succ(
                    data=TestConnectionResponse(
                        success=False,
                        message="连接超时，请检查网络连接",
                        details={}
                    ),
                    message="连接测试失败"
                )
            except Exception as e:
                logger.error(f"[IM Agent] WeChat Work test failed: {e}", exc_info=True)
                return await Response.succ(
                    data=TestConnectionResponse(
                        success=False,
                        message=f"连接测试失败: {str(e)}",
                        details={}
                    ),
                    message="连接测试失败"
                )
        
        elif provider == "dingtalk":
            # TODO: Implement DingTalk connection test
            return await Response.succ(
                data=TestConnectionResponse(
                    success=False,
                    message="钉钉连接测试功能开发中",
                    details={}
                ),
                message="功能开发中"
            )
        
        elif provider == "feishu":
            # TODO: Implement Feishu connection test
            return await Response.succ(
                data=TestConnectionResponse(
                    success=False,
                    message="飞书连接测试功能开发中",
                    details={}
                ),
                message="功能开发中"
            )
        
        elif provider == "imessage":
            # iMessage doesn't need connection test (uses local database)
            return await Response.succ(
                data=TestConnectionResponse(
                    success=True,
                    message="iMessage 配置正确（本地模式无需连接测试）",
                    details={"mode": "database_poll"}
                ),
                message="配置检查通过"
            )
        
        else:
            return await Response.error(code=400, message=f"不支持的 Provider: {provider}")
            
    except Exception as e:
        logger.error(f"[IM Agent] Test connection failed: {e}", exc_info=True)
        return await Response.error(code=500, message=f"测试连接失败: {str(e)}")


@im_router.post("/agent/{agent_id}/im_channels/{provider}/restart")
async def restart_agent_im_channel(
    agent_id: str = FastApiPath(..., description="Agent ID"),
    provider: str = FastApiPath(..., description="Provider type")
):
    """Restart IM channel service for an Agent."""
    logger.info(f"[IM Agent] POST /api/agent/{agent_id}/im_channels/{provider}/restart")
    
    try:
        from mcp_servers.im_server.service_manager import get_service_manager
        
        manager = get_service_manager()
        
        # Use agent_id as sage_user_id for channel management
        result = await manager.restart_channel(agent_id, provider)
        
        if result:
            logger.info(f"[IM Agent] Restarted {provider} channel for agent={agent_id}")
            return await Response.succ(message=f"{provider} 渠道已重启")
        else:
            return await Response.error(code=500, message=f"重启 {provider} 渠道失败")
            
    except Exception as e:
        logger.error(f"[IM Agent] Failed to restart channel: {e}", exc_info=True)
        return await Response.error(code=500, message=f"重启失败: {str(e)}")

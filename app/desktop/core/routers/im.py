"""IM Channel configuration router."""

import logging
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from ..core.render import Response
from ..models import IMChannelConfigDao

logger = logging.getLogger(__name__)

# Default Sage user ID for desktop app
DEFAULT_SAGE_USER_ID = "desktop_default_user"


# Pydantic Models
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
    """Complete IM configuration."""
    feishu: FeishuConfig = FeishuConfig()
    dingtalk: DingTalkConfig = DingTalkConfig()
    wechat_work: WeChatWorkConfig = WeChatWorkConfig()  # 企业微信配置
    imessage: IMessageConfig = IMessageConfig()
    service: IMServiceStatus = IMServiceStatus()


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

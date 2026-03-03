"""IM Channel configuration router."""

import logging
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from ..core.render import Response
from ..models import IMChannelConfigDao

logger = logging.getLogger(__name__)


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
        
        # Get all configs
        all_configs = await dao.get_all_configs()
        logger.info(f"[IM] Retrieved {len(all_configs)} provider configs")
        
        # Build response
        result = {
            "feishu": all_configs.get("feishu", {}),
            "dingtalk": all_configs.get("dingtalk", {}),
            "imessage": all_configs.get("imessage", {}),
            "service": {"running": False}  # TODO: get actual service status
        }
        
        logger.info(f"[IM] Returning config: feishu={result['feishu'].get('enabled', False)}, dingtalk={result['dingtalk'].get('enabled', False)}, imessage={result['imessage'].get('enabled', False)}")
        logger.info("[IM] ========== END GET /api/im/config ==========")
        
        return await Response.succ(data=result, message="获取配置成功")
        
    except Exception as e:
        logger.error(f"[IM] ========== ERROR GET /api/im/config ==========")
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
            ("imessage", config.imessage.dict()),
        ]
        
        for provider_type, provider_config in providers:
            logger.info(f"[IM] Saving {provider_type} config: enabled={provider_config.get('enabled', False)}")
            await dao.save_config(provider_type, provider_config)
            logger.info(f"[IM] {provider_type} config saved")
        
        logger.info("[IM] All configs saved successfully")
        logger.info("[IM] ========== END POST /api/im/config ==========")
        
        return await Response.succ(data=config.dict(), message="保存配置成功")
        
    except Exception as e:
        logger.error(f"[IM] ========== ERROR POST /api/im/config ==========")
        logger.error(f"[IM] Failed to save config: {e}", exc_info=True)
        logger.error("[IM] ========== END ERROR ==========")
        return await Response.error(code=500, message=f"保存配置失败: {str(e)}")


@im_router.get("/service/status")
async def get_im_service_status():
    """Get IM service status."""
    logger.info("[IM] GET /api/im/service/status")
    return await Response.succ(
        data={
            "running": False,
            "providers": {
                "feishu": {"enabled": False, "connected": False},
                "dingtalk": {"enabled": False, "connected": False},
                "imessage": {"enabled": False, "connected": False},
            }
        },
        message="获取服务状态成功"
    )

"""IM Channel configuration router."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..models import IMChannelConfigDao

logger = logging.getLogger(__name__)

# Use a fixed user_id for desktop app (single user)
DESKTOP_USER_ID = "desktop_user"


# Pydantic Models
class IMProviderConfig(BaseModel):
    """Base IM provider configuration."""
    enabled: bool = False


class FeishuConfig(IMProviderConfig):
    """Feishu configuration."""
    app_id: Optional[str] = None
    app_secret: Optional[str] = None


class DingTalkConfig(IMProviderConfig):
    """DingTalk configuration."""
    client_id: Optional[str] = None
    client_secret: Optional[str] = None


class IMessageConfig(IMProviderConfig):
    """iMessage configuration."""
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


@im_router.get("/config", response_model=IMConfig)
async def get_im_config():
    """Get IM channel configuration for desktop user."""
    logger.info(f"[IM] Getting config for user: {DESKTOP_USER_ID}")
    try:
        dao = IMChannelConfigDao()
        logger.debug(f"[IM] DAO created, querying database...")
        
        config_record = await dao.get_by_user_id(DESKTOP_USER_ID)
        
        if config_record:
            logger.info(f"[IM] Config found for user: {DESKTOP_USER_ID}")
            logger.debug(f"[IM] Config data: {config_record.config}")
            
            # Log provider status
            config_data = config_record.config
            for provider in ['feishu', 'dingtalk', 'imessage']:
                provider_config = config_data.get(provider, {})
                enabled = provider_config.get('enabled', False)
                logger.info(f"[IM] Provider '{provider}' enabled: {enabled}")
            
            return IMConfig(**config_data)
        
        logger.info(f"[IM] No config found for user: {DESKTOP_USER_ID}, returning default")
        return IMConfig()
        
    except Exception as e:
        logger.error(f"[IM] Failed to get config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@im_router.post("/config", response_model=IMConfig)
async def save_im_config(config: IMConfig):
    """Save IM channel configuration for desktop user."""
    logger.info(f"[IM] Saving config for user: {DESKTOP_USER_ID}")
    logger.debug(f"[IM] Config data: {config.dict()}")
    
    try:
        dao = IMChannelConfigDao()
        logger.debug(f"[IM] DAO created, saving to database...")
        
        await dao.save_config(DESKTOP_USER_ID, config.dict())
        logger.info(f"[IM] Config saved successfully for user: {DESKTOP_USER_ID}")
        
        # Log which providers are enabled
        for provider in ['feishu', 'dingtalk', 'imessage']:
            provider_config = getattr(config, provider)
            enabled = provider_config.enabled if provider_config else False
            logger.info(f"[IM] Provider '{provider}' saved with enabled: {enabled}")
        
        # Handle service start/stop based on config
        if config.service.running:
            logger.info("[IM] Service is set to running, starting IM service...")
            await _start_im_service(config)
        else:
            logger.info("[IM] Service is set to stopped, stopping IM service...")
            await _stop_im_service()
        
        return config
        
    except Exception as e:
        logger.error(f"[IM] Failed to save config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


async def _start_im_service(config: IMConfig):
    """Start IM service with current configuration."""
    logger.info("[IM] Starting IM service...")
    try:
        from mcp_servers.im_server.im_server import initialize_im_server
        import asyncio
        
        # Log which providers will be started
        enabled_providers = []
        if config.feishu.enabled:
            enabled_providers.append('feishu')
        if config.dingtalk.enabled:
            enabled_providers.append('dingtalk')
        if config.imessage.enabled:
            enabled_providers.append('imessage')
        
        logger.info(f"[IM] Starting IM service with providers: {enabled_providers}")
        
        asyncio.create_task(initialize_im_server())
        logger.info("[IM] IM service start task created")
        
    except Exception as e:
        logger.error(f"[IM] Failed to start IM service: {e}", exc_info=True)
        raise


async def _stop_im_service():
    """Stop IM service."""
    logger.info("[IM] Stopping IM service...")
    # TODO: Implement stop logic
    logger.info("[IM] IM service stopped")
    pass


@im_router.get("/service/status")
async def get_im_service_status():
    """Get IM service status."""
    logger.debug("[IM] Getting service status")
    return {
        "running": False,
        "providers": {
            "feishu": {"enabled": False, "connected": False},
            "dingtalk": {"enabled": False, "connected": False},
            "imessage": {"enabled": False, "connected": False},
        }
    }

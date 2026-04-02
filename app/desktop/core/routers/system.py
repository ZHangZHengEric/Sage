import time

from fastapi import APIRouter, Request

import os
import httpx
from common.schemas.base import (
    AgentUsageStatsRequest,
    AgentUsageStatsResponse,
    BaseResponse,
    SystemSettingsRequest,
    TauriUpdateResponse,
)
from common.core.render import Response
from common.models.system import SystemInfoDao
from common.models.llm_provider import LLMProviderDao
from common.models.agent import AgentConfigDao
from common.services.chat_utils import get_sessions_root
from ..services.agent_usage_stats import analyze_tools_usage

# 创建路由器
system_router = APIRouter(prefix="/api", tags=["System"])


@system_router.get("/system/version/check", response_model=TauriUpdateResponse)
async def check_version():
    """
    检查更新接口
    Tauri Updater 会调用此接口。
    此处作为 Proxy，请求远程服务器获取最新版本信息，并转换为 Tauri 需要的格式。
    """
    remote_url = os.getenv("SAGE_UPDATE_URL", "https://api.sage.com/version/check")
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(remote_url, timeout=10.0)
            response.raise_for_status()
            user_data = response.json()
    except Exception as e:
        # Fallback or error handling
        # In a real scenario, you might want to return an empty response or log the error
        # Here we return a default/empty response to avoid crashing the client
        return TauriUpdateResponse(
            version="0.0.0",
            notes=f"Check failed: {str(e)}",
            pub_date="",
            platforms={}
        )
    
    data = user_data.get("data", {})
    artifacts = data.get("artifacts", [])
    
    platforms = {}
    for artifact in artifacts:
        platform_key = artifact.get("platform")
        if platform_key:
            platforms[platform_key] = {
                "url": artifact.get("url"),
                "signature": artifact.get("signature", "")
            }
            
    # Tauri prefers UTC ISO format with Z
    pub_date = data.get("pub_date", "")
    if pub_date and not pub_date.endswith("Z") and "+" not in pub_date:
        pub_date += "Z"
        
    return TauriUpdateResponse(
        version=data.get("version", "0.0.0"),
        notes=data.get("release_notes", ""),
        pub_date=pub_date,
        platforms=platforms
    )


@system_router.get("/system/info")
async def get_system_info():
    sys_dao = SystemInfoDao()
    # allow_reg = await sys_dao.get_by_key("allow_registration")
    
    # Check for model providers
    llm_dao = LLMProviderDao()
    providers = await llm_dao.get_list()
    has_model_provider = len(providers) > 0
    
    # Check for agents
    agent_dao = AgentConfigDao()
    agents = await agent_dao.get_list()
    has_agent = len(agents) > 0

    return await Response.succ(
        data={
            "allow_registration": False, # Disabled as per requirement
            "has_model_provider": has_model_provider,
            "has_agent": has_agent
        },
        message="获取系统信息成功"
    )

@system_router.post("/system/update_settings", response_model=BaseResponse[dict])
async def update_system_settings(request: Request, req: SystemSettingsRequest):
    claims = getattr(request.state, "user_claims", {}) or {}
    role = claims.get("role")
    if role != "admin":
        return await Response.error(code=403, message="权限不足", error_detail="permission denied")

    sys_dao = SystemInfoDao()
    await sys_dao.set_value("allow_registration", "true" if req.allow_registration else "false")
    return await Response.succ(data={}, message="系统设置更新成功")


@system_router.get("/health")
async def health_check():
    return await Response.succ(
        message="服务运行正常",
        data={
            "status": "healthy",
            "timestamp": time.time(),
            "service": "SagePlatform",
        },
    )


@system_router.post(
    "/system/agent/usage-stats",
    response_model=BaseResponse[AgentUsageStatsResponse],
)
async def get_agent_usage_stats(req: AgentUsageStatsRequest):
    """
    获取最近 N 天的 Agent 工具使用统计。
    """
    sessions_root = get_sessions_root()
    stats = analyze_tools_usage(sessions_root, days=req.days)
    return await Response.succ(
        message="获取 Agent 工具使用统计成功",
        data=AgentUsageStatsResponse(usage=stats).model_dump(),
    )

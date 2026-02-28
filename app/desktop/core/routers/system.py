import time

from fastapi import APIRouter, Request

from ..core.render import Response
from ..models import SystemInfoDao, LLMProviderDao, AgentConfigDao
from ..schemas.base import BaseResponse
from ..schemas.system import SystemSettingsRequest

# 创建路由器
system_router = APIRouter(prefix="/api", tags=["System"])


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

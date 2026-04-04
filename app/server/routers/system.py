import time

from fastapi import APIRouter, Request

from common.core.render import Response
from common.services import conversation_service
from common.services.oauth.upstream import get_auth_public_config
from common.schemas.base import (
    AgentUsageStatsRequest,
    BaseResponse,
    SystemSettingsRequest,
)
from common.models.system import SystemInfoDao

# 创建路由器
system_router = APIRouter(prefix="/api", tags=["System"])


@system_router.get("/system/info")
async def get_system_info():
    sys_dao = SystemInfoDao()
    allow_reg = await sys_dao.get_by_key("allow_registration")
    auth_config = get_auth_public_config()
    return await Response.succ(
        data={
            "allow_registration": allow_reg != "false",
            **auth_config,
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


@system_router.post("/system/agent/usage-stats")
async def get_agent_usage_stats(request: Request, req: AgentUsageStatsRequest):
    claims = getattr(request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    usage = await conversation_service.get_agent_usage_stats(
        days=req.days,
        user_id=user_id,
        agent_id=req.agent_id,
    )
    return await Response.succ(
        data={"usage": usage},
        message="获取 Agent 使用统计成功",
    )

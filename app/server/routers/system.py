from fastapi import APIRouter, Request

from common.core.request_identity import get_request_role, get_request_user_id
from common.core.render import Response
from common.services import system_service, token_usage_service
from common.schemas.base import (
    AgentUsageStatsRequest,
    BaseResponse,
    SystemSettingsRequest,
    TokenUsageStatsRequest,
    TokenUsageStatsResponse,
)

# 创建路由器
system_router = APIRouter(prefix="/api", tags=["System"])


@system_router.get("/system/info")
async def get_system_info():
    return await Response.succ(
        data=await system_service.get_system_info_data(include_auth_config=True),
        message="获取系统信息成功"
    )

@system_router.post("/system/update_settings", response_model=BaseResponse[dict])
async def update_system_settings(request: Request, req: SystemSettingsRequest):
    if get_request_role(request) != "admin":
        return await Response.error(code=403, message="权限不足", error_detail="permission denied")

    await system_service.update_allow_registration(req.allow_registration)
    return await Response.succ(data={}, message="系统设置更新成功")


@system_router.get("/health")
async def health_check():
    return await Response.succ(
        message="服务运行正常",
        data=system_service.get_health_data(),
    )


@system_router.post("/system/agent/usage-stats")
async def get_agent_usage_stats(request: Request, req: AgentUsageStatsRequest):
    usage = await system_service.get_agent_usage_stats_data(
        days=req.days,
        user_id=get_request_user_id(request),
        agent_id=req.agent_id,
    )
    return await Response.succ(
        data={"usage": usage},
        message="获取 Agent 使用统计成功",
    )


@system_router.post(
    "/token-usage/stats",
    response_model=BaseResponse[TokenUsageStatsResponse],
)
async def get_token_usage_stats(req: TokenUsageStatsRequest):
    stats = await token_usage_service.get_token_usage_stats(
        group_by=req.group_by,
        user_id=req.user_id,
        agent_id=req.agent_id,
        session_id=req.session_id,
        start_time=req.start_time,
        end_time=req.end_time,
    )
    return await Response.succ(
        data=TokenUsageStatsResponse(**stats).model_dump(exclude_none=True),
        message="获取 Token 使用统计成功",
    )

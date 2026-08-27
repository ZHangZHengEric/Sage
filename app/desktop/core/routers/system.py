from fastapi import APIRouter, Request
from common.core.render import Response
from common.schemas.base import (
    AgentUsageStatsRequest,
    AgentUsageStatsResponse,
    BaseResponse,
    SystemSettingsRequest,
    TokenUsageStatsRequest,
    TokenUsageStatsResponse,
)
from common.services import system_service, token_usage_service
from ..user_context import get_desktop_user_id

# 创建路由器
system_router = APIRouter(prefix="/api", tags=["System"])


@system_router.get("/system/info")
async def get_system_info(request: Request):
    user_id = get_desktop_user_id(request)
    data = await system_service.get_system_info_data(
        user_id=user_id,
        include_desktop_flags=True,
    )
    data["allow_registration"] = False
    return await Response.succ(data=data, message="system.info_loaded")


@system_router.post("/system/update_settings", response_model=BaseResponse[dict])
async def update_system_settings(request: Request, req: SystemSettingsRequest):
    claims = getattr(request.state, "user_claims", {}) or {}
    role = claims.get("role")
    if role != "admin":
        return await Response.error(
            code=403,
            message="common.permission_denied",
            error_detail="permission denied",
        )

    await system_service.update_allow_registration(req.allow_registration)
    return await Response.succ(data={}, message="system.settings_updated")


@system_router.get("/health")
async def health_check():
    return await Response.succ(
        message="system.healthy",
        data=system_service.get_health_data(),
    )


@system_router.post(
    "/system/agent/usage-stats",
    response_model=BaseResponse[AgentUsageStatsResponse],
)
async def get_agent_usage_stats(req: AgentUsageStatsRequest, request: Request):
    """
    获取最近 N 天的 Agent 工具使用统计。
    """
    stats = await system_service.get_agent_usage_stats_data(
        days=req.days,
        user_id=get_desktop_user_id(request),
        agent_id=req.agent_id,
    )
    return await Response.succ(
        message="system.agent_usage_loaded",
        data=AgentUsageStatsResponse(usage=stats).model_dump(),
    )


@system_router.post(
    "/token-usage/stats",
    response_model=BaseResponse[TokenUsageStatsResponse],
)
async def get_token_usage_stats(req: TokenUsageStatsRequest):
    stats = await token_usage_service.get_token_usage_stats(
        dimension=req.dimension,
        user_id=req.user_id,
        agent_id=req.agent_id,
        session_id=req.session_id,
        request_source=req.request_source,
        start_date=req.start_date,
        end_date=req.end_date,
    )
    return await Response.succ(
        message="system.token_usage_loaded",
        data=TokenUsageStatsResponse(**stats).model_dump(),
    )

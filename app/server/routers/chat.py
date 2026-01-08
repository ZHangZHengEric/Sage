"""
流式聊天接口路由模块
"""
import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from core.client.chat import get_chat_client
from core.exceptions import SageHTTPException
from core.render import Response

# 导入新模型
from schemas.chat import ChatRequest, StreamRequest

# 导入辅助函数
from service.chat import (
    populate_request_from_agent_config,
    run_chat_session,
    run_async_chat_task,
)


# 创建路由器
chat_router = APIRouter()


def validate_and_prepare_request(
    request: ChatRequest | StreamRequest, http_request: Request
) -> None:
    """验证并准备请求参数"""
    if not get_chat_client():
        raise SageHTTPException(
            status_code=503,
            detail="模型客户端未配置或不可用",
            error_detail="Model client is not configured or unavailable",
        )

    # 验证请求参数
    if not request.messages or len(request.messages) == 0:
        raise SageHTTPException(status_code=400, detail="消息列表不能为空")

    # 注入当前用户ID（如果未指定）
    claims = getattr(http_request.state, "user_claims", {}) or {}
    req_user_id = claims.get("userid")
    if not request.user_id:
        request.user_id = req_user_id


@chat_router.post("/api/chat")
async def chat(request: ChatRequest, http_request: Request):
    """流式聊天接口"""
    validate_and_prepare_request(request, http_request)
    
    # 构建 StreamRequest
    inner_request = StreamRequest(
        messages=request.messages,
        session_id=request.session_id,
        user_id=request.user_id,
        system_context=request.system_context,
        agent_id=request.agent_id,
    )
    
    await populate_request_from_agent_config(inner_request, require_agent_id=True)

    return StreamingResponse(
        run_chat_session(inner_request, mode="chat"),
        media_type="text/plain"
    )


@chat_router.post("/api/stream")
async def stream_chat(request: StreamRequest, http_request: Request):
    """流式聊天接口， 与chat不同的是入参不能够指定agent_id"""
    validate_and_prepare_request(request, http_request)
    
    await populate_request_from_agent_config(request, require_agent_id=False)
    
    return StreamingResponse(
        run_chat_session(request, mode="stream"),
        media_type="text/plain"
    )


@chat_router.post("/api/stream/submit_task")
async def submit_stream_task(request: StreamRequest, http_request: Request):
    validate_and_prepare_request(request, http_request)
    
    await populate_request_from_agent_config(request, require_agent_id=False)
    
    session_id = await run_async_chat_task(request)
    
    return await Response.succ(
        data={"session_id": session_id}, message="异步任务已提交"
    )

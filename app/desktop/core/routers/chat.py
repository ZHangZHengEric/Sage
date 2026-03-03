"""
流式聊天接口路由模块
"""

import asyncio
import json
import time

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from loguru import logger

from ..core.client.chat import get_chat_client
from ..core.exceptions import SageHTTPException

# 导入新模型
from ..schemas.chat import ChatRequest, StreamRequest

# 导入辅助函数
from ..services.chat import (
    execute_chat_session,
    populate_request_from_agent_config,
    prepare_session,
)
from ..services.chat.stream_manager import StreamManager
from ..services.conversation import interrupt_session, get_conversation_messages

# 创建路由器
chat_router = APIRouter()


async def stream_with_manager(session_id: str, last_index: int = 0):
    """
    通过 StreamManager 订阅会话流
    """
    manager = StreamManager.get_instance()
    has_stream_data = False
    async for chunk in manager.subscribe(session_id, last_index):
        has_stream_data = True
        yield chunk
    if has_stream_data:
        return
    try:
        await get_conversation_messages(session_id)
    except Exception:
        return
    yield json.dumps(
        {
            "type": "stream_end",
            "session_id": session_id,
            "timestamp": time.time(),
            "resume_fallback": True,
        },
        ensure_ascii=False,
    ) + "\n"


def validate_and_prepare_request(request: ChatRequest | StreamRequest, http_request: Request) -> None:
    """验证并准备请求参数"""
    if not get_chat_client():
        raise SageHTTPException(
            status_code=503,
            detail="模型客户端未配置或不可用",
            error_detail="Model client is not configured or unavailable",
        )

    # 验证请求参数
    if not request.messages or len(request.messages) == 0:
        raise SageHTTPException(status_code=500, detail="消息列表不能为空")



@chat_router.post("/api/web-stream")
async def stream_chat_web(request: StreamRequest, http_request: Request):
    """这个接口有用户鉴权"""
    validate_and_prepare_request(request, http_request)

    session_id = request.session_id
    manager = StreamManager.get_instance()

    if manager.has_running_session(session_id):
        logger.bind(session_id=session_id).info("同会话重入，先中断旧会话")
        try:
            await interrupt_session(session_id, "同会话重入，先中断旧会话")
        finally:
            await manager.stop_session(session_id)

    await populate_request_from_agent_config(request, require_agent_id=False)
    stream_service, lock = await prepare_session(request)
    session_id = request.session_id

    await manager.start_session(session_id, execute_chat_session(mode="web-stream", stream_service=stream_service), lock)

    return StreamingResponse(
        stream_with_manager(session_id, last_index=0),
        media_type="text/plain",
    )


@chat_router.get("/api/stream/resume/{session_id}")
async def resume_stream(session_id: str, last_index: int = 0):
    """
    断线重连或页面切换回来后，继续订阅流
    :param session_id: 会话ID
    :param last_index: 已收到的最后一条消息索引
    """
    return StreamingResponse(stream_with_manager(session_id, last_index), media_type="text/plain")


@chat_router.get("/api/stream/active_sessions")
async def get_active_sessions():
    """获取当前正在生成流的会话列表"""
    manager = StreamManager.get_instance()

    return manager.get_active_sessions()

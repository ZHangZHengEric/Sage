"""
流式聊天接口路由模块
"""

import asyncio
import json
import time
import uuid
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlalchemy.orm import query
from sagents.context.session_context import delete_session_run_lock
from sagents.utils.lock_manager import safe_release

from common.core.exceptions import SageHTTPException
from common.core.request_identity import get_request_user_id
from common.services import chat_service
from common.services import conversation_service
from common.schemas.chat import ChatRequest, StreamRequest, UserInputOptimizeRequest
from pydantic import BaseModel

from ..services.chat.stream_manager import StreamManager

# 创建路由器
chat_router = APIRouter()


def _resolve_request_language(http_request: Request, language: str | None = None, default: str = "zh") -> str:
    candidate = (language or "").strip()
    if not candidate:
        headers = http_request.headers
        candidate = (
            headers.get("x-accept-language")
            or headers.get("accept-language")
            or ""
        ).strip()
    lowered = candidate.lower()
    if lowered.startswith("pt"):
        return "pt"
    if lowered.startswith("en"):
        return "en"
    if lowered.startswith("zh") or lowered.startswith("cn"):
        return "zh"
    return default


class RerunStreamRequest(BaseModel):
    agent_id: str | None = None
    agent_mode: str | None = None
    more_suggest: bool | None = None
    max_loop_count: int | None = None
    available_sub_agent_ids: list[str] | None = None
    guidance_content: str | None = None
    guidance_id: str | None = None


def _build_current_time_with_weekday() -> str:
    now = datetime.now().astimezone()
    return now.strftime("%a, %d %b %Y %H:%M:%S %z")


async def _start_web_stream_session(
    request: StreamRequest,
    *,
    manager: StreamManager,
    interrupt_message: str,
    query: str,
):
    session_id = request.session_id

    if manager.has_running_session(session_id):
        logger.bind(session_id=session_id).info(interrupt_message)
        try:
            await conversation_service.interrupt_session(
                session_id,
                interrupt_message,
            )
        finally:
            await manager.stop_session(session_id)

    await chat_service.populate_request_from_agent_config(
        request,
        require_agent_id=False,
    )
    stream_service, lock = await chat_service.prepare_session(request)
    session_id = request.session_id
    await manager.start_session(
        session_id,
        query,
        chat_service.execute_chat_session(stream_service=stream_service),
        lock,
    )

    return StreamingResponse(
        stream_with_manager(session_id, last_index=0, resume=False),
        media_type="text/plain",
    )


@chat_router.post("/api/chat/optimize-input")
async def optimize_chat_input(request: UserInputOptimizeRequest, http_request: Request):
    claims = getattr(http_request.state, "user_claims", {}) or {}
    if not request.user_id:
        request.user_id = claims.get("userid") or ""
    language = _resolve_request_language(http_request, request.language, default="zh")

    result = await chat_service.optimize_user_input(
        current_input=request.current_input,
        history_messages=[message.model_dump() for message in request.history_messages],
        session_id=request.session_id or "",
        agent_id=request.agent_id or "",
        user_id=request.user_id or "",
        language=language,
    )

    return {
        "code": 200,
        "message": "用户输入优化成功",
        "data": result,
    }


@chat_router.post("/api/chat/optimize-input/stream")
async def optimize_chat_input_stream(request: UserInputOptimizeRequest, http_request: Request):
    claims = getattr(http_request.state, "user_claims", {}) or {}
    if not request.user_id:
        request.user_id = claims.get("userid") or ""
    language = _resolve_request_language(http_request, request.language, default="zh")

    async def event_generator():
        async for chunk in chat_service.optimize_user_input_stream(
            current_input=request.current_input,
            history_messages=[message.model_dump() for message in request.history_messages],
            session_id=request.session_id or "",
            agent_id=request.agent_id or "",
            user_id=request.user_id or "",
            language=language,
        ):
            yield json.dumps(chunk, ensure_ascii=False) + "\n"

    return StreamingResponse(event_generator(), media_type="text/plain")


async def stream_with_manager(session_id: str, last_index: int = 0, resume: bool = False):
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
        await conversation_service.get_conversation_messages(session_id)
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


async def stream_api_with_disconnect_check(generator, request: Request, lock: asyncio.Lock, session_id: str):
    """
    Wrap the generator to monitor client disconnection.
    If client disconnects, stop the generator (which triggers its finally block).
    """
    try:
        async for chunk in generator:
            if await request.is_disconnected():
                logger.bind(session_id=session_id).info("Client disconnection detected")
                # 抛出 GeneratorExit 模拟客户端断开，统一由异常处理逻辑处理
                raise GeneratorExit
            yield chunk
    except (asyncio.CancelledError, GeneratorExit) as e:
        # 标记会话中断，让内部逻辑有机会感知并处理
        try:
            await conversation_service.interrupt_session(session_id, "客户端断开连接")
        except Exception as ex:
            logger.bind(session_id=session_id).error(f"Error interrupting session: {ex}")

        # 重新抛出异常，确保生成器正确关闭
        raise e
    except Exception as e:
        logger.bind(session_id=session_id).error(f"Stream generator error: {e}")
        raise e
    finally:
        # 确保 generator 关闭，触发内部清理逻辑 (sagents cleanup)
        # 这必须在释放锁之前执行，因为 sagents 清理逻辑需要获取锁
        try:
            if hasattr(generator, "aclose"):
                await generator.aclose()
        except Exception as e:
            logger.bind(session_id=session_id).warning(f"Error closing generator: {e}")

        # 清理资源
        logger.bind(session_id=session_id).debug("流处理结束，清理会话资源")
        try:
            await safe_release(lock, session_id, "流结束清理")

            delete_session_run_lock(session_id)
            logger.bind(session_id=session_id).info("资源已清理")
        except Exception as e:
            logger.bind(session_id=session_id).error(f"清理资源时发生错误: {e}")


def validate_and_prepare_request(request: ChatRequest | StreamRequest, http_request: Request) -> None:


    # 验证请求参数
    if not request.messages or len(request.messages) == 0:
        raise SageHTTPException(detail="消息列表不能为空")

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
    chat_service.mark_request_execution(inner_request, request_source="api/chat")

    await chat_service.populate_request_from_agent_config(
        inner_request,
        require_agent_id=True,
    )

    stream_service, lock = await chat_service.prepare_session(inner_request)
    session_id = inner_request.session_id
    return StreamingResponse(
        stream_api_with_disconnect_check(
            chat_service.execute_chat_session(
                stream_service=stream_service,
            ),
            http_request,
            lock,
            session_id,
        ),
        media_type="text/plain",
    )


@chat_router.post("/api/stream")
async def stream_chat(request: StreamRequest, http_request: Request):
    """流式聊天接口， 与chat不同的是入参不能够指定agent_id"""
    validate_and_prepare_request(request, http_request)
    chat_service.mark_request_execution(request, request_source="api/stream")
    await chat_service.populate_request_from_agent_config(
        request,
        require_agent_id=False,
    )
    stream_service, lock = await chat_service.prepare_session(request)
    session_id = request.session_id

    return StreamingResponse(
        stream_api_with_disconnect_check(
            chat_service.execute_chat_session(
                stream_service=stream_service,
            ),
            http_request,
            lock,
            session_id,
        ),
        media_type="text/plain",
    )


@chat_router.post("/api/web-stream")
async def stream_chat_web(request: StreamRequest, http_request: Request):
    """这个接口有用户鉴权"""
    validate_and_prepare_request(request, http_request)
    chat_service.mark_request_execution(request, request_source="api/web-stream")

    session_id = request.session_id
    manager = StreamManager.get_instance()
    query = request.messages[0].content
    return await _start_web_stream_session(
        request,
        manager=manager,
        interrupt_message="同会话重入，先中断旧会话",
        query=query,
    )


@chat_router.get("/api/stream/resume/{session_id}")
async def resume_stream(session_id: str, last_index: int = 0):
    """
    断线重连或页面切换回来后，继续订阅流
    :param session_id: 会话ID
    :param last_index: 已收到的最后一条消息索引
    """

    return StreamingResponse(stream_with_manager(session_id, last_index, resume=True), media_type="text/plain")


@chat_router.get("/api/stream/active_sessions")
async def get_active_sessions(request: Request):
    """
    SSE 接口：获取当前正在生成流的会话列表的实时更新
    """
    manager = StreamManager.get_instance()
    client_host = request.client.host if request.client else "unknown"

    async def event_generator():
        try:
            async for sessions in manager.subscribe_active_sessions():
                if await request.is_disconnected():
                    logger.info(f"Client {client_host} disconnected active_sessions stream")
                    break

                # 手动构建 SSE 格式
                json_str = json.dumps(sessions, default=str, ensure_ascii=False)
                yield f"data: {json_str}\n\n"
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error in SSE generator for {client_host}: {e}")
            raise

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@chat_router.post("/api/conversations/{session_id}/rerun-stream")
async def rerun_conversation_stream(
    session_id: str,
    rerun_request: RerunStreamRequest,
    http_request: Request,
):
    user_id = get_request_user_id(http_request)
    payload = await conversation_service.get_rerun_conversation_payload(
        session_id=session_id,
        user_id=user_id,
    )

    guidance_content = (rerun_request.guidance_content or "").strip()
    rerun_messages = []
    if guidance_content:
        rerun_messages.append({
            "message_id": rerun_request.guidance_id or str(uuid.uuid4()),
            "role": "user",
            "content": guidance_content,
        })

    request = StreamRequest(
        messages=rerun_messages,
        session_id=session_id,
        user_id=payload["user_id"] or user_id,
        system_context={
            "current_time": _build_current_time_with_weekday(),
            "rerun_from_edit_last_user_message": True,
            "rerun_from_guidance": bool(guidance_content),
        },
        agent_id=rerun_request.agent_id or payload["agent_id"],
        agent_mode=rerun_request.agent_mode,
        more_suggest=rerun_request.more_suggest,
        max_loop_count=rerun_request.max_loop_count,
        available_sub_agent_ids=rerun_request.available_sub_agent_ids,
    )
    chat_service.mark_request_execution(
        request,
        request_source="api/conversations/rerun-stream",
    )

    manager = StreamManager.get_instance()
    return await _start_web_stream_session(
        request,
        manager=manager,
        interrupt_message="重新执行最后一条用户消息，先中断旧会话",
        query=guidance_content or payload["query"] or "",
    )

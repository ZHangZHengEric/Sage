"""
流式聊天接口路由模块
"""

import asyncio
import json
import time
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlalchemy.orm import query

from ..core.client.chat import get_chat_client
from ..core.exceptions import SageHTTPException

# 导入新模型
from ..schemas.chat import ChatRequest, StreamRequest
from sagents.context.session_context import delete_session_run_lock
from sagents.utils.lock_manager import safe_release

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
            await interrupt_session(session_id, "客户端断开连接")
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


async def broadcast_generator(generator, session_id: str, query: str = ""):
    """
    Wraps a generator to broadcast chunks to StreamManager
    """
    manager = StreamManager.get_instance()
    await manager.create_publisher(session_id, query)
    try:
        async for chunk in generator:
            await manager.publish(session_id, chunk)
            yield chunk
    finally:
        await manager.finish_publisher(session_id)


@chat_router.post("/api/chat")
async def chat(request: ChatRequest, http_request: Request):
    """流式聊天接口"""
    validate_and_prepare_request(request, http_request)
    # 构建 StreamRequest
    inner_request = StreamRequest(
        messages=request.messages,
        session_id=request.session_id,
        system_context=request.system_context,
        agent_id=request.agent_id,
    )

    await populate_request_from_agent_config(inner_request, require_agent_id=True)

    stream_service, lock = await prepare_session(inner_request)
    session_id = inner_request.session_id

    # 获取查询内容用于记录（尝试获取最后一条消息的内容）
    query = ""
    if inner_request.messages:
        query = inner_request.messages[-1].content if hasattr(inner_request.messages[-1], "content") else str(inner_request.messages[-1])

    return StreamingResponse(
        stream_api_with_disconnect_check(
            broadcast_generator(
                execute_chat_session(
                    mode="chat",
                    stream_service=stream_service,
                ),
                session_id,
                query,
            ),
            http_request,
            lock,
            session_id,
        ),
        media_type="text/plain",
    )


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
    query = request.messages[0].content
    await manager.start_session(session_id, query, execute_chat_session(mode="web-stream", stream_service=stream_service), lock)

    return StreamingResponse(
        stream_with_manager(session_id, last_index=0, resume=False),
        media_type="text/plain",
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
    logger.info(f"SSE Connection request from {client_host}")

    async def event_generator():
        try:
            async for sessions in manager.subscribe_active_sessions():
                if await request.is_disconnected():
                    logger.info(f"Client {client_host} disconnected active_sessions stream")
                    break
                
                # 手动构建 SSE 格式
                json_str = json.dumps(sessions, default=str, ensure_ascii=False)
                # logger.debug(f"Yielding SSE data to {client_host}: {json_str[:100]}...")
                yield f"data: {json_str}\n\n"
        except asyncio.CancelledError:
            logger.info(f"SSE task cancelled for {client_host}")
            pass
        except Exception as e:
            logger.error(f"Error in SSE generator for {client_host}: {e}")
            raise

    return StreamingResponse(event_generator(), media_type="text/event-stream")



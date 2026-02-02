"""
流式聊天接口路由模块
"""
import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from loguru import logger
from sagents.context.session_context import delete_session_run_lock

from ..core.client.chat import get_chat_client
from ..core.exceptions import SageHTTPException
from ..core.render import Response

# 导入新模型
from ..schemas.chat import ChatRequest, StreamRequest

# 导入辅助函数
from ..services.chat import (
    execute_chat_session,
    populate_request_from_agent_config,
    prepare_session,
    run_async_chat_task,
)
from ..services.conversation import interrupt_session

# 创建路由器
chat_router = APIRouter()


async def stream_with_disconnect_check(
    generator, 
    request: Request,
    lock: asyncio.Lock,
    session_id: str
):
    """
    Wrap the generator to monitor client disconnection.
    If client disconnects, stop the generator (which triggers its finally block).
    """
    try:
        async for chunk in generator:
            if await request.is_disconnected():
                logger.info(f"Session {session_id}: Client disconnection detected")
                # 抛出 GeneratorExit 模拟客户端断开，统一由异常处理逻辑处理
                raise GeneratorExit
            yield chunk
    except (asyncio.CancelledError, GeneratorExit) as e:        
        # 标记会话中断，让内部逻辑有机会感知并处理
        try:
            await interrupt_session(session_id, "客户端断开连接")
        except Exception as ex:
            logger.error(f"Error interrupting session {session_id}: {ex}")
            
        # 重新抛出异常，确保生成器正确关闭
        raise e
    except Exception as e:
        logger.error(f"Stream generator error: {e}")
        raise e
    finally:
        # 确保 generator 关闭，触发内部清理逻辑 (sagents cleanup)
        # 这必须在释放锁之前执行，因为 sagents 清理逻辑需要获取锁
        try:
            if hasattr(generator, 'aclose'):
                await generator.aclose()
        except Exception as e:
            logger.warning(f"Error closing generator for session {session_id}: {e}")

        # 清理资源
        logger.info(f"sessionId={session_id} 流处理结束，清理会话资源")
        try:
            if lock.locked():
                await lock.release()
            delete_session_run_lock(session_id)
            logger.info(f"sessionId={session_id} 资源已清理")
        except Exception as e:
            logger.error(f"Error releasing resources for session {session_id}: {e}")


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
        raise SageHTTPException(status_code=500, detail="消息列表不能为空")

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

    session_id, stream_service, lock = await prepare_session(inner_request)

    return StreamingResponse(
        stream_with_disconnect_check(
            execute_chat_session(inner_request, "chat", session_id, stream_service),
            http_request,
            lock,
            session_id
        ),
        media_type="text/plain"
    )


@chat_router.post("/api/stream")
async def stream_chat(request: StreamRequest, http_request: Request):
    """流式聊天接口， 与chat不同的是入参不能够指定agent_id"""
    validate_and_prepare_request(request, http_request)

    await populate_request_from_agent_config(request, require_agent_id=False)

    session_id, stream_service, lock = await prepare_session(request)

    return StreamingResponse(
        stream_with_disconnect_check(
            execute_chat_session(request, "stream", session_id, stream_service),
            http_request,
            lock,
            session_id
        ),
        media_type="text/plain"
    )


@chat_router.post("/api/web-stream")
async def stream_chat_web(request: StreamRequest, http_request: Request):
    """流式聊天接口， 与chat不同的是入参不能够指定agent_id"""
    validate_and_prepare_request(request, http_request)

    await populate_request_from_agent_config(request, require_agent_id=False)

    session_id, stream_service, lock = await prepare_session(request)

    return StreamingResponse(
        stream_with_disconnect_check(
            execute_chat_session(request, "stream", session_id, stream_service),
            http_request,
            lock,
            session_id,
        ),
        media_type="text/plain",
    )


@chat_router.post("/api/stream/submit_task")
async def submit_stream_task(request: StreamRequest, http_request: Request):
    validate_and_prepare_request(request, http_request)
    
    await populate_request_from_agent_config(request, require_agent_id=False)
    
    session_id = await run_async_chat_task(request)
    
    return await Response.succ(
        data={"session_id": session_id}, message="异步任务已提交"
    )

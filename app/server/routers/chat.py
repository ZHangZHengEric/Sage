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
from sagents.context.session_context import delete_session_run_lock
from sagents.utils.lock_manager import safe_release

from common.core.exceptions import SageHTTPException
from common.core.request_identity import get_request_user_id
from common.services import chat_service
from common.services import conversation_service
from common.schemas.chat import ChatRequest, StreamRequest, UserInputOptimizeRequest
from app.server.services.prometheus_metrics import record_sse_stream_failure
from app.server.utils.image_size_guard import ensure_image_url_within_size_limit
from pydantic import BaseModel

from ..services.chat.stream_manager import StreamManager

# 创建路由器
chat_router = APIRouter()

SERVER_STREAM_FILTERED_TYPES = {
    "tool_progress",
}


def _resolve_request_language(
    http_request: Request, language: str | None = None, default: str = "zh"
) -> str:
    candidate = (language or "").strip()
    if not candidate:
        headers = http_request.headers
        candidate = (
            headers.get("x-accept-language") or headers.get("accept-language") or ""
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


def _extract_multimodal_image_url(item: object) -> str:
    if not isinstance(item, dict) or item.get("type") != "image_url":
        return ""

    image_url = item.get("image_url")
    if isinstance(image_url, dict):
        return str(image_url.get("url") or "").strip()
    if isinstance(image_url, str):
        return image_url.strip()
    return str(item.get("url") or "").strip()


def _set_multimodal_image_url(item: dict, url: str) -> None:
    image_url = item.get("image_url")
    if isinstance(image_url, dict):
        image_url["url"] = url
    elif isinstance(image_url, str):
        item["image_url"] = url
    elif "url" in item:
        item["url"] = url
    else:
        item["image_url"] = {"url": url}


def _replace_multimodal_image_text_refs(
    content: list,
    old_url: str,
    new_url: str,
) -> None:
    for item in content:
        if not isinstance(item, dict) or item.get("type") != "text":
            continue
        text = item.get("text")
        if isinstance(text, str) and old_url in text:
            item["text"] = text.replace(old_url, new_url)


async def _guard_request_multimodal_images(
    request: ChatRequest | StreamRequest,
) -> None:
    guarded_count = 0
    for message in request.messages or []:
        content = message.content
        if not isinstance(content, list):
            continue
        for item in content:
            image_url = _extract_multimodal_image_url(item)
            if not image_url:
                continue
            try:
                guarded_url = await ensure_image_url_within_size_limit(image_url)
            except Exception as exc:
                logger.bind(session_id=request.session_id).warning(
                    f"多模态图片压缩失败，保留原图: {exc}"
                )
                continue
            if guarded_url != image_url and isinstance(item, dict):
                _set_multimodal_image_url(item, guarded_url)
                _replace_multimodal_image_text_refs(content, image_url, guarded_url)
                guarded_count += 1

    if guarded_count:
        logger.bind(session_id=request.session_id).info(
            f"多模态图片已压缩并替换 URL: count={guarded_count}"
        )


async def _start_web_stream_session(
    request: StreamRequest,
    *,
    manager: StreamManager,
    interrupt_message: str,
    query: str,
    filter_stream_types: bool = False,
    stream_name: str = "web_stream",
):
    session_id = request.session_id

    if manager.has_running_session(session_id):
        logger.bind(session_id=session_id).info(interrupt_message)
        try:
            await conversation_service.interrupt_session(
                session_id,  # pyright: ignore[reportArgumentType]
                interrupt_message,
            )
        finally:
            await manager.stop_session(session_id)

    await _guard_request_multimodal_images(request)

    await chat_service.populate_request_from_agent_config(
        request,
        require_agent_id=False,
    )
    stream_service, lock = await chat_service.prepare_session(request)
    session_id = request.session_id
    generator = chat_service.execute_chat_session(stream_service=stream_service)
    if filter_stream_types:
        generator = _filter_stream_chunks(generator)

    await manager.start_session(session_id, query, generator, lock)  # pyright: ignore[reportArgumentType]

    return StreamingResponse(
        stream_with_manager(
            session_id,  # pyright: ignore[reportArgumentType]
            last_index=0,
            resume=False,
            stream_name=stream_name,
        ),
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
async def optimize_chat_input_stream(
    request: UserInputOptimizeRequest, http_request: Request
):
    claims = getattr(http_request.state, "user_claims", {}) or {}
    if not request.user_id:
        request.user_id = claims.get("userid") or ""
    language = _resolve_request_language(http_request, request.language, default="zh")

    async def event_generator():
        async for chunk in chat_service.optimize_user_input_stream(
            current_input=request.current_input,
            history_messages=[
                message.model_dump() for message in request.history_messages
            ],
            session_id=request.session_id or "",
            agent_id=request.agent_id or "",
            user_id=request.user_id or "",
            language=language,
        ):
            yield json.dumps(chunk, ensure_ascii=False) + "\n"

    return StreamingResponse(event_generator(), media_type="text/plain")


async def stream_with_manager(
    session_id: str,
    last_index: int = 0,
    resume: bool = False,
    stream_name: str = "manager_stream",
):
    """
    通过 StreamManager 订阅会话流
    """
    status = "completed"
    manager = StreamManager.get_instance()
    has_stream_data = False
    try:
        async for chunk in manager.subscribe(session_id, last_index):
            has_stream_data = True
            yield chunk
        if has_stream_data:
            return
        try:
            await conversation_service.get_conversation_messages(session_id)
        except Exception:
            status = "fallback_missing"
            return
        yield (
            json.dumps(
                {
                    "type": "stream_end",
                    "session_id": session_id,
                    "timestamp": time.time(),
                    "resume_fallback": True,
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    except asyncio.CancelledError:
        status = "cancelled"
        raise
    except Exception:
        status = "error"
        raise
    finally:
        record_sse_stream_failure(stream_name, session_id, status)


def _should_filter_stream_chunk(chunk: str) -> bool:
    try:
        payload = json.loads(chunk)
    except Exception:
        return False
    return (
        isinstance(payload, dict)
        and payload.get("type") in SERVER_STREAM_FILTERED_TYPES
    )


async def _filter_stream_chunks(generator):
    try:
        async for chunk in generator:
            if _should_filter_stream_chunk(chunk):
                continue
            yield chunk
    finally:
        if hasattr(generator, "aclose"):
            await generator.aclose()


# 流式清理动作的超时上限。
# 历史实现把 interrupt_session / generator.aclose() 都无超时 await 在断开链路里，
# 一旦下层 await 卡在 anyio 取消派发或锁等待，整个事件循环会被拖住。
_DISCONNECT_INTERRUPT_TIMEOUT = 5.0
_GENERATOR_ACLOSE_TIMEOUT = 5.0


async def stream_api_with_disconnect_check(
    generator,
    request: Request,
    lock: asyncio.Lock,
    session_id: str,
    stream_name: str = "chat_stream",
):
    """
    Wrap the generator to monitor client disconnection.
    If client disconnects, stop the generator (which triggers its finally block).

    断开检测策略：发现 ``request.is_disconnected()`` 后只 ``break``，不再人为抛 ``GeneratorExit``。
    ``GeneratorExit`` 是 async generator 的关闭信号，规范上不应该在 ``except GeneratorExit`` 里
    再 ``await`` 长协程（旧写法会在 generator 关闭临界态做远程持久化，叠加 anyio CancelScope
    导致 sage-server 主线程 100% CPU 空转）。改为 ``break`` 后统一在 ``finally`` 里收尾。
    """
    client_disconnected = False
    status = "completed"
    try:
        async for chunk in generator:
            if await request.is_disconnected():
                logger.bind(session_id=session_id).info("Client disconnection detected")
                client_disconnected = True
                status = "disconnected"
                break
            yield chunk
    except asyncio.CancelledError:
        client_disconnected = True
        status = "cancelled"
        raise
    except Exception as e:
        status = "error"
        logger.bind(session_id=session_id).error(f"Stream generator error: {e}")
        raise
    finally:
        if client_disconnected:
            try:
                await asyncio.wait_for(
                    conversation_service.interrupt_session(
                        session_id, "客户端断开连接"
                    ),
                    timeout=_DISCONNECT_INTERRUPT_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.bind(session_id=session_id).warning(
                    f"interrupt_session 超过 {_DISCONNECT_INTERRUPT_TIMEOUT}s 未返回，跳过强制等待"
                )
            except Exception as ex:
                logger.bind(session_id=session_id).error(
                    f"Error interrupting session: {ex}"
                )

        # 确保 generator 关闭，触发内部清理逻辑 (sagents cleanup)
        # 这必须在释放锁之前执行，因为 sagents 清理逻辑需要获取锁
        try:
            if hasattr(generator, "aclose"):
                await asyncio.wait_for(
                    generator.aclose(), timeout=_GENERATOR_ACLOSE_TIMEOUT
                )
        except asyncio.TimeoutError:
            logger.bind(session_id=session_id).warning(
                f"generator.aclose 超过 {_GENERATOR_ACLOSE_TIMEOUT}s 未返回，跳过强制等待"
            )
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
        record_sse_stream_failure(stream_name, session_id, status)


def validate_and_prepare_request(
    request: ChatRequest | StreamRequest,
    http_request: Request,
    *,
    allow_pending_guidance_flush: bool = False,
) -> None:

    # 验证请求参数
    if not request.messages or len(request.messages) == 0:
        if not allow_pending_guidance_flush or not _has_pending_user_injections(
            request.session_id
        ):
            raise SageHTTPException(detail="消息列表不能为空")
        logger.bind(session_id=request.session_id).info(
            "允许空 messages 请求消费 pending guidance"
        )

    # 注入当前用户ID（如果未指定）
    claims = getattr(http_request.state, "user_claims", {}) or {}
    req_user_id = claims.get("userid")
    if not request.user_id:
        request.user_id = req_user_id

    provider_id = (request.provider_id or "").strip()
    if provider_id:
        request.provider_id = provider_id


def _has_pending_user_injections(session_id: str | None) -> bool:
    normalized_session_id = (session_id or "").strip()
    if not normalized_session_id:
        return False
    try:
        data = conversation_service.list_pending_user_injections(normalized_session_id)
    except Exception as exc:
        logger.bind(session_id=normalized_session_id).debug(
            f"空 messages pending guidance 检查失败: {exc}"
        )
        return False
    items = data.get("items") if isinstance(data, dict) else None
    return isinstance(items, list) and len(items) > 0


@chat_router.post("/api/chat")
async def chat(request: ChatRequest, http_request: Request):
    logger.bind(session_id=request.session_id).info("Received chat request")
    """流式聊天接口"""
    validate_and_prepare_request(
        request,
        http_request,
        allow_pending_guidance_flush=True,
    )
    await _guard_request_multimodal_images(request)

    # 构建 StreamRequest
    inner_request = StreamRequest(
        messages=request.messages,
        session_id=request.session_id,
        user_id=request.user_id,
        system_context=request.system_context,
        agent_id=request.agent_id,
        provider_id=request.provider_id,
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
            _filter_stream_chunks(
                chat_service.execute_chat_session(
                    stream_service=stream_service,
                ),
            ),
            http_request,
            lock,
            session_id,  # pyright: ignore[reportArgumentType]
            stream_name="api_chat",
        ),
        media_type="text/plain",
    )


@chat_router.post("/api/stream")
async def stream_chat(request: StreamRequest, http_request: Request):
    """流式聊天接口， 与chat不同的是入参不能够指定agent_id"""
    validate_and_prepare_request(request, http_request)
    await _guard_request_multimodal_images(request)
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
            session_id,  # pyright: ignore[reportArgumentType]
            stream_name="api_stream",
        ),
        media_type="text/plain",
    )


@chat_router.post("/api/web-stream")
async def stream_chat_web(request: StreamRequest, http_request: Request):
    """这个接口有用户鉴权"""
    validate_and_prepare_request(request, http_request)
    chat_service.mark_request_execution(request, request_source="api/web-stream")

    manager = StreamManager.get_instance()
    query = request.messages[0].content
    return await _start_web_stream_session(
        request,
        manager=manager,
        interrupt_message="同会话重入，先中断旧会话",
        query=query,  # pyright: ignore[reportArgumentType]
        filter_stream_types=True,
        stream_name="web_stream",
    )


@chat_router.get("/api/stream/resume/{session_id}")
async def resume_stream(session_id: str, last_index: int = 0):
    """
    断线重连或页面切换回来后，继续订阅流
    :param session_id: 会话ID
    :param last_index: 已收到的最后一条消息索引
    """

    return StreamingResponse(
        stream_with_manager(
            session_id,
            last_index,
            resume=True,
            stream_name="resume_stream",
        ),
        media_type="text/plain",
    )


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
                    logger.info(
                        f"Client {client_host} disconnected active_sessions stream"
                    )
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
        rerun_messages.append(
            {
                "message_id": rerun_request.guidance_id or str(uuid.uuid4()),
                "role": "user",
                "content": guidance_content,
            }
        )

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
        stream_name="rerun_stream",
    )

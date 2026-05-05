"""
流式聊天接口路由模块
"""

import asyncio
import json
import time
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlalchemy.orm import query

from common.core.exceptions import SageHTTPException
from common.models.agent import AgentConfigDao
from common.services import chat_service
from common.services import conversation_service
from common.schemas.chat import ChatRequest, StreamRequest, UserInputOptimizeRequest
from common.core.client.chat import get_chat_client
from pydantic import BaseModel

from sagents.context.session_context import delete_session_run_lock
from sagents.utils.lock_manager import safe_release

from ..services.browser_capability import get_browser_tool_sync_state
from ..services.chat.stream_manager import StreamManager
from ..services.browser_tools import BrowserBridgeTool
from ..user_context import get_desktop_user_id

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


def _build_current_time_with_weekday() -> str:
    now = datetime.now().astimezone()
    return now.strftime("%a, %d %b %Y %H:%M:%S %z")


async def _apply_desktop_auto_sub_agents(request: StreamRequest) -> None:
    if not request.agent_id or request.agent_mode != "fibre":
        return

    agent = await AgentConfigDao().get_by_id(request.agent_id)
    if not agent or not agent.config:
        return

    config = agent.config or {}
    selection_mode = config.get("subAgentSelectionMode") or config.get("sub_agent_selection_mode")
    configured_ids = config.get("availableSubAgentIds")
    if selection_mode is None:
        selection_mode = "manual" if configured_ids else "auto_all"

    if selection_mode != "auto_all":
        return

    if request.available_sub_agent_ids:
        return

    all_agents = await AgentConfigDao().get_all()
    request.available_sub_agent_ids = [
        sub_agent.agent_id
        for sub_agent in all_agents
        if sub_agent.agent_id and sub_agent.agent_id != request.agent_id
    ]


FIBRE_ONLY_TOOLS = ("sys_spawn_agent", "sys_delegate_task", "sys_finish_task")


def _sync_fibre_only_tools(request: StreamRequest) -> None:
    """Fibre 专属工具（智能体委派/创建/完成）只允许在 fibre 模式下出现在 available_tools。
    其他模式下即便 agent 配置里残留也强制移除，避免 agent 误调用。
    """
    if request.agent_mode == "fibre":
        return
    current_tools = list(request.available_tools or [])
    cleaned = [t for t in current_tools if t not in FIBRE_ONLY_TOOLS]
    if len(cleaned) != len(current_tools):
        logger.bind(session_id=request.session_id).info(
            f"[FibreTools] 当前 agent_mode={request.agent_mode!r} 非 fibre，已移除 fibre 专属工具"
        )
    request.available_tools = cleaned


async def _sync_browser_tools_for_request(request: StreamRequest) -> None:
    """
    根据浏览器扩展的实时状态，对 request.available_tools 中的浏览器工具做同步：
    - 扩展离线/未安装：清掉所有浏览器工具（即便 agent 配置里勾了也无效，因为根本调不通）。
    - 扩展在线：先剔除 agent 配置里那些扩展并未上报 capability 的浏览器工具，再把扩展支持
      但 agent 配置里漏掉的工具补回来（保持 UI 一侧 syncBrowserToolSelection 的行为一致）。
    """
    current_tools = list(request.available_tools or [])
    all_browser_tools = set(BrowserBridgeTool.TOOL_NAMES)

    browser_sync_state = await get_browser_tool_sync_state(request.user_id or "")
    online = bool(browser_sync_state.get("browser_tools_online"))
    supported_browser_tools = set(browser_sync_state.get("browser_tools") or [])

    if not online:
        # 没装/没在线：浏览器工具全部踢掉，避免注入空壳工具骗 agent 调用
        cleaned = [t for t in current_tools if t not in all_browser_tools]
        if len(cleaned) != len(current_tools):
            logger.bind(session_id=request.session_id).info(
                "[BrowserTools] 扩展离线，已从 available_tools 移除所有浏览器工具"
            )
        request.available_tools = cleaned
        return

    # 在线：保留扩展实际支持的；不支持的踢掉
    cleaned: list[str] = []
    dropped: list[str] = []
    for tool_name in current_tools:
        if tool_name in all_browser_tools and tool_name not in supported_browser_tools:
            dropped.append(tool_name)
            continue
        cleaned.append(tool_name)
    if dropped:
        logger.bind(session_id=request.session_id).info(
            f"[BrowserTools] 扩展未上报 capability，移除不支持的浏览器工具: {dropped}"
        )

    # 扩展支持但 agent 配置里没列的工具补齐（与前端 syncBrowserToolSelection 行为一致）
    for tool_name in BrowserBridgeTool.TOOL_NAMES:
        if tool_name in supported_browser_tools and tool_name not in cleaned:
            cleaned.append(tool_name)

    request.available_tools = cleaned


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
    await _apply_desktop_auto_sub_agents(request)
    _sync_fibre_only_tools(request)
    await _sync_browser_tools_for_request(request)
    stream_service, lock = await chat_service.prepare_session(request)
    session_id = request.session_id
    await manager.start_session(
        session_id,
        query,
        chat_service.execute_chat_session(
            mode="web-stream",
            stream_service=stream_service,
        ),
        lock,
    )

    return StreamingResponse(
        stream_with_manager(session_id, last_index=0, resume=False),
        media_type="text/plain",
    )


@chat_router.post("/api/chat/optimize-input")
async def optimize_chat_input(request: UserInputOptimizeRequest, http_request: Request):
    if not request.user_id:
        request.user_id = get_desktop_user_id(http_request)
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
    if not request.user_id:
        request.user_id = get_desktop_user_id(http_request)
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
        conversation_data = await conversation_service.get_conversation_messages(session_id)
    except Exception:
        return
    yield json.dumps(
        {
            "type": "stream_end",
            "session_id": session_id,
            "timestamp": time.time(),
            "resume_fallback": True,
            "goal": (conversation_data.get("conversation_info") or {}).get("goal"),
            "goal_transition": (conversation_data.get("conversation_info") or {}).get("goal_transition"),
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
        user_id=request.user_id or get_desktop_user_id(http_request),
    )
    chat_service.mark_request_execution(inner_request, request_source="api/chat")

    await chat_service.populate_request_from_agent_config(
        inner_request,
        require_agent_id=True,
    )
    await _apply_desktop_auto_sub_agents(inner_request)
    _sync_fibre_only_tools(inner_request)
    await _sync_browser_tools_for_request(inner_request)

    stream_service, lock = await chat_service.prepare_session(inner_request)
    session_id = inner_request.session_id

    # 获取查询内容用于记录（尝试获取最后一条消息的内容）
    query = ""
    if inner_request.messages:
        query = inner_request.messages[-1].content if hasattr(inner_request.messages[-1], "content") else str(inner_request.messages[-1])

    return StreamingResponse(
        stream_api_with_disconnect_check(
            broadcast_generator(
                chat_service.execute_chat_session(
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
    if not request.user_id:
        request.user_id = get_desktop_user_id(http_request)
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
                # logger.debug(f"Yielding SSE data to {client_host}: {json_str[:100]}...")
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
    user_id = get_desktop_user_id(http_request)
    payload = await conversation_service.get_rerun_conversation_payload(
        session_id=session_id,
        user_id=user_id,
    )

    request = StreamRequest(
        messages=[],
        session_id=session_id,
        user_id=payload["user_id"] or user_id,
        system_context={
            "current_time": _build_current_time_with_weekday(),
            "rerun_from_edit_last_user_message": True,
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
        query=payload["query"] or "",
    )

import asyncio
import time
import uuid
import traceback
import os
import json
from loguru import logger
from ...schemas.chat import StreamRequest

from sagents.sagents import SAgent
from ...core.config import get_startup_config
from ...core.exceptions import SageHTTPException
from ...utils.async_utils import create_safe_task

from .utils import (
    create_tool_proxy,
    send_chunked_json,
    initialize_chat_resources
)
from .processor import (
    ContentProcessor,
    _prepare_messages,
    _initialize_message_collector,
    update_message_collector
)
from .manager import (
    _ensure_conversation,
    _save_single_message
)
from sagents.context.session_context import (
    get_session_run_lock,
    get_session_context,
    delete_session_run_lock,
    SessionStatus
)

class SageStreamService:
    """Sage 流式服务类"""

    def __init__(self, request: StreamRequest):
        self.request = request
        # 1. 配置准备
        server_args = get_startup_config()

        # 优化：使用 unified initialization function
        model_client, final_model_config = initialize_chat_resources(
            request.llm_model_config, server_args
        )

        # 2. 工具代理
        tool_proxy = create_tool_proxy(request.available_tools, request.multi_agent)
        self.tool_manager = tool_proxy

        # 3. 路径处理
        workspace = server_args.workspace
        if workspace:
            workspace = os.path.abspath(workspace)
            if not workspace.endswith('/'):
                workspace += '/'

        # 4. 初始化 Sage 引擎
        self.sage_engine = SAgent(
            model=model_client,
            model_config=final_model_config,
            system_prefix=request.system_prefix,
            workspace=workspace,
            memory_root=server_args.memory_root,
        )

    async def process_stream(
        self,
        messages,
        session_id=None,
        user_id=None,
        deep_thinking=None,
        max_loop_count=None,
        multi_agent=None,
        more_suggest=False,
        system_context=None,
        available_workflows=None,
        force_summary=False,
        context_budget_config=None,
    ):
        if max_loop_count is None:
            max_loop_count = 10
        """处理流式聊天请求"""
        logger.info(f"🚀 SageStreamService.process_stream 开始，会话ID: {session_id}")
        try:
            stream_result = self.sage_engine.run_stream(
                input_messages=messages,
                tool_manager=self.tool_manager,
                session_id=session_id,
                user_id=user_id,
                deep_thinking=deep_thinking,
                max_loop_count=max_loop_count,
                multi_agent=multi_agent,
                more_suggest=more_suggest,
                system_context=system_context,
                available_workflows=available_workflows,
                force_summary=force_summary,
                context_budget_config=context_budget_config,
            )

            async for chunk in stream_result:
                if not isinstance(chunk, (list, tuple)):
                    continue
                for message in chunk:
                    result = message.to_dict()
                    result['session_id'] = session_id
                    result['timestamp'] = time.time()

                    result = ContentProcessor.clean_content(result)

                    yield result

            logger.info(f"sessionId={session_id} 🏁 流式处理完成")

        except Exception as e:
            logger.error(f"❌ 流式处理异常: {traceback.format_exc()}")
            error_result = {
                'type': 'error',
                'content': f"处理失败: {str(e)}",
                'role': 'assistant',
                'message_id': str(uuid.uuid4()),
                'session_id': session_id,
            }
            yield error_result

async def prepare_session(request: StreamRequest):
    """准备会话：获取锁并初始化服务"""
    session_id = request.session_id or str(uuid.uuid4())
    request.session_id = session_id
    
    logger.info(f"sessionId={session_id} Server: 请求参数: {request}")
    
    lock = get_session_run_lock(session_id)
    acquired = False
    
    if lock.locked():
        ctx = get_session_context(session_id)
        if not ctx or ctx.status != SessionStatus.INTERRUPTED:
             raise SageHTTPException(status_code=409, detail="会话正在运行中，请先调用 interrupt 或使用不同的会话ID")

    try:
        await asyncio.wait_for(lock.acquire(), timeout=10)
        acquired = True
    except asyncio.TimeoutError:
         raise SageHTTPException(status_code=409, detail="会话正在清理中，请稍后重试")

    try:
        stream_service = SageStreamService(request)
        return session_id, stream_service, lock
    except Exception:
        if acquired and lock.locked():
            await lock.release()
        raise

async def _generate_stream_lines(
    *,
    stream_service: SageStreamService,
    request: StreamRequest,
    session_id: str,
    mode: str,
):
    messages = _prepare_messages(request.messages)
    await _ensure_conversation(session_id, request)

    stream_counter = 0
    last_activity_time = time.time()

    # 从配置获取 context_budget_config
    server_config = get_startup_config()
    context_budget_config = {
        'max_model_len': server_config.default_llm_max_model_len,
        'history_ratio': server_config.context_history_ratio,
        'active_ratio': server_config.context_active_ratio,
        'max_new_message_ratio': server_config.context_max_new_message_ratio,
        'recent_turns': server_config.context_recent_turns
    }

    async for result in stream_service.process_stream(
        messages=messages,
        session_id=session_id,
        user_id=getattr(request, "user_id", None),
        deep_thinking=getattr(request, "deep_thinking", None),
        max_loop_count=getattr(request, "max_loop_count", None),
        multi_agent=getattr(request, "multi_agent", None),
        more_suggest=getattr(request, "more_suggest", False),
        system_context=getattr(request, "system_context", None),
        available_workflows=getattr(request, "available_workflows", None),
        force_summary=getattr(request, "force_summary", False),
        context_budget_config=context_budget_config,
    ):
        stream_counter += 1
        current_time = time.time()
        time_since_last = current_time - last_activity_time
        last_activity_time = current_time

        if stream_counter % 100 == 0:
            logger.info(
                f"📊 流处理状态 - 会话: {session_id}, 计数: {stream_counter}, 间隔: {time_since_last:.3f}s"
            )

        if mode == "chat":
            yield_result = result.copy()
            yield_result.pop("message_type", None)
            yield_result.pop("show_content", None)
            yield_result.pop("is_final", None)
            yield_result.pop("is_chunk", None)
            if yield_result.get("type") == "token_usage":
                continue
            yield json.dumps(yield_result, ensure_ascii=False) + "\n"
        elif mode == "stream":
            async for chunk in send_chunked_json(result):
                yield chunk
        else:
            yield json.dumps(result, ensure_ascii=False) + "\n"


    end_data = {
        "type": "stream_end",
        "session_id": session_id,
        "timestamp": time.time(),
        "total_stream_count": stream_counter,
    }
    total_duration = time.time() - (
        last_activity_time - time_since_last
        if "time_since_last" in locals()
        else last_activity_time
    )
    logger.info(
        f"sessionId={session_id} ✅ 完成流式处理: 总计 {stream_counter} 个流结果, 耗时 {total_duration:.3f}s"
    )
    yield json.dumps(end_data, ensure_ascii=False) + "\n"

async def execute_chat_session(
    request: StreamRequest,
    mode: str,
    session_id: str,
    stream_service: SageStreamService,
):
    """
    执行聊天会话逻辑（仅生成流，不处理锁释放）
    """
    # 2. 生成流
    async for line in _generate_stream_lines(
        stream_service=stream_service,
        request=request,
        session_id=session_id,
        mode=mode,
    ):
        yield line


async def run_chat_session(
    request: StreamRequest,
    mode: str,
):
    """
    运行聊天会话，封装了准备、执行和资源清理的完整生命周期
    """
    # 1. 准备会话（获取锁、初始化服务）
    session_id, stream_service, lock = await prepare_session(request)
    
    try:
        async for line in execute_chat_session(
            request=request,
            mode=mode,
            session_id=session_id,
            stream_service=stream_service,
        ):
            yield line
    finally:
        # 3. 清理资源
        logger.info(f"sessionId={session_id} 流处理结束，清理会话资源")
        if lock.locked():
            await lock.release()
        delete_session_run_lock(session_id)
        logger.info(f"sessionId={session_id} 资源已清理")


async def _execute_chat_task(
    request: StreamRequest,
    session_id: str,
    stream_service: SageStreamService,
    lock,
) -> None:
    """执行异步聊天任务"""
    acquired = False
    try:
        acquired = True
        messages = _prepare_messages(request.messages)
        message_collector, message_order = _initialize_message_collector(messages)
        await _ensure_conversation(session_id, request)
        # 将用户消息保存到conversation
        for message in messages:
            if message.get("role") == "user":
                await _save_single_message(
                    session_id, message_collector, message.get("message_id")
                )
        current_message_id: str | None = None
        saved_ids: set[str] = set()
        async for result in stream_service.process_stream(
            messages=messages,
            session_id=session_id,
            user_id=request.user_id,
            deep_thinking=request.deep_thinking,
            max_loop_count=request.max_loop_count,
            multi_agent=request.multi_agent,
            more_suggest=request.more_suggest,
            system_context=request.system_context,
            available_workflows=request.available_workflows,
            force_summary=request.force_summary,
        ):
            update_message_collector(message_collector, message_order, result)
            mid = result.get("message_id")
            if current_message_id is None:
                current_message_id = mid
            elif mid and mid != current_message_id and current_message_id not in saved_ids:
                await _save_single_message(session_id, message_collector, current_message_id)
                saved_ids.add(current_message_id)
                current_message_id = mid
        if current_message_id and current_message_id not in saved_ids:
            await _save_single_message(session_id, message_collector, current_message_id)
        # 补全 end_data
        end_data = {
            "message_id": str(uuid.uuid4()),
            "type": "stream_end",
            "session_id": session_id,
            "timestamp": time.time(),
        }
        message_collector[end_data["message_id"]] = end_data
        # 保存stream_end消息到conversation
        await _save_single_message(session_id, message_collector, end_data["message_id"])
    except Exception:
        pass
    finally:
        if acquired and lock.locked():
            await lock.release()
        delete_session_run_lock(session_id)

async def run_async_chat_task(request: StreamRequest) -> str:
    """提交异步聊天任务，返回 session_id"""
    session_id, stream_service, lock = await prepare_session(request)
    create_safe_task(
        _execute_chat_task(request, session_id, stream_service, lock),
        name=f"chat_task_{session_id}"
    )
    return session_id

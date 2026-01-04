"""
流式聊天接口路由模块
"""

import asyncio
import json
import time
import uuid
from typing import Dict, Any, Optional, List, Union
from fastapi import APIRouter, Request
from openai import AsyncOpenAI
from core.exceptions import SageHTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from service.sage_stream_service import SageStreamService
from core.config import StartupConfig, get_startup_config
from loguru import logger
import models
from core.client.llm import get_chat_client
from sagents.tool.tool_manager import get_tool_manager
from sagents.context.session_context import (
    SessionStatus,
    delete_session_run_lock,
    get_session_context,
    get_session_run_lock,
)


# 创建路由器
chat_router = APIRouter()


class Message(BaseModel):
    role: str
    content: Union[str, List[Dict[str, Any]]]


class StreamRequest(BaseModel):
    messages: List[Message]
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    deep_thinking: Optional[bool] = None
    max_loop_count: Optional[int] = None
    multi_agent: Optional[bool] = None
    more_suggest: Optional[bool] = None
    system_context: Optional[Dict[str, Any]] = None
    available_workflows: Optional[Dict[str, List[str]]] = None
    llm_model_config: Optional[Dict[str, Any]] = None
    system_prefix: Optional[str] = None
    available_tools: Optional[List[str]] = None
    force_summary: Optional[bool] = False
    agent_id: Optional[str] = None
    agent_name: Optional[str] = None
    content_beautify: Optional[bool] = True

    def __init__(self, **data):
        super().__init__(**data)
        # 确保 messages 中的每个消息都有 role 和 content
        if self.messages:
            for i, msg in enumerate(self.messages):
                if isinstance(msg, dict):
                    # 如果是字典，转换为 Message 对象
                    self.messages[i] = Message(**msg)
                elif not hasattr(msg, "role") or not hasattr(msg, "content"):
                    raise ValueError(f"消息 {i} 缺少必要的 'role' 或 'content' 字段")


def _clean_llm_model_config(llm_model_config: dict) -> dict:
    """清理LLM模型配置，移除空值"""
    if not llm_model_config:
        return {}
    return {k: v for k, v in llm_model_config.items() if v is not None and v != ""}


def _build_llm_model_config(request_config: dict, server_args: StartupConfig) -> dict:
    """构建LLM模型配置"""
    llm_model_config = {
        "model": request_config.get("model", server_args.default_llm_model_name)
    }

    # 只有在有有效的max_tokens值时才添加该键，避免None值导致错误
    max_tokens_value = request_config.get(
        "max_tokens", server_args.default_llm_max_tokens
    )
    if max_tokens_value is not None:
        llm_model_config["max_tokens"] = int(max_tokens_value)

    # 只有在有有效的temperature值时才添加该键，避免None值导致错误
    temperature_value = request_config.get(
        "temperature", server_args.default_llm_temperature
    )
    if temperature_value is not None:
        llm_model_config["temperature"] = float(temperature_value)

    return llm_model_config


def _create_model_client(request_config: dict, server_args: StartupConfig):
    model_client = get_chat_client()
    if request_config:
        api_key = request_config.get("apiKey", server_args.default_llm_api_key)
        base_url = request_config.get("baseUrl", server_args.default_llm_api_base_url)
        model_name = request_config.get("model", server_args.default_llm_model_name)
        logger.info(
            f"初始化新的模型客户端，模型配置api_key: {api_key}, base_url: {base_url}, model: {model_name}"
        )
        model_client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        model_client.model = model_name
    return model_client


def _create_tool_proxy(request: StreamRequest):
    """创建工具代理"""
    if not request.available_tools:
        return get_tool_manager()

    logger.info(f"初始化工具代理，可用工具: {request.available_tools}")

    # 如果request.multi_agent 是true，要确保request.available_tools没有 complete_task 这个工具
    if request.multi_agent and "complete_task" in request.available_tools:
        request.available_tools.remove("complete_task")
    from sagents.tool.tool_proxy import ToolProxy

    tool_proxy = ToolProxy(get_tool_manager(), request.available_tools)
    return tool_proxy


def _setup_stream_service(request: StreamRequest):
    """设置流式服务，返回(stream_service, session_id)"""
    session_id = request.session_id or str(uuid.uuid4())
    request.session_id = session_id
    request.llm_model_config = _clean_llm_model_config(request.llm_model_config or {})
    server_args = get_startup_config()
    model_client = _create_model_client(request.llm_model_config, server_args)
    llm_model_config = _build_llm_model_config(request.llm_model_config, server_args)
    max_model_len = request.llm_model_config.get(
        "max_model_len", server_args.default_llm_max_model_len
    )
    # 创建工具代理
    tool_proxy = _create_tool_proxy(request)
    """创建流式服务"""
    stream_service = SageStreamService(
        model=model_client,
        model_config=llm_model_config,
        tool_manager=tool_proxy,
        preset_running_config={"system_prefix": request.system_prefix},
        workspace=server_args.workspace,
        memory_root=server_args.memory_root,
        max_model_len=max_model_len,
    )
    return stream_service, session_id


def _prepare_messages(request_messages):
    """准备和格式化消息"""
    messages = []
    for msg in request_messages:
        # 保持原始消息的所有字段
        message_dict = msg.model_dump()
        # 先判断原消息是否存在message_id字段， 不存在则初始化一个
        if "message_id" not in message_dict or not message_dict["message_id"]:
            message_dict["message_id"] = str(uuid.uuid4())  # 为每个消息生成唯一ID
        # 如果有content 一定要转化成str
        if message_dict.get("content"):
            message_dict["content"] = str(message_dict["content"])
        messages.append(message_dict)
    return messages


def _initialize_message_collector(messages):
    """初始化消息收集器"""
    message_collector = {}  # {message_id: merged_message}
    message_order = []  # 保持消息的原始顺序

    # 将请求的messages添加到初始化中
    for msg in messages:
        msg_id = msg["message_id"]
        message_collector[msg_id] = msg
        message_order.append(msg_id)

    return message_collector, message_order


def _update_message_collector(message_collector, message_order, result):
    """更新消息收集器"""
    if not isinstance(result, dict) or not result.get("message_id"):
        return

    message_id = result["message_id"]
    # 如果是新消息，初始化
    if message_id not in message_collector:
        message_collector[message_id] = result
        message_order.append(message_id)
    else:
        # 对于工具调用结果消息，完整替换而不是合并
        if result.get("role") != "tool":
            # 合并content和show_content字段（追加）
            if result.get("content"):
                message_collector[message_id]["content"] += str(result["content"])
            if result.get("show_content"):
                message_collector[message_id]["show_content"] += str(
                    result["show_content"]
                )


async def _create_conversation_title(request):
    """创建会话标题"""
    if not request.messages or len(request.messages) == 0:
        return "新会话"

    # 使用第一条用户消息的前50个字符作为标题
    first_message = request.messages[0].content
    if isinstance(first_message, str):
        conversation_title = (
            first_message[:50] + "..." if len(first_message) > 50 else first_message
        )
    elif isinstance(first_message, list) and len(first_message) > 0:
        # 如果是多模态消息，尝试提取文本内容
        for item in first_message:
            if isinstance(item, dict) and item.get("type") == "text":
                text_content = item.get("text", "")
                conversation_title = (
                    text_content[:50] + "..."
                    if len(text_content) > 50
                    else text_content
                )
                break
        else:
            conversation_title = "多模态消息"
    else:
        conversation_title = "新会话"

    return conversation_title


async def _ensure_conversation(session_id: str, request: StreamRequest) -> None:
    conversation_dao = models.ConversationDao()
    existing_conversation = await conversation_dao.get_by_session_id(session_id)
    if not existing_conversation:
        conversation_title = await _create_conversation_title(request)
        await conversation_dao.save_conversation(
            user_id=request.user_id or "default_user",
            agent_id=request.agent_id or "default_agent",
            agent_name=request.agent_name or "Sage Assistant",
            messages=[],
            session_id=session_id,
            title=conversation_title,
        )


class ChatRequest(BaseModel):
    messages: List[Message]
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    system_context: Optional[Dict[str, Any]] = None
    agent_id: str

    def __init__(self, **data):
        super().__init__(**data)
        # 确保 messages 中的每个消息都有 role 和 content
        if self.messages:
            for i, msg in enumerate(self.messages):
                if isinstance(msg, dict):
                    # 如果是字典，转换为 Message 对象
                    self.messages[i] = Message(**msg)
                elif not hasattr(msg, "role") or not hasattr(msg, "content"):
                    raise ValueError(f"消息 {i} 缺少必要的 'role' 或 'content' 字段")


@chat_router.post("/api/chat")
async def chat(request: ChatRequest, http_request: Request):
    """流式聊天接口"""
    if not get_chat_client():
        raise SageHTTPException(
            status_code=503,
            detail="模型客户端未配置或不可用",
        )
    # 验证请求参数
    if not request.messages or len(request.messages) == 0:
        raise SageHTTPException(status_code=400, detail="消息列表不能为空")
    inner_request = StreamRequest(
        messages=request.messages,
        session_id=request.session_id,
        user_id=request.user_id,
        system_context=request.system_context,
    )
    if request.agent_id:
        agent_dao = models.AgentConfigDao()
        agent = await agent_dao.get_by_id(request.agent_id)
        if agent and agent.config:
            inner_request.agent_name = agent.name or "Sage Assistant"
            inner_request.llm_model_config = agent.config.get("llmConfig", {})
            inner_request.available_tools = agent.config.get("availableTools", [])
            inner_request.available_workflows = agent.config.get("availableWorkflows", {})
            inner_request.deep_thinking = agent.config.get("deepThinking", False)
            inner_request.max_loop_count = agent.config.get("maxLoopCount", 10)
            inner_request.multi_agent = agent.config.get("multiAgent", False)
            inner_request.more_suggest = agent.config.get("moreSuggest", False)
            inner_request.system_context = agent.config.get("systemContext", {})
            inner_request.system_prefix = agent.config.get("systemPrefix", "")
        else:
            raise SageHTTPException(status_code=400, detail=f"Agent 不存在")

    session_id = inner_request.session_id or str(uuid.uuid4())
    inner_request.session_id = session_id
    logger.info(f"sessionId={session_id} Server: 请求参数: {inner_request}")
    lock = get_session_run_lock(session_id)
    acquired = False
    if lock.locked():
        ctx = get_session_context(session_id)
        if not ctx or ctx.status != SessionStatus.INTERRUPTED:
            raise SageHTTPException(
                status_code=409,
                detail="会话正在运行中，请先调用 interrupt 或使用不同的会话ID",
            )
    try:
        await asyncio.wait_for(lock.acquire(), timeout=30)
        acquired = True
    except asyncio.TimeoutError:
        raise SageHTTPException(
            status_code=409,
            detail="会话正在清理中，请稍后重试",
        )

    try:
        stream_service, session_id = _setup_stream_service(inner_request)
    except Exception:
        if acquired and lock.locked():
            lock.release()
        raise

    # 生成流式响应
    async def generate_stream():
        """生成SSE流"""
        try:
            # 准备和格式化消息
            messages = _prepare_messages(inner_request.messages)

            logger.info(f"sessionId={session_id} 开始流式处理")
            await _ensure_conversation(session_id, inner_request)

            # 添加流处理计数器和连接状态跟踪
            stream_counter = 0
            last_activity_time = time.time()

            # 初始化消息收集器
            message_collector, message_order = _initialize_message_collector(messages)

            # 处理流式响应，传递所有参数
            async for result in stream_service.process_stream(
                messages=messages,
                session_id=session_id,
                deep_thinking=inner_request.deep_thinking,
                max_loop_count=inner_request.max_loop_count,
                multi_agent=inner_request.multi_agent,
                more_suggest=inner_request.more_suggest,
                system_context=inner_request.system_context,
                available_workflows=inner_request.available_workflows,
                force_summary=inner_request.force_summary,
            ):
                # 更新流处理计数器和活动时间
                stream_counter += 1
                current_time = time.time()
                time_since_last = current_time - last_activity_time
                last_activity_time = current_time

                # 每100个结果记录一次连接状态
                if stream_counter % 100 == 0:
                    logger.info(
                        f"📊 流处理状态 - 会话: {session_id}, 计数: {stream_counter}, 间隔: {time_since_last:.3f}s"
                    )

                # 更新消息收集器
                _update_message_collector(message_collector, message_order, result)
                # 对外发送的字段过滤  ， 去除message_type, show_content, is_final, is_chunk
                yield_result = result.copy()
                if "message_type" in yield_result:
                    del yield_result["message_type"]
                if "show_content" in yield_result:
                    del yield_result["show_content"]
                if "is_final" in yield_result:
                    del yield_result["is_final"]
                if "is_chunk" in yield_result:
                    del yield_result["is_chunk"]
                # 跳过发送token_usage消息
                if yield_result["type"] == "token_usage":
                    continue
                yield json.dumps(yield_result, ensure_ascii=False) + "\n"

                await asyncio.sleep(0.01)  # 避免过快发送

            # 发送流结束标记
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

        finally:
            logger.info(f"sessionId={session_id} 流处理结束，清理会话资源")
            if acquired and lock.locked():
                lock.release()
            delete_session_run_lock(session_id)
            logger.info(f"sessionId={session_id} 资源已清理")

    return StreamingResponse(generate_stream(), media_type="text/plain")

import asyncio
import hashlib
import json
import os
from re import S
import time
import traceback
import uuid

from loguru import logger
from sagents.context.session_context import (
    SessionStatus,
    delete_session_run_lock,
    get_session_context,
    get_session_run_lock,
)
from sagents.sagents import SAgent
from sagents.tool import ToolManager, get_tool_manager
from ... import models
from ...core.exceptions import SageHTTPException
from ...schemas.chat import StreamRequest, CustomSubAgentConfig
from ...core.config import get_startup_config
from .processor import (
    ContentProcessor,
)
from .utils import (
    create_model_client,
    create_skill_proxy,
    create_tool_proxy,
    send_chunked_json,
)

_SAGENT_CACHE = {}


async def populate_request_from_agent_config(
    request: StreamRequest, *, require_agent_id: bool = False
) -> None:
    if request.agent_id is None:
        # 如果要求必须有 Agent ID，则抛出异常
        if require_agent_id:
            raise SageHTTPException(status_code=500, detail="Agent ID 不能为空")
        else:
            # 默认使用request 的信息
            pass
    else:
        agent_dao = models.AgentConfigDao()
        agent = await agent_dao.get_by_id(request.agent_id)
        if not agent or not agent.config:
            # 如果要求必须有 Agent ID，但 Agent 不存在，则抛出异常
            if require_agent_id:
                raise SageHTTPException(status_code=500, detail="Agent 不存在")
            logger.warning(f"Agent {request.agent_id} not found")
            return

    request.agent_name = agent.name or "Sage Assistant"

    def _fill_if_none(field, value):
        if getattr(request, field) is None:
            setattr(request, field, value)

    def _merge_dict(field, value):
        current = getattr(request, field)
        if current is None:
            setattr(request, field, value)
        elif isinstance(current, dict) and isinstance(value, dict):
            # Request 优先，所以 Agent 配置作为 base
            merged = value.copy()
            merged.update(current)
            setattr(request, field, merged)
    # 注入 llm_config 配置
    if request.llm_model_config is None:
        request.llm_model_config = {}
    provider_dao = models.LLMProviderDao()
    provider_id = agent.config.get("llm_provider_id")
    if provider_id: # 有指定则全量替换
        provider = await provider_dao.get_by_id(provider_id)
        request.llm_model_config["base_url"] = provider.base_url
        request.llm_model_config["api_key"] = ",".join(provider.api_keys)
        request.llm_model_config["model"] = provider.model
        request.llm_model_config["max_tokens"] = provider.max_tokens
        request.llm_model_config["temperature"] = provider.temperature
        request.llm_model_config["top_p"] = provider.top_p
        request.llm_model_config["presence_penalty"] = provider.presence_penalty
        request.llm_model_config["max_model_len"] = provider.max_model_len 
    else: # 填充空字段
        provider = await provider_dao.get_default()
        if request.llm_model_config.get("base_url") is None:
            request.llm_model_config["base_url"] = provider.base_url
        if request.llm_model_config.get("api_key") is None:
            request.llm_model_config["api_key"] = ",".join(provider.api_keys)
        if request.llm_model_config.get("model") is None:
            request.llm_model_config["model"] = provider.model
        if request.llm_model_config.get("max_tokens") is None:
            request.llm_model_config["max_tokens"] = provider.max_tokens
        if request.llm_model_config.get("temperature") is None:
            request.llm_model_config["temperature"] = provider.temperature
        if request.llm_model_config.get("top_p") is None:
            request.llm_model_config["top_p"] = provider.top_p
        if request.llm_model_config.get("presence_penalty") is None:
            request.llm_model_config["presence_penalty"] = provider.presence_penalty
        if request.llm_model_config.get("max_model_len") is None:
            request.llm_model_config["max_model_len"] = provider.max_model_len 
        
    if request.max_loop_count is None:
        request.max_loop_count = 10
    _fill_if_none("available_tools", agent.config.get("availableTools", []))
    _fill_if_none("available_skills", agent.config.get("availableSkills", []))
    _merge_dict("available_workflows", agent.config.get("availableWorkflows", {}))
    _fill_if_none("deep_thinking", agent.config.get("deepThinking", False))
    _fill_if_none("max_loop_count", agent.config.get("maxLoopCount", 10))
    _fill_if_none("multi_agent", agent.config.get("multiAgent", False))
    _fill_if_none("more_suggest", agent.config.get("moreSuggest", False))
    _merge_dict("system_context", agent.config.get("systemContext", {}))
    _fill_if_none("system_prefix", agent.config.get("systemPrefix", ""))
    _fill_if_none("memory_type", agent.config.get("memoryType", "session"))
    user = {"本次会话用户id": request.user_id or "default_user"}
    _merge_dict("system_context", user)

    # 处理可用知识库
    available_knowledge_bases = agent.config.get("availableKnowledgeBases", [])
    if available_knowledge_bases:
        kdb_dao = models.KdbDao()
        # 分页获取所有关联的知识库
        kdbs, _ = await kdb_dao.get_kdbs_paginated(
            kdb_ids=available_knowledge_bases,
            data_type=None,
            query_name=None,
            page=1,
            page_size=1000,
        )

        if kdbs:
            # 1. 注入 system_context
            kdb_context = {}
            for kdb in kdbs:
                index_name = kdb.get_index_name()
                kdb_context[f"{kdb.name}数据库的index_name"] = index_name

            _merge_dict("system_context", kdb_context)

            # 2. 添加 retrieve_on_zavixai_db 工具
            current_tools = request.available_tools
            if "retrieve_on_zavixai_db" not in current_tools:
                current_tools.append("retrieve_on_zavixai_db")

    # 处理可用技能
    available_skills = agent.config.get("availableSkills", [])
    if available_skills:
        # file_read execute_python_code execute_shell_command file_write update_file 五种工具注入
        current_skills = getattr(request, "available_skills", [])
        if current_skills is None:
            current_skills = []
            setattr(request, "available_skills", current_skills)
        need_tools = ["load_skill", "execute_python_code", "execute_shell_command", "file_write", "update_file"]
        current_tools = request.available_tools
        for tool in need_tools:
            if tool not in current_tools:
                current_tools.append(tool)
    # 处理可用子Agent
    available_sub_agent_ids = agent.config.get("availableSubAgentIds", [])
    if available_sub_agent_ids:
        # 从数据库获取所有子Agent配置
        sub_agent_dao = models.AgentConfigDao()
        sub_agents = await sub_agent_dao.get_by_ids(available_sub_agent_ids)
        # 转成CustomSubAgentConfig
        custom_sub_agents = [
            CustomSubAgentConfig(
               name=sub_agent.name,
               description=sub_agent.config.get("description", ""),
               available_workflows=sub_agent.config.get("availableWorkflows", []),
               system_context=sub_agent.config.get("systemContext", {}),
               available_tools=sub_agent.config.get("availableTools", []),
               available_skills=sub_agent.config.get("availableSkills", []),
            )
            for sub_agent in sub_agents
        ]
        setattr(request, "custom_sub_agents", custom_sub_agents)

    # 从配置获取 context_budget_config
    from ...core.config import get_startup_config
    server_config = get_startup_config()

    # 尝试从 llm_model_config 中获取 max_model_len
    llm_config = request.llm_model_config or {}

    context_budget_config = {
        'max_model_len': llm_config.get("max_model_len"),
        'history_ratio': server_config.context_history_ratio,
        'active_ratio': server_config.context_active_ratio,
        'max_new_message_ratio': server_config.context_max_new_message_ratio,
        'recent_turns': server_config.context_recent_turns
    }
    request.context_budget_config = context_budget_config

    # 处理可用覆盖mcp配置，注册到tool_manager
    if request.extra_mcp_config:
        tm = get_tool_manager()
        if tm:
            logger.info(f"Registering {len(request.extra_mcp_config)} extra MCP servers")
            for key, value in request.extra_mcp_config.items():
                if not isinstance(value, dict):
                    logger.warning(f"Invalid MCP config for {key}: expected dict, got {type(value)}")
                    continue
                
                # 默认启用
                if "disabled" not in value:
                    value["disabled"] = False
                
                # 简单校验必要参数
                if not any(k in value for k in ["command", "sse_url", "url", "streamable_http_url"]):
                    logger.warning(f"Invalid MCP config for {key}: missing connection parameters")
                    continue

                registered_tools = await tm.register_mcp_server(key, value)
                if registered_tools:
                    new_tool_names = []
                    for tool in registered_tools:
                        tool_name = None
                        if isinstance(tool, dict):
                            tool_name = tool.get("name")
                        else:
                            tool_name = getattr(tool, "name", None)
                        
                        if tool_name:
                            new_tool_names.append(tool_name)
                    
                    # if new_tool_names:
                        # request.available_tools.extend(new_tool_names)
                        # logger.info(f"Added {len(new_tool_names)} tools from MCP server {key} to request")
                else:
                    logger.warning(f"Failed to register MCP server {key} with tools")
        else:
            logger.warning("ToolManager not available, cannot register MCP servers")
            
class SageStreamService:
    """Sage 流式服务类"""

    def __init__(self, request: StreamRequest):
        self.request = request
        # 2. 工具代理
        tool_proxy = create_tool_proxy(request.available_tools)
        self.tool_manager = tool_proxy
        # 3. 技能代理
        skill_proxy = create_skill_proxy(request.available_skills)
        self.skill_manager = skill_proxy
        # 4. 路径处理
        config = get_startup_config()
        workspace = config.workspace
        if workspace:
            workspace = os.path.abspath(workspace)
            if not workspace.endswith('/'):
                workspace += '/'

        # 5. 构造模型客户端
        model_client = create_model_client(request.llm_model_config)
        self.sage_engine = SAgent(
                model=model_client,
                model_config=request.llm_model_config,
                system_prefix=request.system_prefix,
                workspace=workspace,
                memory_type=request.memory_type,
            )

    async def process_stream(self):
        """处理流式聊天请求"""
        session_id = self.request.session_id
        """准备和格式化消息"""
        messages = []
        for msg in self.request.messages:
            message_dict = msg.model_dump()
            if "message_id" not in message_dict or not message_dict["message_id"]:
                message_dict["message_id"] = str(uuid.uuid4())
            if message_dict.get("content"):
                message_dict["content"] = str(message_dict["content"])
            messages.append(message_dict)
        await _ensure_conversation(self.request)
        logger.bind(session_id=session_id).info("🚀 SageStreamService.process_stream 开始")
        try:
            stream_result = self.sage_engine.run_stream(
                input_messages=messages,
                tool_manager=self.tool_manager,
                skill_manager=self.skill_manager,
                session_id=session_id,
                user_id=self.request.user_id,
                deep_thinking=self.request.deep_thinking,
                max_loop_count=self.request.max_loop_count,
                multi_agent=self.request.multi_agent,
                agent_mode=self.request.agent_mode,
                more_suggest=self.request.more_suggest,
                system_context=self.request.system_context,
                available_workflows=self.request.available_workflows,
                force_summary=self.request.force_summary,
                context_budget_config=self.request.context_budget_config,
                custom_sub_agents=[agent.model_dump() for agent in self.request.custom_sub_agents] if self.request.custom_sub_agents else None
            )

            async for chunk in stream_result:
                if not isinstance(chunk, (list, tuple)):
                    continue
                for message in chunk:
                    result = message.to_dict()
                    result['timestamp'] = time.time()

                    result = ContentProcessor.clean_content(result)

                    yield result
                    
        except Exception as e:
            logger.bind(session_id=session_id).error(f"❌ 流式处理异常: {traceback.format_exc()}")
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
    logger.bind(session_id=session_id).info(f"Server: 请求参数 - 「{request.model_dump()}」")
    lock = get_session_run_lock(session_id)
    acquired = False
    if lock.locked():
        ctx = get_session_context(session_id)
        if not ctx or ctx.status != SessionStatus.INTERRUPTED:
             raise SageHTTPException(status_code=500, detail="会话正在运行中，请先调用 interrupt 或使用不同的会话ID")

    try:
        await asyncio.wait_for(lock.acquire(), timeout=10)
        acquired = True
    except asyncio.TimeoutError:
         raise SageHTTPException(status_code=500, detail="会话正在清理中，请稍后重试")

    try:
        stream_service = SageStreamService(request)
        return  stream_service, lock
    except Exception:
        if acquired and lock.locked():
            await lock.release()
        raise


async def execute_chat_session(
    mode: str,
    stream_service: SageStreamService,
):
    """
    执行聊天会话逻辑（仅生成流，不处理锁释放）
    """
    session_id = stream_service.request.session_id
    stream_counter = 0
    last_activity_time = time.time()
    async for result in stream_service.process_stream():
        stream_counter += 1
        current_time = time.time()
        time_since_last = current_time - last_activity_time
        last_activity_time = current_time
        if stream_counter % 100 == 0:
            logger.bind(session_id=session_id).info(
                f"📊 流处理状态 - 计数: {stream_counter}, 间隔: {time_since_last:.3f}s"
            )
        if mode == "chat":
            yield_result = result.copy()
            yield_result.pop("message_type", None)
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
    logger.bind(session_id=session_id).info(
        f"✅ 完成流式处理: 总计 {stream_counter} 个流结果, 耗时 {total_duration:.3f}s"
    )
    yield json.dumps(end_data, ensure_ascii=False) + "\n"


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
        logger.bind(session_id=session_id).info("流处理结束，清理会话资源")
        if lock.locked():
            await lock.release()
        delete_session_run_lock(session_id)
        logger.bind(session_id=session_id).info("资源已清理")

async def _ensure_conversation(request: StreamRequest) -> None:
    conversation_dao = models.ConversationDao()
    existing_conversation = await conversation_dao.get_by_session_id(request.session_id)
    if not existing_conversation:
        conversation_title = await create_conversation_title(request)
        await conversation_dao.save_conversation(
            user_id=request.user_id or "default_user",
            agent_id=request.agent_id or "default_agent",
            agent_name=request.agent_name or "Sage Assistant",
            messages=[],
            session_id=request.session_id,
            title=conversation_title,
        )

async def create_conversation_title(request: StreamRequest):
    """创建会话标题"""
    if not request.messages or len(request.messages) == 0:
        return "新会话"

    first_message = request.messages[0].content
    conversation_title = (first_message[:50] + "..." if len(first_message) > 50 else first_message)
    return conversation_title

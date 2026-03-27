import asyncio
import json
import os
import shutil
import time
import traceback
import uuid
import random
import string
from pathlib import Path
from typing import List
from loguru import logger
from sagents.context.session_context import (
    SessionStatus,
    get_session_run_lock,
)
from sagents.utils.lock_manager import safe_release
from sagents.sagents import SAgent
from sagents.tool import get_tool_manager
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
)
from sagents.session_runtime import get_global_session_manager

_SAGENT_CACHE = {}


async def populate_request_from_agent_config(request: StreamRequest, *, require_agent_id: bool = False) -> None:
    agent = None
    if request.agent_id is None:
        # 如果要求必须有 Agent ID，则抛出异常
        if require_agent_id:
            raise SageHTTPException(detail="Agent ID 不能为空")
        else:
            # 默认使用request 的信息
            pass
    else:
        agent_dao = models.AgentConfigDao()
        agent = await agent_dao.get_by_id(request.agent_id)
        if not agent or not agent.config:
            # 如果要求必须有 Agent ID，但 Agent 不存在，则抛出异常
            if require_agent_id:
                raise SageHTTPException(detail="Agent 不存在")
            logger.warning(f"Agent {request.agent_id} not found")
            agent = None
        else:
            request.agent_name = agent.name or "Sage Assistant"

    agent_config = agent.config if agent and agent.config else None

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

    if agent_config:
        if agent_config.get("name") is not None:
            request.agent_name = agent_config.get("name")
        if agent_config.get("availableTools") is not None:
            request.available_tools = agent_config.get("availableTools")
        if agent_config.get("availableSkills") is not None:
            request.available_skills = agent_config.get("availableSkills")
        if agent_config.get("availableWorkflows") is not None:
            request.available_workflows = agent_config.get("availableWorkflows")
        if agent_config.get("deepThinking") is not None and request.deep_thinking is None:
            request.deep_thinking = agent_config.get("deepThinking")
        if agent_config.get("maxLoopCount") is not None and request.max_loop_count is None:
            request.max_loop_count = agent_config.get("maxLoopCount")
        if agent_config.get("agentMode") is not None and request.agent_mode is None:
            request.agent_mode = agent_config.get("agentMode")
        if agent_config.get("moreSuggest") is not None and request.more_suggest is None:
            request.more_suggest = agent_config.get("moreSuggest")
        if agent_config.get("systemContext") is not None:
            _merge_dict("system_context", agent_config.get("systemContext"))
        if agent_config.get("systemPrefix") is not None:
            request.system_prefix = agent_config.get("systemPrefix")
        if agent_config.get("memoryType") is not None:
            request.memory_type = agent_config.get("memoryType")
        if agent_config.get("availableKnowledgeBases") is not None:
            request.available_knowledge_bases = agent_config.get("availableKnowledgeBases")
        if agent_config.get("availableSubAgentIds") is not None:
            request.available_sub_agent_ids = agent_config.get("availableSubAgentIds")

    if request.agent_name is None:
        request.agent_name = "Sage Assistant"
    # 注入 llm_config 配置
    if request.llm_model_config is None:
        request.llm_model_config = {}
    provider_dao = models.LLMProviderDao()
    provider_id = agent_config.get("llm_provider_id") if agent_config else None
    if provider_id: # 有指定则全量替换
        provider = await provider_dao.get_by_id(provider_id)
        request.llm_model_config["base_url"] = provider.base_url
        request.llm_model_config["api_key"] = provider.api_key
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
            request.llm_model_config["api_key"] = provider.api_key
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
        request.max_loop_count = 50
    _fill_if_none("available_tools", [])
    _fill_if_none("available_skills", [])
    _merge_dict("available_workflows", {})
    _fill_if_none("deep_thinking", False)
    _fill_if_none("multi_agent", False)
    _fill_if_none("more_suggest", False)
    _fill_if_none("system_prefix", "")
    _fill_if_none("memory_type", "session")
    _fill_if_none("available_knowledge_bases", [])
    _fill_if_none("available_sub_agent_ids", [])
    user = {"本次会话用户id": request.user_id or "default_user"}
    _merge_dict("system_context", user)
    if request.agent_id and agent:
        _merge_dict("system_context", {"当前AgentId": request.agent_id})

    # 处理可用知识库
    available_knowledge_bases = request.available_knowledge_bases
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
    available_skills = request.available_skills
    if available_skills:
        # file_read execute_python_code execute_shell_command file_write file_update 五种工具注入
        current_skills = getattr(request, "available_skills", [])
        if current_skills is None:
            current_skills = []
            setattr(request, "available_skills", current_skills)
        need_tools = ['file_read', 'execute_python_code', 'execute_javascript_code',
                    'execute_shell_command', 'file_write', 'file_update', 'load_skill']
        current_tools = request.available_tools
        for tool in need_tools:
            if tool not in current_tools:
                current_tools.append(tool)
    # 处理可用子Agent
    available_sub_agent_ids = request.available_sub_agent_ids
    if available_sub_agent_ids:
        # 从数据库获取所有子Agent配置
        sub_agent_dao = models.AgentConfigDao()
        sub_agents = await sub_agent_dao.get_by_ids(available_sub_agent_ids)
        # 转成CustomSubAgentConfig
        custom_sub_agents = [
            CustomSubAgentConfig(
               name=sub_agent.name,
               description=sub_agent.config.get("description", ""),
               available_workflows=sub_agent.config.get("availableWorkflows", {}),
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
    if request.extra_mcp_config or request.system_context.get("extra_mcp_config",None):
        extra_mcp_config = request.extra_mcp_config or request.system_context.get("extra_mcp_config",None)
        
        tm = get_tool_manager()
        if tm:
            logger.info(f"Registering {len(extra_mcp_config)} extra MCP servers")
            for key, value in extra_mcp_config.items():
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

                else:
                    logger.warning(f"Failed to register MCP server {key} with tools")
            if 'extra_mcp_config' in request.system_context:
                del request.system_context['extra_mcp_config']
        else:
            logger.warning("ToolManager not available, cannot register MCP servers")
            
def _copy_sage_usage_docs_to_workspace(agent_workspace: str) -> None:
    """将 sage-usage-docs 复制到 agent workspace，方便 agent 阅读"""
    try:
        sage_docs_source = Path.home() / ".sage" / "sage-usage-docs"
        if not sage_docs_source.exists():
            logger.debug(f"sage-usage-docs 目录不存在: {sage_docs_source}")
            return

        # 目标路径：workspace/.sage-docs/
        target_dir = Path(agent_workspace) / ".sage-docs"
        target_dir.mkdir(parents=True, exist_ok=True)

        # 复制文档（如果目标目录为空或源目录有更新）
        if target_dir.exists() and any(target_dir.iterdir()):
            # 检查是否需要更新（简单比较文件数量）
            source_files = list(sage_docs_source.rglob("*"))
            target_files = list(target_dir.rglob("*"))
            if len(source_files) <= len(target_files):
                logger.debug(f"sage-usage-docs 已存在于 workspace: {target_dir}")
                return

        # 执行复制
        shutil.copytree(sage_docs_source, target_dir, dirs_exist_ok=True)
        logger.info(f"已将 sage-usage-docs 复制到 agent workspace: {target_dir}")
    except Exception as e:
        # 复制失败不应影响主流程
        logger.warning(f"复制 sage-usage-docs 到 workspace 失败: {e}")


class SageStreamService:
    """Sage 流式服务类"""

    def __init__(self, request: StreamRequest):
        self.request = request
        # 4. 路径处理 (提前计算，供后续使用)
        cfg = get_startup_config()
        # agent工作空间由 agent_dir + user_id + agent_id来。 如果user_id 为空。用 default_user 如果agent_id 为空，用 随机8位英文字母
        user_id = self.request.user_id or "default_user"
        agent_id = self.request.agent_id or ''.join(random.choices(string.ascii_letters, k=8))
        self.agent_workspace = os.path.join(cfg.agents_dir, user_id, agent_id)

        # 创建 workspace 目录并复制 sage-usage-docs
        os.makedirs(self.agent_workspace, exist_ok=True)
        _copy_sage_usage_docs_to_workspace(self.agent_workspace)

        # 2. 工具代理
        tool_proxy = create_tool_proxy(request.available_tools)
        self.tool_manager = tool_proxy
        # 3. 技能代理 (带优先级: agent_workspace > user_skills > system_skills > global)
        skill_proxy, agent_skill_manager = create_skill_proxy(
            request.available_skills,
            user_id=self.request.user_id,
            agent_workspace=self.agent_workspace
        )
        self.skill_proxy = skill_proxy
        self.agent_skill_manager = agent_skill_manager

        # 5. 构造模型客户端
        model_client = create_model_client(request.llm_model_config)
        self.sage_engine = SAgent(
                session_root_space=cfg.session_dir,
                enable_obs=cfg.trace_jaeger_endpoint is not None,
            )
        self.model_client = model_client

    async def process_stream(self):
        """处理流式聊天请求"""
        session_id = self.request.session_id
        """准备和格式化消息"""
        messages = []
        for msg in self.request.messages:
            message_dict = msg.model_dump()
            if "message_id" not in message_dict or not message_dict["message_id"]:
                message_dict["message_id"] = str(uuid.uuid4())
            messages.append(message_dict)
        await _ensure_conversation(self.request)
        try:
            stream_result = self.sage_engine.run_stream(
                session_id=session_id,
                input_messages=messages,
                tool_manager=self.tool_manager,
                skill_manager=self.skill_proxy,
                model=self.model_client,
                model_config=self.request.llm_model_config,
                system_prefix=self.request.system_prefix,
                agent_id=self.request.agent_id,
                host_workspace=self.agent_workspace,
                default_memory_type=self.request.memory_type,
                user_id=self.request.user_id,
                deep_thinking=self.request.deep_thinking,
                max_loop_count=self.request.max_loop_count,
                agent_mode=self.request.agent_mode,
                system_context=self.request.system_context,
                available_workflows=self.request.available_workflows,
                context_budget_config=self.request.context_budget_config,
                custom_sub_agents=[agent.model_dump() for agent in self.request.custom_sub_agents] if self.request.custom_sub_agents else None
            )

            async for chunk in stream_result:
                if not isinstance(chunk, (list, tuple)):
                    continue
                for message in chunk:
                    result = message.to_dict()

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
        session_manager = get_global_session_manager()
        session = session_manager.get(session_id)
        if not session or session.session_context.status != SessionStatus.INTERRUPTED:
             raise SageHTTPException(detail="会话正在运行中，请先调用 interrupt 或使用不同的会话ID")

    try:
        lock_wait_start = time.perf_counter()
        await asyncio.wait_for(lock.acquire(), timeout=10)
        acquired = True
        lock_wait_cost = time.perf_counter() - lock_wait_start
        if lock_wait_cost > 0.2:
            logger.bind(session_id=session_id).warning(f"Session lock wait slow: {lock_wait_cost:.3f}s")
    except asyncio.TimeoutError:
         raise SageHTTPException(detail="会话正在清理中，请稍后重试")

    try:
        stream_service = SageStreamService(request)
        return  stream_service, lock
    except Exception as e:
        if acquired:
            await safe_release(lock, session_id, f"prepare_session 构造失败，保留原始异常: {type(e).__name__}")
        raise


async def execute_chat_session(
    stream_service: SageStreamService,
    **kwargs,
):
    """
    执行聊天会话逻辑（仅生成流，不处理锁释放）
    """

    session_id = stream_service.request.session_id
    request = stream_service.request
    
    # 记录会话开始时下的原始skills
    original_skills = stream_service.agent_skill_manager.list_skills() if stream_service.agent_skill_manager else []
    
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
        yield_result = result.copy()
        yield_result.pop("message_type", None)
        yield_result.pop("is_final", None)
        yield_result.pop("is_chunk", None)
        yield_result.pop("chunk_id", None)
        yield json.dumps(yield_result, ensure_ascii=False) + "\n"

    end_data = {
        "type": "stream_end",
        "session_id": session_id,
        "timestamp": time.time(),
        "total_stream_count": stream_counter,
    }
    yield json.dumps(end_data, ensure_ascii=False) + "\n"

    # 会话结束后的处理，传入原始skills用于合并
    await _handle_session_end(request, original_skills)


async def _handle_session_end(request: StreamRequest, original_skills: List[str]) -> None:
    """
    会话结束后的处理逻辑
    1. 更新conversation表的updated_at
    2. 如果入参available_skills有值，异步检查agent工作空间下的skills目录
    """
    # 更新会话时间戳
    conversation_dao = models.ConversationDao()
    await conversation_dao.update_timestamp(request.session_id)
    logger.bind(session_id=request.session_id).info("会话结束，已更新conversation时间戳")

    # 2. 如果available_skills有值，启动异步任务检查skills目录
    if request.available_skills and request.agent_id:
        asyncio.create_task(_check_and_update_agent_skills(request, original_skills))


async def _check_and_update_agent_skills(request: StreamRequest, original_skills: List[str]) -> None:
    """
    异步检查agent工作空间下的skills目录，只处理新增的skills
    将会话期间新增的skills添加到数据库配置中
    """
    try:
        from ...core.config import get_startup_config

        cfg = get_startup_config()
        user_id = request.user_id
        agent_id = request.agent_id

        # 获取agent工作空间下的实际skills
        agent_skills_path = os.path.join(cfg.agents_dir, user_id, agent_id, "skills")
        
        actual_skills = set()
        if os.path.exists(agent_skills_path) and os.path.isdir(agent_skills_path):
            try:
                from sagents.skill.skill_manager import SkillManager
                tm = SkillManager(skill_dirs=[agent_skills_path], isolated=True)
                for skill in tm.list_skill_info():
                    actual_skills.add(skill.name)
            except Exception as e:
                logger.warning(f"加载Agent工作空间技能失败: {e}")

        # 原始skills（会话开始时工作空间中的）
        original_skills_set = set(original_skills or [])
        
        # 计算会话期间新增的skills
        added_in_session = actual_skills - original_skills_set
        
        # 如果有新增的skills，更新到数据库配置
        if added_in_session:
            agent_dao = models.AgentConfigDao()
            agent = await agent_dao.get_by_id(agent_id)
            if agent and agent.config:
                # 获取当前配置的skills
                current_skills = set(agent.config.get("availableSkills") or [])
                # 合并新增的skills
                updated_skills = current_skills | added_in_session
                
                # 更新配置
                agent.config["availableSkills"] = list(updated_skills)
                await agent_dao.save(agent)
                
                logger.bind(session_id=request.session_id, agent_id=agent_id).info(
                    f"Agent技能列表已更新: 新增={added_in_session}, 最终={updated_skills}"
                )
    except Exception as e:
        logger.bind(session_id=request.session_id).error(f"检查并更新Agent技能失败: {e}")

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

    content = request.messages[0].content
    # 处理多模态消息格式，提取文本内容
    if isinstance(content, list):
        # 从多模态列表中提取文本内容
        text_parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(item.get("text", ""))
        first_message = " ".join(text_parts) if text_parts else "新会话"
    else:
        first_message = content or "新会话"

    conversation_title = (first_message[:50] + "..." if len(first_message) > 50 else first_message)
    return conversation_title

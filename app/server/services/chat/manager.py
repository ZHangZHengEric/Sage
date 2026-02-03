import asyncio

from loguru import logger
from sagents.context.session_context import (
    SessionStatus,
    delete_session_run_lock,
    get_session_context,
    get_session_run_lock,
)

from ... import models
from ...core.exceptions import SageHTTPException
from ...schemas.chat import StreamRequest


class SessionLockContext:
    """会话锁上下文管理器"""
    def __init__(self, session_id: str, timeout: int = 30):
        self.session_id = session_id
        self.timeout = timeout
        self.lock = None
        self.acquired = False

    async def __aenter__(self):
        self.lock = get_session_run_lock(self.session_id)
        if self.lock.locked():
            ctx = get_session_context(self.session_id)
            if not ctx or ctx.status != SessionStatus.INTERRUPTED:
                raise SageHTTPException(
                    status_code=409,
                    detail="会话正在运行中，请先调用 interrupt 或使用不同的会话ID",
                )
        
        try:
            await asyncio.wait_for(self.lock.acquire(), timeout=self.timeout)
            self.acquired = True
            return self
        except asyncio.TimeoutError:
            raise SageHTTPException(
                status_code=409,
                detail="会话正在清理中，请稍后重试",
            )

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        try:
            if self.acquired and self.lock and self.lock.locked():
                await self.lock.release()
        finally:
            delete_session_run_lock(self.session_id)

async def create_conversation_title(request: StreamRequest):
    """创建会话标题"""
    if not request.messages or len(request.messages) == 0:
        return "新会话"

    first_message = request.messages[0].content
    if isinstance(first_message, str):
        conversation_title = (
            first_message[:50] + "..." if len(first_message) > 50 else first_message
        )
    elif isinstance(first_message, list) and len(first_message) > 0:
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
        conversation_title = await create_conversation_title(request)
        await conversation_dao.save_conversation(
            user_id=request.user_id or "default_user",
            agent_id=request.agent_id or "default_agent",
            agent_name=request.agent_name or "Sage Assistant",
            messages=[],
            session_id=session_id,
            title=conversation_title,
        )

async def _save_single_message(session_id: str, message_collector: dict, message_id: str) -> None:
    if not message_id or message_id not in message_collector:
        return
    conversation_dao = models.ConversationDao()
    existing_conversation = await conversation_dao.get_by_session_id(session_id)
    messages = existing_conversation.messages if existing_conversation else []
    merged_message = message_collector.get(message_id)
    messages.append(merged_message)
    await conversation_dao.update_conversation_messages(session_id, messages)

async def populate_request_from_agent_config(
    request: StreamRequest, *, require_agent_id: bool = False
) -> None:
    if not getattr(request, "agent_id", None):
        # 如果要求必须有 Agent ID，则抛出异常
        if require_agent_id:
            raise SageHTTPException(status_code=500, detail="Agent ID 不能为空")
        return
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

    _merge_dict("llm_model_config", agent.config.get("llmConfig", {}))
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
            current_tools = getattr(request, "available_tools", [])
            if current_tools is None:
                current_tools = []
                setattr(request, "available_tools", current_tools)

            if "retrieve_on_zavixai_db" not in current_tools:
                current_tools.append("retrieve_on_zavixai_db")

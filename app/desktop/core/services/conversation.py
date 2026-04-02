"""
会话业务处理模块

封装会话相关的业务逻辑，供路由层调用。
"""

import json
import os
import mimetypes
import tempfile
import zipfile
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger
from sagents.context.session_context import SessionStatus
from sagents.session_runtime import build_conversation_messages_view, get_global_session_manager
from pathlib import Path
from common.core.exceptions import SageHTTPException
from common.models.conversation import Conversation, ConversationDao
from common.models.questionnaire import QuestionnaireDao
from .chat.processor import ContentProcessor
from .chat.stream_manager import StreamManager


async def interrupt_session(
    session_id: str, message: str = "用户请求中断"
) -> Dict[str, Any]:
    """中断指定会话，返回数据字典"""
    session_manager = get_global_session_manager()
    session = session_manager.get(session_id)
    if not session:
        logger.bind(session_id=session_id).info("会话不存在或者已完成")
        return {"session_id": session_id}

    session.session_context.set_status(SessionStatus.INTERRUPTED)
    try:
        await QuestionnaireDao().expire_pending_session(session_id)
        await QuestionnaireDao().expire_pending_sessions_by_prefix(f"{session_id}__questionnaire__")
    except Exception as e:
        logger.bind(session_id=session_id).warning(f"中断会话时更新问卷状态失败: {e}")
    logger.bind(session_id=session_id).info("会话中断成功")
    return {"session_id": session_id}


async def get_session_status(session_id: str) -> Dict[str, Any]:
    """获取指定会话的状态"""
    session_manager = get_global_session_manager()
    session = session_manager.get(session_id)
    if not session:
        raise SageHTTPException(
            status_code=500,
            detail=f"会话 {session_id} 已完成或者不存在",
            error_detail=f"Session '{session_id}' completed or not found",
        )

    # tasks_status = session.session_context.task_manager.to_dict()
    tasks_status = {}
    logger.bind(session_id=session_id).info(f"获取任务数量：{len(tasks_status.get('tasks', []))}")
    return {"session_id": session_id, "tasks_status": tasks_status}


async def get_conversations_paginated(
    page: int = 1,
    page_size: int = 10,
    search: Optional[str] = None,
    agent_id: Optional[str] = None,
    sort_by: str = "date",
) -> Tuple[List[Conversation], int]:
    """分页获取会话列表并构造响应字典"""
    dao = ConversationDao()
    conversations, total_count = await dao.get_conversations_paginated(
        page=page,
        page_size=page_size,
        search=search,
        agent_id=agent_id,
        sort_by=sort_by or "date",
    )
    return conversations, total_count


async def get_conversation_messages(session_id: str) -> Dict[str, Any]:
    """获取指定对话的所有消息并返回响应字典"""
    dao = ConversationDao()
    conversation = await dao.get_by_session_id(session_id)
    if not conversation:
        raise SageHTTPException(
            status_code=500,
            detail=f"会话 {session_id} 不存在",
            error_detail=f"Conversation '{session_id}' not found",
        )

    # 从 common 层获取原始消息（包含 sys_delegate_task 的子会话展开）
    view = build_conversation_messages_view(session_id)

    messages: List[Dict[str, Any]] = []
    for m in view["messages"]:
        cleaned = ContentProcessor.clean_content(m)
        messages.append(cleaned)

    next_stream_index = StreamManager.get_instance().get_history_length(session_id)

    return {
        "conversation_id": session_id,
        "messages": messages,
        "message_count": len(messages),
        "next_stream_index": next_stream_index,
        "conversation_info": {
            "session_id": conversation.session_id,
            "agent_id": conversation.agent_id,
            "agent_name": conversation.agent_name,
            "title": conversation.title,
            "created_at": conversation.created_at,
            "updated_at": conversation.updated_at,
        },
    }


async def delete_conversation(session_id: str) -> str:
    """删除指定对话，返回 session_id"""
    dao = ConversationDao()
    conversation = await dao.get_by_session_id(session_id)
    if not conversation:
        raise SageHTTPException(
            status_code=500,
            detail=f"会话 {session_id} 不存在",
            error_detail=f"Conversation '{session_id}' not found",
        )

    success = await dao.delete_conversation(session_id)
    if not success:
        raise SageHTTPException(
            status_code=500,
            detail=f"删除会话 {session_id} 失败",
            error_detail=f"Failed to delete conversation '{session_id}'",
        )
    logger.bind(session_id=session_id).info("会话删除成功")
    return session_id

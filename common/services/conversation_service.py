"""
Conversation shared service-layer entry points for server and desktop routers.
"""

import json
from collections import Counter
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger
from sagents.context.session_context import SessionStatus
from sagents.session_runtime import (
    build_conversation_messages_view,
    get_global_session_manager,
)

from common.core import config
from common.core.exceptions import SageHTTPException
from common.models.base import get_local_now
from common.models.conversation import Conversation, ConversationDao
from common.services.chat_processor import ContentProcessor
from common.services.chat_utils import get_sessions_root


def _get_cfg() -> config.StartupConfig:
    cfg = config.get_startup_config()
    if not cfg:
        raise RuntimeError("Startup config not initialized")
    return cfg


def _is_desktop_mode() -> bool:
    return _get_cfg().app_mode == "desktop"


def _conversation_error_kwargs(
    detail: str,
    error_detail: str,
) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {
        "detail": detail,
        "error_detail": error_detail,
    }
    if _is_desktop_mode():
        kwargs["status_code"] = 500
    return kwargs


async def interrupt_session(
    session_id: str,
    message: str = "用户请求中断",
) -> Dict[str, Any]:
    session_manager = get_global_session_manager()
    session = session_manager.get(session_id)
    if not session:
        logger.bind(session_id=session_id).info("会话不存在或者已完成")
        return {"session_id": session_id}

    if _is_desktop_mode():
        from common.models.questionnaire import QuestionnaireDao

        session.session_context.set_status(SessionStatus.INTERRUPTED)
        try:
            await QuestionnaireDao().expire_pending_session(session_id)
            await QuestionnaireDao().expire_pending_sessions_by_prefix(
                f"{session_id}__questionnaire__"
            )
        except Exception as e:
            logger.bind(session_id=session_id).warning(f"中断会话时更新问卷状态失败: {e}")
    else:
        session.session_context.status = SessionStatus.INTERRUPTED

    logger.bind(session_id=session_id).info("会话中断成功")
    return {"session_id": session_id}


async def get_session_status(session_id: str) -> Dict[str, Any]:
    session_manager = get_global_session_manager()
    session = session_manager.get(session_id)
    if not session:
        raise SageHTTPException(
            **_conversation_error_kwargs(
                detail=f"会话 {session_id} 已完成或者不存在",
                error_detail=f"Session '{session_id}' completed or not found",
            )
        )

    if _is_desktop_mode():
        tasks_status: Dict[str, Any] = {}
    else:
        tasks_status = session.session_context.task_manager.to_dict()

    logger.bind(session_id=session_id).info(
        f"获取任务数量：{len(tasks_status.get('tasks', []))}"
    )
    return {"session_id": session_id, "tasks_status": tasks_status}


async def get_conversations_paginated(
    page: int = 1,
    page_size: int = 10,
    user_id: Optional[str] = None,
    search: Optional[str] = None,
    agent_id: Optional[str] = None,
    sort_by: str = "date",
) -> Tuple[List[Conversation], int]:
    dao = ConversationDao()
    return await dao.get_conversations_paginated(
        page=page,
        page_size=page_size,
        user_id=user_id,
        search=search,
        agent_id=agent_id,
        sort_by=sort_by or "date",
    )


async def get_conversation_messages(
    session_id: str,
) -> Dict[str, Any]:
    dao = ConversationDao()
    conversation = await dao.get_by_session_id(session_id)
    if not conversation:
        raise SageHTTPException(
            **_conversation_error_kwargs(
                detail=f"会话 {session_id} 不存在",
                error_detail=f"Conversation '{session_id}' not found",
            )
        )

    stream_manager_module = (
        "app.desktop.core.services.chat.stream_manager"
        if _is_desktop_mode()
        else "app.server.services.chat.stream_manager"
    )
    stream_manager = __import__(stream_manager_module, fromlist=["StreamManager"]).StreamManager

    view = build_conversation_messages_view(session_id)
    messages: List[Dict[str, Any]] = []
    for message in view["messages"]:
        messages.append(ContentProcessor.clean_content(message))

    next_stream_index = stream_manager.get_instance().get_history_length(session_id)
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


async def delete_conversation(
    conversation_id: str,
    user_id: Optional[str] = None,
) -> str:
    dao = ConversationDao()
    conversation = await dao.get_by_session_id(conversation_id)
    if not conversation:
        raise SageHTTPException(
            **_conversation_error_kwargs(
                detail=f"会话 {conversation_id} 不存在",
                error_detail=f"Conversation '{conversation_id}' not found",
            )
        )

    success = await dao.delete_conversation(conversation_id)
    if not success:
        raise SageHTTPException(
            **_conversation_error_kwargs(
                detail=f"删除会话 {conversation_id} 失败",
                error_detail=f"Failed to delete conversation '{conversation_id}'",
            )
        )
    logger.bind(session_id=conversation_id).info("会话删除成功")
    return conversation_id


async def update_server_conversation_title(
    session_id: str,
    title: str,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    dao = ConversationDao()
    success = await dao.update_title(session_id, title)
    if not success:
        raise SageHTTPException(
            detail=f"会话 {session_id} 不存在",
            error_detail=f"Conversation '{session_id}' not found",
        )
    return {"session_id": session_id, "title": title}


async def get_agent_usage_stats(
    *,
    days: int,
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> Dict[str, int]:
    safe_days = max(1, min(int(days or 1), 365))
    updated_after = get_local_now() - timedelta(days=safe_days)
    conversations = await ConversationDao().get_recent_conversations(
        user_id=user_id,
        updated_after=updated_after,
        agent_id=agent_id,
    )

    usage_counter: Counter[str] = Counter()
    sessions_root = Path(get_sessions_root())

    for conversation in conversations:
        session_id = str(conversation.session_id or "").strip()
        if not session_id:
            continue

        tools_usage_path = sessions_root / session_id / "tools_usage.json"
        if not tools_usage_path.is_file():
            continue

        try:
            with tools_usage_path.open("r", encoding="utf-8") as f:
                tools_usage = json.load(f)
            if not isinstance(tools_usage, dict):
                continue
            for tool_name, count in tools_usage.items():
                if tool_name:
                    usage_counter[str(tool_name)] += int(count or 0)
        except Exception as e:
            logger.warning(
                f"读取 tools_usage.json 失败，跳过该会话统计: session_id={session_id}, error={e}"
            )

    return dict(usage_counter)

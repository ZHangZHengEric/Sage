"""
Conversation shared service-layer entry points for server and desktop routers.
"""

import asyncio
import json
import os
import hashlib
from collections import Counter
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import anyio
from loguru import logger
from sagents.session_runtime import (
    build_conversation_messages_view,
    get_global_session_manager,
)

from common.core import config
from common.core.exceptions import SageHTTPException
from common.models.base import get_local_now
from common.models.conversation import Conversation, ConversationDao
from common.schemas.conversation import ConversationInfo
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


def _build_session_trace_id(session_id: str) -> str:
    return hashlib.md5(session_id.encode("utf-8")).hexdigest()


def _build_session_trace_url(session_id: str) -> Optional[str]:
    cfg = _get_cfg()
    if not cfg.trace_jaeger_endpoint:
        return None

    trace_id = _build_session_trace_id(session_id)
    if _is_desktop_mode():
        base = (cfg.trace_jaeger_public_url or "").rstrip("/")
        if not base:
            return None
        return f"{base}/trace/{trace_id}"

    return f"/jaeger/trace/{trace_id}"


async def interrupt_session(
    session_id: str,
    message: str = "用户请求中断",
) -> Dict[str, Any]:
    session_manager = get_global_session_manager()
    session = session_manager.get_live_session(session_id)
    if not session:
        logger.bind(session_id=session_id).info("会话不存在或者已完成")
        return {"session_id": session_id}

    if not session.request_interrupt(message):
        logger.bind(session_id=session_id).warning("会话存在但未能写入中断状态")
        return {"session_id": session_id}

    await persist_session_state_with_cancel_protection(session_id)

    stream_managers = []
    try:
        if _is_desktop_mode():
            from app.desktop.core.services.chat.stream_manager import StreamManager as DesktopStreamManager
            stream_managers.append(DesktopStreamManager.get_instance())
    except Exception as e:
        logger.bind(session_id=session_id).debug(f"无法加载 desktop StreamManager: {e}")

    try:
        from common.services.chat_stream_manager import StreamManager as CommonStreamManager
        stream_managers.append(CommonStreamManager.get_instance())
    except Exception as e:
        logger.bind(session_id=session_id).debug(f"无法加载 common StreamManager: {e}")

    for manager in stream_managers:
        try:
            await manager.stop_session(session_id)
        except Exception as e:
            logger.bind(session_id=session_id).warning(f"停止流式会话失败: {e}")

    if _is_desktop_mode():
        from common.models.questionnaire import QuestionnaireDao

        try:
            await QuestionnaireDao().expire_pending_session(session_id)
            await QuestionnaireDao().expire_pending_sessions_by_prefix(
                f"{session_id}__questionnaire__"
            )
        except Exception as e:
            logger.bind(session_id=session_id).warning(f"中断会话时更新问卷状态失败: {e}")

    logger.bind(session_id=session_id).info("会话中断成功")
    return {"session_id": session_id}


async def persist_session_state(session_id: str) -> None:
    session_manager = get_global_session_manager()
    if session_manager:
        try:
            await asyncio.to_thread(session_manager.save_session, session_id)
        except Exception as exc:
            logger.bind(session_id=session_id).warning(f"保存会话快照失败: {exc}")

    messages = await asyncio.to_thread(_load_session_raw_messages, session_id)
    dao = ConversationDao()
    if messages:
        await dao.update_conversation_messages(session_id, messages)
        logger.bind(session_id=session_id).info(
            f"会话状态已同步到 conversations 表，message_count={len(messages)}"
        )
        return

    updated = await dao.update_timestamp(session_id)
    if updated:
        logger.bind(session_id=session_id).info("会话状态已刷新 conversation 时间戳")


async def persist_session_state_with_cancel_protection(session_id: str) -> None:
    persistence_task = None
    try:
        with anyio.CancelScope(shield=True):
            persistence_task = asyncio.create_task(persist_session_state(session_id))
            await asyncio.shield(persistence_task)
    except asyncio.CancelledError as cancel_exc:
        logger.bind(session_id=session_id).warning("会话持久化遇到取消，等待后台任务完成")
        if persistence_task is None:
            raise cancel_exc
        current_task = asyncio.current_task()
        uncancel_count = current_task.uncancel() if current_task and hasattr(current_task, "uncancel") else 0
        try:
            with anyio.CancelScope(shield=True):
                await asyncio.shield(persistence_task)
        finally:
            if current_task and uncancel_count:
                for _ in range(uncancel_count):
                    current_task.cancel()
        raise cancel_exc


async def get_session_status(session_id: str) -> Dict[str, Any]:
    session_manager = get_global_session_manager()
    session = await asyncio.to_thread(session_manager.get, session_id)
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
        tasks_status = await asyncio.to_thread(session.get_tasks_status)

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


def build_conversation_list_result(
    *,
    conversations: List[Conversation],
    total_count: int,
    page: int,
    page_size: int,
    include_user_id: bool = False,
    context_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    conversation_items: List[ConversationInfo] = []
    for conv in conversations:
        message_count = conv.get_message_count()
        trace_id = _build_session_trace_id(conv.session_id)
        trace_url = _build_session_trace_url(conv.session_id)
        conversation_items.append(
            ConversationInfo(
                session_id=conv.session_id,
                user_id=conv.user_id if include_user_id else None,
                agent_id=conv.agent_id,
                agent_name=conv.agent_name,
                title=conv.title,
                message_count=message_count.get("user_count", 0) + message_count.get("agent_count", 0),
                user_count=message_count.get("user_count", 0),
                agent_count=message_count.get("agent_count", 0),
                created_at=conv.created_at.isoformat() if conv.created_at else "",
                updated_at=conv.updated_at.isoformat() if conv.updated_at else "",
                trace_id=trace_id,
                trace_url=trace_url,
            )
        )

    total_pages = (total_count + page_size - 1) // page_size if total_count > 0 else 0
    result: Dict[str, Any] = {
        "list": [item.model_dump(exclude_none=True) for item in conversation_items],
        "total": total_count,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1,
    }
    if context_user_id is not None:
        result["user_id"] = context_user_id
    return result


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

    if user_id and conversation.user_id and conversation.user_id != user_id:
        raise SageHTTPException(
            **_conversation_error_kwargs(
                detail="无权删除该会话",
                error_detail="forbidden",
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


def _get_stream_manager():
    stream_manager_module = (
        "app.desktop.core.services.chat.stream_manager"
        if _is_desktop_mode()
        else "app.server.services.chat.stream_manager"
    )
    return __import__(stream_manager_module, fromlist=["StreamManager"]).StreamManager.get_instance()


def _load_session_raw_messages(session_id: str) -> List[Dict[str, Any]]:
    session_manager = get_global_session_manager()
    if session_manager:
        try:
            session = session_manager.get(session_id)
            if session:
                raw_messages = session.get_messages()
                if raw_messages:
                    return [message.to_dict() for message in raw_messages]
        except Exception as exc:
            logger.bind(session_id=session_id).warning(f"读取 session 原始消息失败，回退数据库: {exc}")
    return []


def _find_last_user_message_index(messages: List[Dict[str, Any]]) -> int:
    for index in range(len(messages) - 1, -1, -1):
        if (messages[index] or {}).get("role") == "user":
            return index
    return -1


def _replace_message_text_content(existing_content: Any, new_text: str) -> Any:
    text = str(new_text or "").strip()
    if isinstance(existing_content, list):
        updated_items: List[Dict[str, Any]] = []
        text_replaced = False
        for item in existing_content:
            if isinstance(item, dict) and item.get("type") == "text" and not text_replaced:
                updated_items.append({**item, "text": text})
                text_replaced = True
                continue
            updated_items.append(item)
        if not text_replaced:
            updated_items.insert(0, {"type": "text", "text": text})
        return updated_items
    return text


def _extract_text_from_message_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(str(item.get("text", "")).strip())
        return "\n".join(part for part in text_parts if part).strip()
    return str(content or "").strip()


def _truncate_messages_after_last_user(
    messages: List[Dict[str, Any]],
    edited_content: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    last_user_index = _find_last_user_message_index(messages)
    if last_user_index < 0:
        raise SageHTTPException(
            **_conversation_error_kwargs(
                detail="会话中不存在可编辑的用户消息",
                error_detail="No editable user message found",
            )
        )

    truncated_messages = [dict(message or {}) for message in messages[: last_user_index + 1]]
    last_user_message = dict(truncated_messages[last_user_index] or {})
    last_user_message["content"] = _replace_message_text_content(
        last_user_message.get("content"),
        edited_content,
    )
    truncated_messages[last_user_index] = last_user_message
    return truncated_messages, last_user_message


def _session_workspace_file_paths(session_id: str) -> Tuple[Optional[Path], Path, Path, Path]:
    sessions_root = Path(get_sessions_root())
    manager = get_global_session_manager()
    workspace_path: Optional[Path] = None
    if manager:
        found = manager.get_session_workspace(session_id)
        if found:
            workspace_path = Path(found)
    if workspace_path is None:
        workspace_path = sessions_root / session_id

    messages_path = workspace_path / "messages.json"
    context_path = workspace_path / "session_context.json"
    tools_usage_path = workspace_path / "tools_usage.json"
    return workspace_path, messages_path, context_path, tools_usage_path


def _write_session_files(session_id: str, messages: List[Dict[str, Any]]) -> None:
    workspace_path, messages_path, context_path, tools_usage_path = _session_workspace_file_paths(session_id)
    if not workspace_path:
        return

    workspace_path.mkdir(parents=True, exist_ok=True)

    with open(messages_path, "w", encoding="utf-8") as f:
        json.dump(messages, f, ensure_ascii=False, indent=4)

    if context_path.exists():
        try:
            with open(context_path, "r", encoding="utf-8") as f:
                context_data = json.load(f)
        except Exception as exc:
            logger.bind(session_id=session_id).warning(f"读取 session_context.json 失败，跳过状态重置: {exc}")
            context_data = None

        if isinstance(context_data, dict):
            context_data["status"] = "idle"
            context_data["updated_at"] = get_local_now().timestamp()
            context_data["child_session_ids"] = []
            context_data["audit_status"] = {}
            context_data["tokens_usage_info"] = {"total_info": {}, "per_step_info": []}
            system_context = context_data.get("system_context")
            if isinstance(system_context, dict):
                system_context.pop("current_time", None)
                system_context.pop("available_sub_agents", None)
                system_context.pop("custom_sub_agents", None)
            with open(context_path, "w", encoding="utf-8") as f:
                json.dump(context_data, f, ensure_ascii=False, indent=4)

    tools_usage: Dict[str, int] = {}
    for message in messages:
        for tool_call in (message or {}).get("tool_calls", []) or []:
            tool_name = (tool_call or {}).get("function", {}).get("name")
            if tool_name:
                tools_usage[tool_name] = tools_usage.get(tool_name, 0) + 1

    with open(tools_usage_path, "w", encoding="utf-8") as f:
        json.dump(tools_usage, f, ensure_ascii=False, indent=4)


async def edit_last_user_message(
    *,
    session_id: str,
    content: str,
    user_id: Optional[str] = None,
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

    if user_id and conversation.user_id and conversation.user_id != user_id:
        raise SageHTTPException(
            **_conversation_error_kwargs(
                detail="无权编辑该会话",
                error_detail="forbidden",
            )
        )

    cleaned_content = str(content or "").strip()
    if not cleaned_content:
        raise SageHTTPException(
            **_conversation_error_kwargs(
                detail="编辑后的消息不能为空",
                error_detail="Edited message cannot be empty",
            )
        )

    await interrupt_session(session_id, "编辑最后一条用户消息")
    await _get_stream_manager().stop_session(session_id)

    source_messages = await asyncio.to_thread(_load_session_raw_messages, session_id)
    source_messages = source_messages or list(conversation.messages or [])
    truncated_messages, last_user_message = _truncate_messages_after_last_user(
        source_messages,
        cleaned_content,
    )

    from common.services.chat_service import _sanitize_title_text

    title_source = _sanitize_title_text(
        _extract_text_from_message_content(last_user_message.get("content"))
    ) or conversation.title or "新会话"

    await dao.update_conversation_messages(session_id, truncated_messages)
    await dao.update_title(session_id, title_source[:50] + "..." if len(title_source) > 50 else title_source)
    await asyncio.to_thread(_write_session_files, session_id, truncated_messages)

    manager = get_global_session_manager()
    if manager:
        try:
            await asyncio.to_thread(manager.close_session, session_id)
        except Exception:
            manager.remove_session_context(session_id)

    logger.bind(session_id=session_id).info(
        f"最后一条用户消息已编辑并截断后续消息，新消息数={len(truncated_messages)}"
    )
    return {
        "session_id": session_id,
        "title": title_source[:50] + "..." if len(title_source) > 50 else title_source,
        "message_count": len(truncated_messages),
        "last_user_message": last_user_message,
    }


async def get_rerun_conversation_payload(
    *,
    session_id: str,
    user_id: Optional[str] = None,
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

    if user_id and conversation.user_id and conversation.user_id != user_id:
        raise SageHTTPException(
            **_conversation_error_kwargs(
                detail="无权重跑该会话",
                error_detail="forbidden",
            )
        )

    source_messages = await asyncio.to_thread(_load_session_raw_messages, session_id)
    source_messages = source_messages or list(conversation.messages or [])
    last_user_index = _find_last_user_message_index(source_messages)
    if last_user_index < 0:
        raise SageHTTPException(
            **_conversation_error_kwargs(
                detail="会话中不存在可重跑的用户消息",
                error_detail="No rerunnable user message found",
            )
        )

    last_user_message = source_messages[last_user_index]
    return {
        "session_id": session_id,
        "user_id": conversation.user_id,
        "agent_id": conversation.agent_id,
        "agent_name": conversation.agent_name,
        "query": _extract_text_from_message_content(last_user_message.get("content")),
    }


def _load_tools_usage_counts_sync(
    conversations: List[Conversation],
    sessions_root: Path,
) -> Dict[str, int]:
    usage_counter: Counter[str] = Counter()

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

    sessions_root = Path(get_sessions_root())
    return await asyncio.to_thread(_load_tools_usage_counts_sync, conversations, sessions_root)

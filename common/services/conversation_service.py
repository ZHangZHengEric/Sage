"""
Conversation shared service-layer entry points for server and desktop routers.
"""

import asyncio
import hashlib
from collections import Counter
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from loguru import logger
from sagents.session_runtime import (
    build_conversation_messages_view,
    get_global_session_manager,
)
from sagents.context.messages.message import is_message_client_visible

from common.core import config
from common.core.context import get_request_locale
from common.core.exceptions import SageHTTPException
from common.core.i18n import t
from common.models.base import get_local_now
from common.models.conversation import Conversation, ConversationDao
from common.schemas.conversation import ConversationInfo
from common.services.chat_processor import ContentProcessor
from common.services.chat_utils import get_sessions_root

_SESSION_PERSISTENCE_TASKS: Dict[str, asyncio.Task] = {}


def _get_cfg() -> config.StartupConfig:
    cfg = config.get_startup_config()
    if not cfg:
        raise RuntimeError("Startup config not initialized")
    return cfg


def _is_desktop_mode() -> bool:
    return _get_cfg().app_mode == "desktop"


def _conversation_error_kwargs(
    detail: str = "",
    error_detail: str = "",
    message_key: str | None = None,
    message_params: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {
        "detail": detail,
        "error_detail": error_detail,
    }
    if message_key:
        kwargs["message_key"] = message_key
    if message_params:
        kwargs["message_params"] = message_params
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


def _validate_session_id_for_storage(session_id: str) -> str:
    value = str(session_id or "")
    if (
        not value
        or value != value.strip()
        or value in {".", ".."}
        or Path(value).name != value
        or "/" in value
        or "\\" in value
        or "\x00" in value
    ):
        raise SageHTTPException(
            status_code=400,
            message_key="conversation.session_id_invalid",
            error_detail="Invalid session_id",
        )
    return value


def inject_user_message(
    session_id: str,
    content: Union[str, List[Dict[str, Any]]],
    *,
    guidance_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """向运行中的 session 注入引导用户消息（统一通过 SAgent 入口）。

    Returns:
        {"session_id": ..., "guidance_id": ..., "accepted": True}

    Raises:
        SageHTTPException: session 不存在/已结束/已中断；或 content 为空。
    """
    from sagents import SAgent

    if isinstance(content, str) and not content.strip():
        raise SageHTTPException(message_key="conversation.content_required")
    sage_engine = SAgent(session_root_space=str(get_sessions_root()))
    try:
        gid = sage_engine.inject_user_message(
            session_id=session_id,
            content=content,
            guidance_id=guidance_id,
            metadata=metadata,
        )
    except LookupError as exc:
        logger.bind(session_id=session_id).info(f"注入引导消息失败: {exc}")
        raise SageHTTPException(
            **_conversation_error_kwargs(
                message_key="conversation.session_not_active_for_inject",
                error_detail=str(exc),
            )
        )
    except ValueError as exc:
        raise SageHTTPException(detail=str(exc))
    logger.bind(session_id=session_id).info(
        f"已注入引导消息 guidance_id={gid} content_type={type(content).__name__}"
    )
    return {"session_id": session_id, "guidance_id": gid, "accepted": True}


def _build_inject_sage_engine():
    from sagents import SAgent

    return SAgent(session_root_space=str(get_sessions_root()))


def _raise_inject_lookup_error(session_id: str, exc: Exception) -> None:
    logger.bind(session_id=session_id).info(f"引导消息操作失败: {exc}")
    raise SageHTTPException(
        **_conversation_error_kwargs(
            message_key="conversation.session_not_active_for_guidance",
            error_detail=str(exc),
        )
    )


def list_pending_user_injections(session_id: str) -> Dict[str, Any]:
    """列出当前活跃 session 上的 pending 引导消息。"""
    sage_engine = _build_inject_sage_engine()
    try:
        items = sage_engine.list_pending_user_injections(session_id=session_id)
    except LookupError as exc:
        _raise_inject_lookup_error(session_id, exc)
    return {"session_id": session_id, "items": items}


def update_pending_user_injection(
    session_id: str,
    guidance_id: str,
    content: Union[str, List[Dict[str, Any]]],
) -> Dict[str, Any]:
    """编辑指定 pending 引导消息。"""
    if not guidance_id:
        raise SageHTTPException(message_key="conversation.guidance_id_required")
    if isinstance(content, str) and not content.strip():
        raise SageHTTPException(message_key="conversation.content_required")
    sage_engine = _build_inject_sage_engine()
    try:
        hit = sage_engine.update_pending_user_injection(
            session_id=session_id,
            guidance_id=guidance_id,
            content=content,
        )
    except LookupError as exc:
        _raise_inject_lookup_error(session_id, exc)
    except ValueError as exc:
        raise SageHTTPException(detail=str(exc))
    if not hit:
        raise SageHTTPException(
            message_key="conversation.guidance_not_found",
            message_params={"guidance_id": guidance_id},
        )
    return {"session_id": session_id, "guidance_id": guidance_id, "updated": True}


def delete_pending_user_injection(
    session_id: str,
    guidance_id: str,
) -> Dict[str, Any]:
    """删除指定 pending 引导消息。"""
    if not guidance_id:
        raise SageHTTPException(message_key="conversation.guidance_id_required")
    sage_engine = _build_inject_sage_engine()
    try:
        hit = sage_engine.delete_pending_user_injection(
            session_id=session_id,
            guidance_id=guidance_id,
        )
    except LookupError as exc:
        _raise_inject_lookup_error(session_id, exc)
    if not hit:
        raise SageHTTPException(
            message_key="conversation.guidance_not_found",
            message_params={"guidance_id": guidance_id},
        )
    return {"session_id": session_id, "guidance_id": guidance_id, "deleted": True}


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
            from app.desktop.core.services.chat.stream_manager import (
                StreamManager as DesktopStreamManager,
            )

            stream_managers.append(DesktopStreamManager.get_instance())
    except Exception as e:
        logger.bind(session_id=session_id).debug(f"无法加载 desktop StreamManager: {e}")

    try:
        from common.services.chat_stream_manager import (
            StreamManager as CommonStreamManager,
        )

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
            logger.bind(session_id=session_id).warning(
                f"中断会话时更新问卷状态失败: {e}"
            )

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
        await dao.update_conversation_counts(session_id, messages)
        logger.bind(session_id=session_id).info(
            f"会话状态已同步到 conversations 表，message_count={len(messages)}"
        )
        return

    updated = await dao.update_timestamp(session_id)
    if updated:
        logger.bind(session_id=session_id).info("会话状态已刷新 conversation 时间戳")


async def _run_single_session_persistence(session_id: str) -> None:
    try:
        await persist_session_state(session_id)
    finally:
        current = _SESSION_PERSISTENCE_TASKS.get(session_id)
        if current is asyncio.current_task():
            _SESSION_PERSISTENCE_TASKS.pop(session_id, None)


async def persist_session_state_with_cancel_protection(session_id: str) -> None:
    persistence_task = _SESSION_PERSISTENCE_TASKS.get(session_id)
    if persistence_task is None or persistence_task.done():
        persistence_task = asyncio.create_task(
            _run_single_session_persistence(session_id),
            name=f"persist-session-state-{session_id}",
        )
        _SESSION_PERSISTENCE_TASKS[session_id] = persistence_task

    try:
        await asyncio.shield(persistence_task)
    except asyncio.CancelledError as cancel_exc:
        logger.bind(session_id=session_id).warning(
            "会话持久化遇到取消，转入后台继续完成"
        )
        if not persistence_task.done():
            persistence_task.add_done_callback(
                lambda task: _log_background_persistence_result(session_id, task)
            )
        raise cancel_exc


def _log_background_persistence_result(session_id: str, task: asyncio.Task) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        logger.bind(session_id=session_id).warning("后台会话持久化被取消")
    except Exception as exc:
        logger.bind(session_id=session_id).warning(f"后台会话持久化失败: {exc}")


async def get_session_status(session_id: str) -> Dict[str, Any]:
    session_manager = get_global_session_manager()
    session = await asyncio.to_thread(session_manager.get, session_id)
    if not session:
        raise SageHTTPException(
            **_conversation_error_kwargs(
                message_key="conversation.completed_or_not_found",
                message_params={"session_id": session_id},
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
    include_message_counts: bool = True,
) -> Dict[str, Any]:
    conversation_items: List[ConversationInfo] = []
    for conv in conversations:
        if include_message_counts:
            message_count = conv.get_message_count()
            user_count = message_count.get("user_count", 0)
            agent_count = message_count.get("agent_count", 0)
            total_messages = int(getattr(conv, "message_count", 0) or 0)
        else:
            total_messages = 0
            user_count = 0
            agent_count = 0
        trace_id = _build_session_trace_id(conv.session_id)
        trace_url = _build_session_trace_url(conv.session_id)
        conversation_items.append(
            ConversationInfo(
                session_id=conv.session_id,
                user_id=conv.user_id if include_user_id else None,
                agent_id=conv.agent_id,
                agent_name=conv.agent_name,
                title=conv.title,
                message_count=total_messages,
                user_count=user_count,
                agent_count=agent_count,
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
    session_manager = get_global_session_manager()
    session = None
    session_workspace = None
    if session_manager:
        get_live_session = getattr(session_manager, "get_live_session", None)
        if callable(get_live_session):
            session = get_live_session(session_id)
        else:
            # Compatibility with small integrations/test doubles implementing
            # only the historical SessionManager.get() surface.
            session = session_manager.get(session_id)
        get_workspace = getattr(session_manager, "get_session_workspace", None)
        if callable(get_workspace):
            session_workspace = get_workspace(session_id)
    if not session and not session_workspace:
        raise SageHTTPException(
            **{
                **_conversation_error_kwargs(
                    message_key="conversation.not_found",
                    message_params={"session_id": session_id},
                    error_detail=f"Conversation '{session_id}' not found",
                ),
                "status_code": 404,
            }
        )

    view = build_conversation_messages_view(session_id)
    messages: List[Dict[str, Any]] = []
    for message in view["messages"]:
        messages.append(ContentProcessor.clean_content(message))

    next_stream_index = _get_stream_manager().get_history_length(session_id)
    if conversation:
        conversation_info = {
            "session_id": conversation.session_id,
            "agent_id": conversation.agent_id,
            "agent_name": conversation.agent_name,
            "title": conversation.title,
            "created_at": conversation.created_at,
            "updated_at": conversation.updated_at,
        }
    else:
        if session is None and session_manager is not None:
            session = session_manager.get(session_id)
        session_context = session.get_context() if session else None
        session_created_at = session.get_start_time() if session else None
        agent_config = (
            getattr(session_context, "agent_config", None) or {}
            if session_context
            else {}
        )
        conversation_info = {
            "session_id": session_id,
            "agent_id": str(
                agent_config.get("agent_id")
                or getattr(session_context, "agent_id", "")
                or ""
            ),
            "agent_name": str(agent_config.get("name") or ""),
            "title": "",
            "created_at": session_created_at or "",
            "updated_at": getattr(session, "end_time", None) or "",
        }
    return {
        "conversation_id": session_id,
        "messages": messages,
        "message_count": len(messages),
        "next_stream_index": next_stream_index,
        "conversation_info": conversation_info,
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
                message_key="conversation.not_found",
                message_params={"session_id": conversation_id},
                error_detail=f"Conversation '{conversation_id}' not found",
            )
        )

    if user_id and conversation.user_id and conversation.user_id != user_id:
        raise SageHTTPException(
            **_conversation_error_kwargs(
                message_key="conversation.delete_forbidden",
                error_detail="forbidden",
            )
        )

    success = await dao.delete_conversation(conversation_id)
    if not success:
        raise SageHTTPException(
            **_conversation_error_kwargs(
                message_key="conversation.delete_failed",
                message_params={"session_id": conversation_id},
                error_detail=f"Failed to delete conversation '{conversation_id}'",
            )
        )
    logger.bind(session_id=conversation_id).info("会话删除成功")
    return conversation_id


async def prepare_session_folder_download(
    session_id: str,
    *,
    is_admin: bool = False,
) -> Tuple[str, str, str]:
    if not is_admin:
        raise SageHTTPException(
            status_code=403,
            message_key="conversation.download_admin_required",
            error_detail="admin_required",
        )

    session_id = _validate_session_id_for_storage(session_id)

    dao = ConversationDao()
    conversation = await dao.get_by_session_id(session_id)
    if not conversation:
        raise SageHTTPException(
            status_code=404,
            message_key="conversation.not_found",
            message_params={"session_id": session_id},
            error_detail=f"Conversation '{session_id}' not found",
        )

    manager = get_global_session_manager()
    try:
        archive_path = await asyncio.to_thread(
            manager.storage.export_session_archive, session_id
        )
    except FileNotFoundError:
        raise SageHTTPException(
            status_code=404,
            message_key="conversation.folder_not_found",
            message_params={"session_id": session_id},
            error_detail=f"Session '{session_id}' not found in storage",
        )
    return archive_path, f"{session_id}.zip", "application/zip"


async def update_server_conversation_title(
    session_id: str,
    title: str,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    dao = ConversationDao()
    success = await dao.update_title(session_id, title)
    if not success:
        raise SageHTTPException(
            message_key="conversation.not_found",
            message_params={"session_id": session_id},
            error_detail=f"Conversation '{session_id}' not found",
        )
    return {"session_id": session_id, "title": title}


def _get_stream_manager():
    stream_manager_module = (
        "app.desktop.core.services.chat.stream_manager"
        if _is_desktop_mode()
        else "app.server.services.chat.stream_manager"
    )
    return __import__(
        stream_manager_module, fromlist=["StreamManager"]
    ).StreamManager.get_instance()


def _load_session_raw_messages(session_id: str) -> List[Dict[str, Any]]:
    session_manager = get_global_session_manager()
    if session_manager:
        try:
            raw_messages = session_manager.get_session_messages(session_id)
            if raw_messages:
                return [message.to_dict() for message in raw_messages]
        except Exception as exc:
            logger.bind(session_id=session_id).warning(
                f"读取 session 原始消息失败: {exc}"
            )
    return []


def _is_hidden_context_message(message: Dict[str, Any]) -> bool:
    return not is_message_client_visible(message)


def _find_last_user_message_index(messages: List[Dict[str, Any]]) -> int:
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index] or {}
        if _is_hidden_context_message(message):
            continue
        if message.get("role") == "user":
            return index
    return -1


def _replace_message_text_content(existing_content: Any, new_text: str) -> Any:
    text = str(new_text or "").strip()
    if isinstance(existing_content, list):
        updated_items: List[Dict[str, Any]] = []
        text_replaced = False
        for item in existing_content:
            if (
                isinstance(item, dict)
                and item.get("type") == "text"
                and not text_replaced
            ):
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
                message_key="conversation.no_editable_user_message",
                error_detail="No editable user message found",
            )
        )

    truncated_messages = [
        dict(message or {}) for message in messages[: last_user_index + 1]
    ]
    last_user_message = dict(truncated_messages[last_user_index] or {})
    last_user_message["content"] = _replace_message_text_content(
        last_user_message.get("content"),
        edited_content,
    )
    truncated_messages[last_user_index] = last_user_message
    return truncated_messages, last_user_message


def _write_session_files(session_id: str, messages: List[Dict[str, Any]]) -> None:
    manager = get_global_session_manager()
    storage = getattr(manager, "storage", None) if manager else None
    if storage is None:
        raise RuntimeError("session storage is not initialized")
    storage.save_message_snapshot(session_id, messages)
    context_data = storage.load_session_snapshot(session_id)
    if isinstance(context_data, dict):
        context_data["status"] = "idle"
        context_data["updated_at"] = get_local_now().timestamp()
        context_data["child_session_ids"] = []
        context_data["audit_status"] = {}
        context_data["tokens_usage_info"] = {
            "total_info": {},
            "per_step_info": [],
        }
        context_data["prompt_token_checkpoints"] = {}
        system_context = context_data.get("system_context")
        if isinstance(system_context, dict):
            system_context.pop("current_time", None)
            system_context.pop("available_sub_agents", None)
            system_context.pop("custom_sub_agents", None)
        storage.save_session_snapshot(session_id, context_data)

    tools_usage: Dict[str, int] = {}
    for message in messages:
        for tool_call in (message or {}).get("tool_calls", []) or []:
            tool_name = (tool_call or {}).get("function", {}).get("name")
            if tool_name:
                tools_usage[tool_name] = tools_usage.get(tool_name, 0) + 1

    storage.save_tools_usage(session_id, tools_usage)


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
                message_key="conversation.not_found",
                message_params={"session_id": session_id},
                error_detail=f"Conversation '{session_id}' not found",
            )
        )

    if user_id and conversation.user_id and conversation.user_id != user_id:
        raise SageHTTPException(
            **_conversation_error_kwargs(
                message_key="conversation.edit_forbidden",
                error_detail="forbidden",
            )
        )

    cleaned_content = str(content or "").strip()
    if not cleaned_content:
        raise SageHTTPException(
            **_conversation_error_kwargs(
                message_key="conversation.edited_message_required",
                error_detail="Edited message cannot be empty",
            )
        )

    await interrupt_session(
        session_id,
        t("chat.edit_last_user_message", locale=get_request_locale()),
    )
    await _get_stream_manager().stop_session(session_id)

    source_messages = await asyncio.to_thread(_load_session_raw_messages, session_id)
    truncated_messages, last_user_message = _truncate_messages_after_last_user(
        source_messages,
        cleaned_content,
    )

    from common.services.chat_service import _sanitize_title_text

    title_source = (
        _sanitize_title_text(
            _extract_text_from_message_content(last_user_message.get("content"))
        )
        or conversation.title
        or t("conversation.new_title", locale=get_request_locale())
    )

    await dao.update_conversation_counts(session_id, truncated_messages)
    await dao.update_title(
        session_id,
        title_source[:50] + "..." if len(title_source) > 50 else title_source,
    )
    await asyncio.to_thread(_write_session_files, session_id, truncated_messages)

    manager = get_global_session_manager()
    if manager:
        try:
            live_session = manager.get_live_session(session_id)
            live_context = (
                live_session.get_context()
                if live_session is not None and live_session.has_context()
                else None
            )
            if live_context is not None and hasattr(
                live_context, "prompt_budget_manager"
            ):
                live_context.prompt_budget_manager.clear()
            await manager.aclose_session(session_id)
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
                message_key="conversation.not_found",
                message_params={"session_id": session_id},
                error_detail=f"Conversation '{session_id}' not found",
            )
        )

    if user_id and conversation.user_id and conversation.user_id != user_id:
        raise SageHTTPException(
            **_conversation_error_kwargs(
                message_key="conversation.rerun_forbidden",
                error_detail="forbidden",
            )
        )

    source_messages = await asyncio.to_thread(_load_session_raw_messages, session_id)
    last_user_index = _find_last_user_message_index(source_messages)
    if last_user_index < 0:
        raise SageHTTPException(
            **_conversation_error_kwargs(
                message_key="conversation.no_rerunnable_user_message",
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
    storage=None,
) -> Dict[str, int]:
    usage_counter: Counter[str] = Counter()

    for conversation in conversations:
        session_id = str(conversation.session_id or "").strip()
        if not session_id:
            continue

        try:
            if storage is None:
                raise RuntimeError("session storage is not initialized")
            tools_usage = storage.load_tools_usage(session_id)
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

    manager = get_global_session_manager()
    storage = getattr(manager, "storage", None) if manager else None
    return await asyncio.to_thread(
        _load_tools_usage_counts_sync, conversations, storage
    )

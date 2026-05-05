from typing import Any, Dict, Optional

from loguru import logger

from common.services import conversation_service


async def build_interrupt_response(
    session_id: str,
    *,
    message: str = "用户请求中断",
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    data = await conversation_service.interrupt_session(session_id, message)
    if user_id:
        data = {**data, "user_id": user_id}
    return {
        "message": f"会话 {session_id} 已中断",
        "data": data,
    }


async def build_status_response(
    session_id: str,
    *,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    result = await conversation_service.get_session_status(session_id)
    tasks = result.get("tasks_status", {}).get("tasks", [])
    logger.bind(session_id=session_id).info(f"获取任务数量：{len(tasks)}")
    if user_id:
        result = {**result, "user_id": user_id}
    return {
        "message": f"会话 {session_id} 状态获取成功",
        "data": result,
    }


async def build_list_conversations_response(
    *,
    page: int,
    page_size: int,
    user_id: Optional[str],
    search: Optional[str],
    agent_id: Optional[str],
    sort_by: Optional[str],
    goal_status: Optional[str] = None,
    include_user_id: bool = False,
    context_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    conversations, total_count = await conversation_service.get_conversations_paginated(
        page=page,
        page_size=page_size,
        user_id=user_id,
        search=search,
        agent_id=agent_id,
        sort_by=sort_by or "date",
        goal_status=goal_status,
    )
    return conversation_service.build_conversation_list_result(
        conversations=conversations,
        total_count=total_count,
        page=page,
        page_size=page_size,
        include_user_id=include_user_id,
        context_user_id=context_user_id,
    )


async def build_delete_response(
    session_id: str,
    *,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    session_id_res = await conversation_service.delete_conversation(
        session_id,
        user_id=user_id,
    )
    logger.bind(session_id=session_id).info("会话删除成功")
    return {
        "message": f"会话 {session_id} 已删除",
        "data": {"session_id": session_id_res},
    }


async def build_goal_status_response(
    session_id: str,
    *,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    data = await conversation_service.get_session_goal(session_id, user_id=user_id)
    if user_id:
        data = {**data, "user_id": user_id}
    return {
        "message": f"会话 {session_id} 目标获取成功",
        "data": data,
    }


async def build_goal_set_response(
    session_id: str,
    *,
    objective: str,
    status,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    data = await conversation_service.set_session_goal(
        session_id,
        objective=objective,
        status=status,
        user_id=user_id,
    )
    if user_id:
        data = {**data, "user_id": user_id}
    return {
        "message": f"会话 {session_id} 目标已更新",
        "data": data,
    }


async def build_goal_clear_response(
    session_id: str,
    *,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    data = await conversation_service.clear_session_goal(session_id, user_id=user_id)
    if user_id:
        data = {**data, "user_id": user_id}
    return {
        "message": f"会话 {session_id} 目标已清除",
        "data": data,
    }


async def build_goal_complete_response(
    session_id: str,
    *,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    data = await conversation_service.complete_session_goal(session_id, user_id=user_id)
    if user_id:
        data = {**data, "user_id": user_id}
    return {
        "message": f"会话 {session_id} 目标已完成",
        "data": data,
    }

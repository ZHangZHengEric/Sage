"""
会话业务处理模块

封装会话相关的业务逻辑，供路由层调用。
"""

import os
from typing import Any, Dict, List, Optional, Tuple

import models
from core.exceptions import SageHTTPException

from sagents.context.session_context import (
    SessionStatus,
    get_session_context,
    get_session_messages,
)
from loguru import logger


async def interrupt_session(
    session_id: str, message: str = "用户请求中断"
) -> Dict[str, Any]:
    """中断指定会话，返回数据字典"""
    session_context = get_session_context(session_id)
    if not session_context:
        logger.info(f"会话 {session_id} 不存在或者已完成")
        return {"session_id": session_id}

    session_context.status = SessionStatus.INTERRUPTED
    logger.info(f"会话 {session_id} 中断成功")
    return {"session_id": session_id}


async def get_session_status(session_id: str) -> Dict[str, Any]:
    """获取指定会话的状态"""
    session_context = get_session_context(session_id)
    if not session_context:
        raise SageHTTPException(
            status_code=404,
            detail=f"会话 {session_id} 已完成或者不存在",
            error_detail=f"Session '{session_id}' completed or not found",
        )

    tasks_status = session_context.task_manager.to_dict()
    logger.info(f"获取会话 {session_id} 任务数量：{len(tasks_status.get('tasks', []))}")
    return {"session_id": session_id, "tasks_status": tasks_status}


async def get_file_workspace(session_id: str) -> Dict[str, Any]:
    """获取指定会话的文件工作空间内容"""
    session_context = get_session_context(session_id)
    if not session_context:
        return {
            "session_id": session_id,
            "files": [],
            "agent_workspace": None,
            "message": f"会话 {session_id} 已完成或者不存在",
        }
    workspace_path = session_context.agent_workspace

    if not workspace_path or not os.path.exists(workspace_path):
        return {
            "session_id": session_id,
            "files": [],
            "agent_workspace": workspace_path,
            "message": "工作空间为空",
        }

    files: List[Dict[str, Any]] = []
    for root, dirs, filenames in os.walk(workspace_path):
        for filename in filenames:
            file_path = os.path.join(root, filename)
            relative_path = os.path.relpath(file_path, workspace_path)
            file_stat = os.stat(file_path)
            files.append(
                {
                    "name": filename,
                    "path": relative_path,
                    "size": file_stat.st_size,
                    "modified_time": file_stat.st_mtime,
                    "is_directory": False,
                }
            )

        for dirname in dirs:
            dir_path = os.path.join(root, dirname)
            relative_path = os.path.relpath(dir_path, workspace_path)
            files.append(
                {
                    "name": dirname,
                    "path": relative_path,
                    "size": 0,
                    "modified_time": os.stat(dir_path).st_mtime,
                    "is_directory": True,
                }
            )

    logger.info(f"获取会话 {session_id} 工作空间文件数量：{len(files)}")
    return {
        "session_id": session_id,
        "files": files,
        "agent_workspace": workspace_path,
        "message": "获取文件列表成功",
    }


def resolve_download_path(workspace_path: str, file_path: str) -> str:
    """校验并返回可下载的文件绝对路径"""
    if not workspace_path or not file_path:
        raise SageHTTPException(
            status_code=400,
            detail="缺少必要的路径参数",
            error_detail="workspace_path or file_path missing",
        )
    full_file_path = os.path.join(workspace_path, file_path)
    if not os.path.abspath(full_file_path).startswith(os.path.abspath(workspace_path)):
        raise SageHTTPException(
            status_code=403,
            detail="访问被拒绝：文件路径超出工作空间范围",
            error_detail="Access denied: file path outside workspace",
        )
    if not os.path.exists(full_file_path):
        raise SageHTTPException(
            status_code=404,
            detail=f"文件不存在: {file_path}",
            error_detail=f"File not found: {file_path}",
        )
    if not os.path.isfile(full_file_path):
        raise SageHTTPException(
            status_code=400,
            detail=f"路径不是文件: {file_path}",
            error_detail=f"Path is not a file: {file_path}",
        )
    return full_file_path


async def get_conversations_paginated(
    page: int = 1,
    page_size: int = 10,
    user_id: Optional[str] = None,
    search: Optional[str] = None,
    agent_id: Optional[str] = None,
    sort_by: str = "date",
) -> Tuple[List[models.Conversation], int]:
    """分页获取会话列表并构造响应字典"""
    dao = models.ConversationDao()
    conversations, total_count = await dao.get_conversations_paginated(
        page=page,
        page_size=page_size,
        user_id=user_id,
        search=search,
        agent_id=agent_id,
        sort_by=sort_by or "date",
    )
    return conversations, total_count


async def get_conversation_messages(conversation_id: str) -> Dict[str, Any]:
    """获取指定对话的所有消息并返回响应字典"""
    dao = models.ConversationDao()
    conversation = await dao.get_by_session_id(conversation_id)
    if not conversation:
        raise SageHTTPException(
            status_code=404,
            detail=f"会话 {conversation_id} 不存在",
            error_detail=f"Conversation '{conversation_id}' not found",
        )

    messages = [m.to_dict() for m in get_session_messages(conversation_id)]
    return {
        "conversation_id": conversation_id,
        "messages": messages,
        "message_count": len(messages),
        "conversation_info": {
            "session_id": conversation.session_id,
            "user_id": conversation.user_id,
            "agent_id": conversation.agent_id,
            "agent_name": conversation.agent_name,
            "title": conversation.title,
            "created_at": conversation.created_at,
            "updated_at": conversation.updated_at,
        },
    }


async def delete_conversation(conversation_id: str) -> str:
    """删除指定对话，返回 conversation_id"""
    dao = models.ConversationDao()
    conversation = await dao.get_by_session_id(conversation_id)
    if not conversation:
        raise SageHTTPException(
            status_code=404,
            detail=f"会话 {conversation_id} 不存在",
            error_detail=f"Conversation '{conversation_id}' not found",
        )

    success = await dao.delete_conversation(conversation_id)
    if not success:
        raise SageHTTPException(
            status_code=500,
            detail=f"删除会话 {conversation_id} 失败",
            error_detail=f"Failed to delete conversation '{conversation_id}'",
        )
    logger.info(f"会话 {conversation_id} 删除成功")
    return conversation_id

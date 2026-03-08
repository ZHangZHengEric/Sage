"""
会话业务处理模块

封装会话相关的业务逻辑，供路由层调用。
"""

import json
import os

from typing import Any, Dict, List, Optional, Tuple

from loguru import logger
from sagents.context.session_context import SessionStatus
from sagents.session_runtime import get_global_session_manager



from .. import models
from ..core.exceptions import SageHTTPException
from .chat.processor import ContentProcessor

async def interrupt_session(
    session_id: str, message: str = "用户请求中断"
) -> Dict[str, Any]:
    """中断指定会话，返回数据字典"""
    session_manager = get_global_session_manager()
    session = session_manager.get(session_id)
    if not session:
        logger.bind(session_id=session_id).info("会话不存在或者已完成")
        return {"session_id": session_id}

    session.session_context.status = SessionStatus.INTERRUPTED
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

    tasks_status = session.session_context.task_manager.to_dict()
    logger.bind(session_id=session_id).info(f"获取任务数量：{len(tasks_status.get('tasks', []))}")
    return {"session_id": session_id, "tasks_status": tasks_status}

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


async def get_conversation_messages(session_id: str) -> Dict[str, Any]:
    """获取指定对话的所有消息并返回响应字典"""
    dao = models.ConversationDao()
    conversation = await dao.get_by_session_id(session_id)
    if not conversation:
        raise SageHTTPException(
            status_code=500,
            detail=f"会话 {session_id} 不存在",
            error_detail=f"Conversation '{session_id}' not found",
        )

    messages = []
    session_manager = get_global_session_manager()
    for m in session_manager.get_session_messages(session_id):
        result = m.to_dict()
        result = ContentProcessor.clean_content(result)
        messages.append(result)

        # 处理 sys_delegate_task，将子任务的对话记录拼接在后面
        if result.get('role') == 'assistant' and result.get('tool_calls'):
            for tool_call in result['tool_calls']:
                if tool_call.get('function', {}).get('name') == 'sys_delegate_task':
                    try:
                        arguments = tool_call['function']['arguments']
                        if isinstance(arguments, str):
                            args = json.loads(arguments)
                        else:
                            args = arguments
                        
                        tasks = args.get('tasks', [])
                        if isinstance(tasks, list):
                            for task in tasks:
                                if isinstance(task, dict):
                                    sub_session_id = task.get('session_id')
                                    if sub_session_id:
                                        sub_msgs = session_manager.get_session_messages(sub_session_id)
                                        for sub_msg in sub_msgs:
                                            sub_result = sub_msg.to_dict()
                                            sub_result = ContentProcessor.clean_content(sub_result)
                                            messages.append(sub_result)
                    except Exception as e:
                        logger.warning(f"处理子任务消息失败: {e}")
                        
    return {
        "conversation_id": session_id,
        "messages": messages,
        "message_count": len(messages),
        "conversation_info": {
            "session_id": conversation.session_id,
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
            status_code=500,
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
    logger.bind(session_id=conversation_id).info("会话删除成功")
    return conversation_id


async def update_conversation_title(session_id: str, title: str) -> Dict[str, Any]:
    """更新会话标题"""
    dao = models.ConversationDao()
    success = await dao.update_title(session_id, title)
    if not success:
        raise SageHTTPException(
            status_code=500,
            detail=f"会话 {session_id} 不存在",
            error_detail=f"Conversation '{session_id}' not found",
        )
    return {"session_id": session_id, "title": title}

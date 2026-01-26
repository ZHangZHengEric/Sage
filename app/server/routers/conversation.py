"""
会话管理接口路由模块
"""

import math
import os
from typing import List, Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse
from loguru import logger
from pydantic import BaseModel

from ..core.render import Response
from ..services.conversation import (
    delete_conversation,
    get_conversation_messages,
    get_conversations_paginated,
    get_file_workspace,
    get_session_status,
    interrupt_session,
    resolve_download_path,
)

# ============= 会话相关模型 =============


class ConversationInfo(BaseModel):
    """会话信息模型"""

    session_id: str
    user_id: str
    agent_id: str
    agent_name: str
    title: str
    message_count: int
    user_count: int
    agent_count: int
    created_at: str
    updated_at: str


# 创建路由器
conversation_router = APIRouter()


class InterruptRequest(BaseModel):
    message: str = "用户请求中断"


@conversation_router.post("/api/sessions/{session_id}/interrupt")
async def interrupt(session_id: str, request: InterruptRequest = None):
    """中断指定会话"""
    message = request.message if request else "用户请求中断"
    data = await interrupt_session(session_id, message)
    return await Response.succ(message=f"会话 {session_id} 已中断", data=data)


@conversation_router.post("/api/sessions/{session_id}/tasks_status")
async def get_status(session_id: str):
    """获取指定会话的状态"""
    result = await get_session_status(session_id)
    tasks = result.get("tasks_status", {}).get("tasks", [])
    logger.info(f"获取会话 {session_id} 任务数量：{len(tasks)}")
    return await Response.succ(message=f"会话 {session_id} 状态获取成功", data=result)


@conversation_router.post("/api/sessions/{session_id}/file_workspace")
async def get_workspace(session_id: str):
    """获取指定会话的文件工作空间"""
    result = await get_file_workspace(session_id)
    files = result.get("files", [])
    logger.info(f"获取会话 {session_id} 工作空间文件数量：{len(files)}")
    return await Response.succ(
        message=result.get("message", "获取文件列表成功"), data=result
    )


@conversation_router.get("/api/sessions/file_workspace/download")
async def download_file(request: Request):
    """下载工作空间中的指定文件"""
    file_path = request.query_params.get("file_path")
    workspace_path = request.query_params.get("workspace_path")
    full_file_path = resolve_download_path(workspace_path, file_path)
    return FileResponse(
        path=full_file_path,
        filename=os.path.basename(file_path),
        media_type="application/octet-stream",
    )


@conversation_router.get("/api/conversations")
async def list_conversations(
    request: Request,
    page: int = Query(1, ge=1, description="页码，从1开始"),
    page_size: int = Query(10, ge=1, le=100, description="每页数量，最大100"),
    user_id: Optional[str] = Query(None, description="用户ID过滤"),
    search: Optional[str] = Query(None, description="搜索关键词"),
    agent_id: Optional[str] = Query(None, description="Agent ID过滤"),
    sort_by: Optional[str] = Query(
        "date", description="排序方式: date, title, messages"
    ),
):
    claims = getattr(request.state, "user_claims", {}) or {}
    current_user_id = claims.get("userid") or user_id
    conversations, total_count = await get_conversations_paginated(
        page=page,
        page_size=page_size,
        user_id=current_user_id,
        search=search,
        agent_id=agent_id,
        sort_by=sort_by or "date",
    )

    conversation_items: List[ConversationInfo] = []
    for conv in conversations:
        message_count = conv.get_message_count()
        conversation_items.append(
            ConversationInfo(
                session_id=conv.session_id,
                user_id=conv.user_id,
                agent_id=conv.agent_id,
                agent_name=conv.agent_name,
                title=conv.title,
                message_count=message_count.get("user_count", 0)
                + message_count.get("agent_count", 0),
                user_count=message_count.get("user_count", 0),
                agent_count=message_count.get("agent_count", 0),
                created_at=conv.created_at.isoformat() if conv.created_at else "",
                updated_at=conv.updated_at.isoformat() if conv.updated_at else "",
            )
        )

    total_pages = math.ceil(total_count / page_size) if total_count > 0 else 0
    has_next = page < total_pages
    has_prev = page > 1

    result = {
        "list": [item.model_dump() for item in conversation_items],
        "total": total_count,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "has_next": has_next,
        "has_prev": has_prev,
    }
    return await Response.succ(data=result, message="获取会话列表成功")


@conversation_router.get("/api/conversations/{conversation_id}/messages")
async def list_messages(conversation_id: str):
    """获取指定对话的所有消息"""
    result = await get_conversation_messages(conversation_id)
    return await Response.succ(
        data=result, message=f"获取会话 {conversation_id} 消息成功"
    )


@conversation_router.delete("/api/conversations/{conversation_id}")
async def delete(conversation_id: str):
    """删除指定对话"""
    conversation_id_res = await delete_conversation(conversation_id)
    logger.info(f"会话 {conversation_id} 删除成功")
    return await Response.succ(
        message=f"会话 {conversation_id} 已删除",
        data={"conversation_id": conversation_id_res},
    )

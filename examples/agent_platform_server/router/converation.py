"""
会话管理接口路由模块
"""

import os

import math
from typing import Optional
from fastapi import APIRouter, Request, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from sagents.utils.logger import logger
from common.exceptions import SageHTTPException
from common.render import Response
from handler.conversation_handler import (
    interrupt_session,
    get_session_status,
    get_file_workspace,
    resolve_download_path,
    get_conversations_paginated,
    get_conversation_messages,
    delete_conversation,
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
    logger.info(f"会话 {session_id} 中断成功")
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
    page: int = Query(1, ge=1, description="页码，从1开始"),
    page_size: int = Query(10, ge=1, le=100, description="每页数量，最大100"),
    user_id: Optional[str] = Query(None, description="用户ID过滤"),
    search: Optional[str] = Query(None, description="搜索关键词"),
    agent_id: Optional[str] = Query(None, description="Agent ID过滤"),
    sort_by: Optional[str] = Query(
        "date", description="排序方式: date, title, messages"
    ),
):
    result = await get_conversations_paginated(
        page=page,
        page_size=page_size,
        user_id=user_id,
        search=search,
        agent_id=agent_id,
        sort_by=sort_by or "date",
    )
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

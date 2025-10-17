"""
会话管理接口路由模块
"""
import os
import zipfile
import tempfile
import json
import asyncio
import math
from pathlib import Path
from typing import Dict, Any, Optional
from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from sagents.utils.logger import logger
from sagents.context.session_context import get_session_context
from entities.entities import (
    StandardResponse, ErrorResponse, SessionStatusData, FileWorkspaceData,
    ConversationInfo, PaginatedResponse, ConversationListRequest,
    create_success_response, create_error_response, SageHTTPException
)
import globals.variables as global_vars

# 创建路由器
session_router = APIRouter()

class InterruptRequest(BaseModel):
    message: str = "用户请求中断"

@session_router.post("/api/sessions/{session_id}/interrupt")
async def interrupt_session(session_id: str, request: InterruptRequest = None):
    """中断指定会话"""
    session_info = global_vars.get_all_active_sessions_service_map().get(session_id)
    if not session_info:
        raise SageHTTPException(
            status_code=404,
            detail="会话不存在",
            error_detail=f"Session '{session_id}' not found"
        )

    stream_service = session_info['stream_service']

    if not stream_service:
        raise SageHTTPException(
            status_code=503,
            detail="服务未配置或不可用",
            error_detail="Stream service not configured or unavailable"
        )
    
    message = request.message if request else "用户请求中断"
    success = stream_service.interrupt_session(session_id, message)
    
    if success:
        logger.info(f"会话 {session_id} 中断成功")
        return create_success_response(
            message=f"会话 {session_id} 已中断",
            data={"session_id": session_id}
        )
    else:
        raise SageHTTPException(
            status_code=404,
            detail=f"会话 {session_id} 不存在或已结束",
            error_detail=f"Session '{session_id}' not found or already ended"
        )

@session_router.post("/api/sessions/{session_id}/tasks_status")
async def get_session_status(session_id: str):
    """获取指定会话的状态"""
    session_info = global_vars.get_all_active_sessions_service_map().get(session_id)
    if not session_info:
        raise SageHTTPException(
            status_code=404,
            detail=f"会话 {session_id} 已完成或者不存在",
            error_detail=f"Session '{session_id}' completed or not found"
        )
    stream_service = session_info['stream_service']
    tasks_status = stream_service.sage_controller.get_tasks_status(session_id)
    tasks_status['tasks']
    logger.info(f"获取会话 {session_id} 任务数量：{len(tasks_status['tasks'])}")
    return create_success_response(
        message=f"会话 {session_id} 状态获取成功",
        data={
            "session_id": session_id,
            "tasks_status": tasks_status
        }
    )

@session_router.post("/api/sessions/{session_id}/file_workspace")
async def get_file_workspace(session_id: str):
    """获取指定会话的文件工作空间"""
    session_info = global_vars.get_all_active_sessions_service_map().get(session_id)
    if not session_info:
        return create_success_response(
            message=f"会话 {session_id} 已完成或者不存在",
            data={"session_id": session_id, "files": []}
        )
    session_context = get_session_context(session_id)
    # 这个会话的工作空间的，绝对路径
    workspace_path = session_context.agent_workspace
    
    if not os.path.exists(workspace_path):
        return create_success_response(
            message="工作空间为空",
            data={"session_id": session_id, "files": []}
        )
    
    files = []
    for root, dirs, filenames in os.walk(workspace_path):
        for filename in filenames:
            file_path = os.path.join(root, filename)
            # 计算相对于工作空间的路径
            relative_path = os.path.relpath(file_path, workspace_path)
            file_stat = os.stat(file_path)
            files.append({
                "name": filename,
                "path": relative_path,
                "size": file_stat.st_size,
                "modified_time": file_stat.st_mtime,
                "is_directory": False
            })
        
        for dirname in dirs:
            dir_path = os.path.join(root, dirname)
            relative_path = os.path.relpath(dir_path, workspace_path)
            files.append({
                "name": dirname,
                "path": relative_path,
                "size": 0,
                "modified_time": os.stat(dir_path).st_mtime,
                "is_directory": True
            })
    logger.info(f"获取会话 {session_id} 工作空间文件数量：{len(files)}")
    return create_success_response(
        message="获取文件列表成功",
        data={
            "session_id": session_id,
            "files": files,
            "agent_workspace": session_context.agent_workspace
        }
    )

@session_router.get("/api/sessions/file_workspace/download")
async def download_file(request: Request):
    """下载工作空间中的指定文件"""
    file_path = request.query_params.get("file_path")
    workspace_path = request.query_params.get("workspace_path")
    
    # 构建完整的文件路径
    full_file_path = os.path.join(workspace_path, file_path)
    
    # 安全检查：确保文件路径在工作空间内
    if not os.path.abspath(full_file_path).startswith(os.path.abspath(workspace_path)):
        raise SageHTTPException(
            status_code=403,
            detail="访问被拒绝：文件路径超出工作空间范围",
            error_detail="Access denied: file path outside workspace"
        )
    
    # 检查文件是否存在
    if not os.path.exists(full_file_path):
        raise SageHTTPException(
            status_code=404,
            detail=f"文件不存在: {file_path}",
            error_detail=f"File not found: {file_path}"
        )
    
    # 检查是否为文件（不是目录）
    if not os.path.isfile(full_file_path):
        raise SageHTTPException(
            status_code=400,
            detail=f"路径不是文件: {file_path}",
            error_detail=f"Path is not a file: {file_path}"
        )
    
    # 返回文件
    return FileResponse(
        path=full_file_path,
        filename=os.path.basename(file_path),
        media_type='application/octet-stream'
    )


@session_router.get("/api/conversations")
async def get_conversations_paginated(
    page: int = Query(1, ge=1, description="页码，从1开始"),
    page_size: int = Query(10, ge=1, le=100, description="每页数量，最大100"),
    user_id: Optional[str] = Query(None, description="用户ID过滤"),
    search: Optional[str] = Query(None, description="搜索关键词"),
    agent_id: Optional[str] = Query(None, description="Agent ID过滤"),
    sort_by: Optional[str] = Query("date", description="排序方式: date, title, messages")
):
    """分页获取会话列表"""
    try:
        # 获取数据库管理器
        db_manager = global_vars.get_database_manager()
        if not db_manager:
            raise SageHTTPException(
                status_code=500,
                detail="数据库管理器未初始化",
                error_detail="Database manager not initialized"
            )
        
        # 分页查询会话
        conversations, total_count = await db_manager.get_conversations_paginated(
            page=page, 
            page_size=page_size, 
            user_id=user_id,
            search=search,
            agent_id=agent_id,
            sort_by=sort_by or "date"
        )
        
        # 转换为响应格式
        conversation_items = []
        for conv in conversations:
            conversation_items.append(ConversationInfo(
                session_id=conv.session_id,
                user_id=conv.user_id,
                agent_id=conv.agent_id,
                agent_name=conv.agent_name,
                title=conv.title,
                message_count=conv.get_message_count(),
                created_at=conv.created_at,
                updated_at=conv.updated_at
            ))
        
        # 计算分页信息
        total_pages = math.ceil(total_count / page_size) if total_count > 0 else 0
        has_next = page < total_pages
        has_prev = page > 1
        
        # 构建分页响应
        paginated_data = PaginatedResponse(
            list=conversation_items,
            total=total_count,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            has_next=has_next,
            has_prev=has_prev
        )
        
        return create_success_response(
            data=paginated_data.dict(),
            message="获取会话列表成功"
        )
        
    except Exception as e:
        logger.error(f"获取会话列表失败: {e}")
        raise SageHTTPException(
            status_code=500,
            detail="获取会话列表失败",
            error_detail=str(e)
        )
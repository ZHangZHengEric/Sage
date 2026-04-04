"""
会话管理接口路由模块
"""

from typing import Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from common.core.request_identity import get_request_role, get_request_user_id
from common.core.render import Response
from common.services import conversation_router_service, conversation_service

# 创建路由器
conversation_router = APIRouter()


class InterruptRequest(BaseModel):
    message: str = "用户请求中断"


@conversation_router.post("/api/sessions/{session_id}/interrupt")
async def interrupt(session_id: str, request: Request, body: InterruptRequest = None):
    """中断指定会话"""
    result = await conversation_router_service.build_interrupt_response(
        session_id,
        message=body.message if body else "用户请求中断",
        user_id=get_request_user_id(request),
    )
    return await Response.succ(message=result["message"], data=result["data"])


class UpdateTitleRequest(BaseModel):
    title: str


@conversation_router.post("/api/conversations/{session_id}/title")
async def update_title(session_id: str, request: Request, body: UpdateTitleRequest):
    """更新会话标题"""
    data = await conversation_service.update_server_conversation_title(
        session_id,
        body.title,
        user_id=get_request_user_id(request),
    )
    return await Response.succ(message=f"会话 {session_id} 标题已更新", data=data)


@conversation_router.post("/api/sessions/{session_id}/tasks_status")
async def get_status(session_id: str, request: Request):
    """获取指定会话的状态"""
    result = await conversation_router_service.build_status_response(
        session_id,
        user_id=get_request_user_id(request),
    )
    return await Response.succ(message=result["message"], data=result["data"])


@conversation_router.get("/api/conversations")
async def list_conversations(
    request: Request,
    page: int = Query(1, ge=1, description="页码，从1开始"),
    page_size: int = Query(10, ge=1, le=100, description="每页数量，最大100"),
    user_id: Optional[str] = Query(None, description="用户ID过滤"),
    search: Optional[str] = Query(None, description="搜索关键词"),
    agent_id: Optional[str] = Query(None, description="Agent ID过滤"),
    sort_by: Optional[str] = Query("date", description="排序方式: date, title, messages"),
):
    current_user_id = get_request_user_id(request, user_id or "")
    role = get_request_role(request)

    if role == "admin":
        current_user_id = None
    elif role == "user" and not current_user_id:
        return await Response.succ(data={"list": [], "total": 0}, message="获取会话列表成功")
    result = await conversation_router_service.build_list_conversations_response(
        page=page,
        page_size=page_size,
        user_id=current_user_id,
        search=search,
        agent_id=agent_id,
        sort_by=sort_by,
        include_user_id=True,
        context_user_id=current_user_id,
    )
    return await Response.succ(data=result, message="获取会话列表成功")


@conversation_router.get("/api/conversations/{session_id}/messages")
async def get_messages(session_id: str, request: Request):
    """获取指定对话的所有消息"""
    data = await conversation_service.get_conversation_messages(session_id)
    return await Response.succ(data=data, message="获取消息成功")


@conversation_router.get("/api/share/conversations/{session_id}/messages")
async def get_shared_messages(session_id: str):
    """获取分享对话的消息（无权限校验）"""
    data = await conversation_service.get_conversation_messages(session_id)
    return await Response.succ(data=data, message="获取分享消息成功")


@conversation_router.delete("/api/conversations/{session_id}")
async def delete(session_id: str, request: Request):
    """删除指定对话"""
    result = await conversation_router_service.build_delete_response(
        session_id,
        user_id=get_request_user_id(request),
    )
    return await Response.succ(message=result["message"], data=result["data"])

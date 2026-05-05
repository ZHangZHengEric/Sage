"""
会话管理接口路由模块
"""

from typing import Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from common.core.render import Response
from common.schemas.goal import GoalSetRequest
from common.services import conversation_router_service, conversation_service
from ..user_context import get_desktop_user_id

# 创建路由器
conversation_router = APIRouter()


class InterruptRequest(BaseModel):
    message: str = "用户请求中断"


class EditLastUserMessageRequest(BaseModel):
    content: str


@conversation_router.get("/api/sessions/{session_id}/goal")
async def get_goal(session_id: str, request: Request):
    result = await conversation_router_service.build_goal_status_response(
        session_id,
        user_id=get_desktop_user_id(request),
    )
    return await Response.succ(message=result["message"], data=result["data"])


@conversation_router.post("/api/sessions/{session_id}/goal")
async def set_goal(session_id: str, request: Request, body: GoalSetRequest):
    result = await conversation_router_service.build_goal_set_response(
        session_id,
        objective=body.objective,
        status=body.status,
        user_id=get_desktop_user_id(request),
    )
    return await Response.succ(message=result["message"], data=result["data"])


@conversation_router.delete("/api/sessions/{session_id}/goal")
async def clear_goal(session_id: str, request: Request):
    result = await conversation_router_service.build_goal_clear_response(
        session_id,
        user_id=get_desktop_user_id(request),
    )
    return await Response.succ(message=result["message"], data=result["data"])


@conversation_router.post("/api/sessions/{session_id}/goal/complete")
async def complete_goal(session_id: str, request: Request):
    result = await conversation_router_service.build_goal_complete_response(
        session_id,
        user_id=get_desktop_user_id(request),
    )
    return await Response.succ(message=result["message"], data=result["data"])


class InjectUserMessageRequest(BaseModel):
    content: str
    guidance_id: Optional[str] = None
    metadata: Optional[dict] = None


@conversation_router.post("/api/sessions/{session_id}/interrupt")
async def interrupt(session_id: str, request: Request, body: InterruptRequest = None):
    """中断指定会话"""
    result = await conversation_router_service.build_interrupt_response(
        session_id,
        message=body.message if body else "用户请求中断",
    )
    return await Response.succ(message=result["message"], data=result["data"])


@conversation_router.post("/api/sessions/{session_id}/inject-user-message")
async def inject_user_message(session_id: str, request: Request, body: InjectUserMessageRequest):
    """向运行中的会话注入一条引导用户消息（非阻塞）。"""
    result = conversation_router_service.build_inject_user_message_response(
        session_id,
        content=body.content,
        guidance_id=body.guidance_id,
        metadata=body.metadata,
        user_id=get_desktop_user_id(request),
    )
    return await Response.succ(message=result["message"], data=result["data"])


class UpdateInjectUserMessageRequest(BaseModel):
    content: str


@conversation_router.get("/api/sessions/{session_id}/inject-user-message")
async def list_pending_user_injections(session_id: str, request: Request):
    """列出 pending 引导消息。"""
    result = conversation_router_service.build_list_pending_user_injections_response(
        session_id,
        user_id=get_desktop_user_id(request),
    )
    return await Response.succ(message=result["message"], data=result["data"])


@conversation_router.patch("/api/sessions/{session_id}/inject-user-message/{guidance_id}")
async def update_pending_user_injection(
    session_id: str,
    guidance_id: str,
    request: Request,
    body: UpdateInjectUserMessageRequest,
):
    """编辑一条 pending 引导消息。"""
    result = conversation_router_service.build_update_pending_user_injection_response(
        session_id,
        guidance_id,
        content=body.content,
        user_id=get_desktop_user_id(request),
    )
    return await Response.succ(message=result["message"], data=result["data"])


@conversation_router.delete("/api/sessions/{session_id}/inject-user-message/{guidance_id}")
async def delete_pending_user_injection(
    session_id: str,
    guidance_id: str,
    request: Request,
):
    """删除一条 pending 引导消息。"""
    result = conversation_router_service.build_delete_pending_user_injection_response(
        session_id,
        guidance_id,
        user_id=get_desktop_user_id(request),
    )
    return await Response.succ(message=result["message"], data=result["data"])


@conversation_router.post("/api/sessions/{session_id}/tasks_status")
async def get_status(session_id: str, request: Request):
    """获取指定会话的状态"""
    result = await conversation_router_service.build_status_response(session_id)
    return await Response.succ(message=result["message"], data=result["data"])


@conversation_router.get("/api/conversations")
async def list_conversations(
    request: Request,
    page: int = Query(1, ge=1, description="页码，从1开始"),
    page_size: int = Query(10, ge=1, le=100, description="每页数量，最大100"),
    search: Optional[str] = Query(None, description="搜索关键词"),
    agent_id: Optional[str] = Query(None, description="Agent ID过滤"),
    sort_by: Optional[str] = Query("date", description="排序方式: date, title, messages"),
    goal_status: Optional[str] = Query(None, description="目标状态过滤: active, paused, completed, none"),
):
    user_id = get_desktop_user_id(request)
    result = await conversation_router_service.build_list_conversations_response(
        page=page,
        page_size=page_size,
        user_id=user_id,
        search=search,
        agent_id=agent_id,
        sort_by=sort_by,
        goal_status=goal_status,
    )
    return await Response.succ(data=result, message="获取会话列表成功")


@conversation_router.get("/api/conversations/{session_id}/messages")
async def get_messages(session_id: str, request: Request):
    """获取指定对话的所有消息"""
    data = await conversation_service.get_conversation_messages(session_id)
    return await Response.succ(data=data, message="获取消息成功")


@conversation_router.post("/api/conversations/{session_id}/edit-last-user-message")
async def edit_last_user_message(session_id: str, request: Request, body: EditLastUserMessageRequest):
    data = await conversation_service.edit_last_user_message(
        session_id=session_id,
        content=body.content,
        user_id=get_desktop_user_id(request),
    )
    return await Response.succ(message="最后一条用户消息已更新", data=data)


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
        user_id=get_desktop_user_id(request),
    )
    return await Response.succ(message=result["message"], data=result["data"])

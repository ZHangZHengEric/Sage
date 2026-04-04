"""
工具执行接口路由模块
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel

from common.core.render import Response
from common.services import tool_service
from ..user_context import get_desktop_user_id, get_desktop_user_role

# 创建路由器
tool_router = APIRouter(prefix="/api/tools")


class ExecToolRequest(BaseModel):
    tool_name: str
    tool_params: Dict[str, Any]


@tool_router.post("/exec")
async def exec_tool(request: ExecToolRequest, http_request: Request):
    """执行工具"""
    tool_response = await tool_service.execute_tool(
        request.tool_name,
        request.tool_params,
        user_id=get_desktop_user_id(http_request),
        role=get_desktop_user_role(http_request),
    )
    return await Response.succ("工具执行成功", tool_response)


@tool_router.get("")
async def get_tools(http_request: Request, type: Optional[str] = None):
    """
    获取可用工具列表

    Args:
        type: 工具类型过滤参数，可选值：basic, mcp, agent等

    """
    tools = await tool_service.list_tools(
        user_id=get_desktop_user_id(http_request),
        role=get_desktop_user_role(http_request),
        tool_type=type,
    )

    return await Response.succ(message="获取工具列表成功", data={"tools": tools})

"""
工具执行接口路由模块
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel

from common.core.render import Response
from common.core.request_identity import get_request_role, get_request_user_id
from common.services import tool_service

# 创建路由器
tool_router = APIRouter(prefix="/api/tools")


class ExecToolRequest(BaseModel):
    tool_name: str
    tool_params: Dict[str, Any] = {}
    arguments: Dict[str, Any] = {}


def _resolve_request_language(
    http_request: Request, language: Optional[str] = None, default: str = "en"
) -> str:
    candidate = (language or "").strip()
    if not candidate:
        headers = http_request.headers
        candidate = (
            headers.get("x-accept-language") or headers.get("accept-language") or ""
        ).strip()

    normalized = candidate.lower().replace("_", "-")
    if normalized.startswith("zh"):
        return "zh"
    if normalized.startswith("pt"):
        return "pt"
    if normalized.startswith("en"):
        return "en"
    return default


@tool_router.post("/exec")
async def exec_tool(request: ExecToolRequest, http_request: Request):
    """执行工具"""
    tool_params = request.tool_params or request.arguments or {}
    tool_response = await tool_service.execute_tool(
        request.tool_name,
        tool_params,
        user_id=get_request_user_id(http_request),
        role=get_request_role(http_request),
    )
    return await Response.succ("tool.exec_success", tool_response)


@tool_router.get("")
async def get_tools(
    http_request: Request, type: Optional[str] = None, language: Optional[str] = None
):
    """
    获取可用工具列表

    Args:
        type: 工具类型过滤参数，可选值：basic, mcp, agent等

    """
    tools = await tool_service.list_tools(
        user_id=get_request_user_id(http_request),
        role=get_request_role(http_request),
        tool_type=type,
        language=_resolve_request_language(http_request, language, default="en"),
    )

    return await Response.succ(message="tool.list_loaded", data={"tools": tools})

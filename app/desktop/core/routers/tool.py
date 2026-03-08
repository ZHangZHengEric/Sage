"""
工具执行接口路由模块
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Request
from loguru import logger
from pydantic import BaseModel
from sagents.tool.tool_manager import get_tool_manager

from ..core.exceptions import SageHTTPException
from ..core.render import Response
from ..models import MCPServerDao

# 创建路由器
tool_router = APIRouter(prefix="/api/tools")


class ExecToolRequest(BaseModel):
    tool_name: str
    tool_params: Dict[str, Any]


def _normalize_source(source: str) -> str:
    if source.startswith("MCP Server: "):
        return source[len("MCP Server: ") :]
    if source.startswith("内置MCP: "):
        return source[len("内置MCP: ") :]
    return source


@tool_router.post("/exec")
async def exec_tool(request: ExecToolRequest, http_request: Request):
    """执行工具"""
    logger.info(f"执行工具请求: {request}")

    tool_manager = get_tool_manager()
    if not tool_manager:
        raise SageHTTPException(
            status_code=500,
            detail="工具管理器未初始化",
            error_detail="Tool manager not initialized",
        )

    # 检测工具是否存在
    if request.tool_name not in tool_manager.tools.keys():
        logger.error(f"执行工具失败: {request.tool_name}")
        raise SageHTTPException(
            status_code=500,
            detail="工具不存在",
            error_detail=f"Tool '{request.tool_name}' not found",
        )
    
    tool_response = await tool_manager.run_tool_async(
        tool_name=request.tool_name,
        session_context=None,
        session_id="",
        **request.tool_params,
    )
    if tool_response:
        logger.info(f"执行工具成功: {request.tool_name}")
        return await Response.succ("工具执行成功", tool_response)
    else:
        logger.error(f"执行工具失败: {request.tool_name}")
        raise SageHTTPException(
            status_code=500,
            detail="工具执行失败",
            error_detail=f"Tool '{request.tool_name}' execution failed",
        )


@tool_router.get("")
async def get_tools(http_request: Request, type: Optional[str] = None):
    """
    获取可用工具列表

    Args:
        type: 工具类型过滤参数，可选值：basic, mcp, agent等

    """
    tm = get_tool_manager()
    tools = []
    if tm:
        available_tools = tm.list_tools_with_type()
        
        for tool_info in available_tools:
            tool_type = tool_info.get("type", "basic")
            source = tool_info.get("source", "internal")

            # 如果指定了type参数，则进行过滤
            if type is not None and tool_type != type:
                continue

            tools.append(
                {
                    "name": tool_info.get("name", ""),
                    "description": tool_info.get("description", ""),
                    "parameters": tool_info.get("parameters", {}),
                    "type": tool_type,
                    "source": source,
                }
            )

    return await Response.succ(message="获取工具列表成功", data={"tools": tools})

from typing import Any, Dict, List, Optional

from loguru import logger
from sagents.tool.tool_manager import get_tool_manager

from common.core.exceptions import SageHTTPException
from common.models.mcp_server import MCPServerDao


def normalize_tool_source(source: str) -> str:
    if source.startswith("MCP Server: "):
        return source[len("MCP Server: ") :]
    if source.startswith("内置MCP: "):
        return source[len("内置MCP: ") :]
    return source


def _get_tool_manager_or_raise():
    tool_manager = get_tool_manager()
    if not tool_manager:
        raise SageHTTPException(
            status_code=500,
            detail="工具管理器未初始化",
            error_detail="Tool manager not initialized",
        )
    return tool_manager


async def execute_tool(
    tool_name: str,
    tool_params: Dict[str, Any],
    *,
    user_id: str = "",
    role: str = "user",
) -> Any:
    logger.info(f"执行工具请求: tool={tool_name}")

    tool_manager = _get_tool_manager_or_raise()
    if tool_name not in tool_manager.tools.keys():
        logger.error(f"执行工具失败: {tool_name}")
        raise SageHTTPException(
            status_code=500,
            detail="工具不存在",
            error_detail=f"Tool '{tool_name}' not found",
        )

    if role != "admin":
        tool_info = tool_manager.get_tool_info(tool_name)
        tool_type = tool_info.get("type", "basic")
        if tool_type == "mcp":
            source = normalize_tool_source(tool_info.get("source", "internal"))
            dao = MCPServerDao()
            server = await dao.get_by_name(source)
            if server and server.user_id and server.user_id != user_id:
                raise SageHTTPException(
                    detail="无权使用该工具",
                    error_detail="Permission denied",
                )

    tool_response = await tool_manager.run_tool_async(
        tool_name=tool_name,
        session_context=None,
        session_id="",
        **tool_params,
    )
    if tool_response is not None:
        logger.info(f"执行工具成功: {tool_name}")
        return tool_response

    logger.error(f"执行工具失败: {tool_name}")
    raise SageHTTPException(
        status_code=500,
        detail="工具执行失败",
        error_detail=f"Tool '{tool_name}' execution failed",
    )


async def list_tools(
    *,
    user_id: str = "",
    role: str = "user",
    tool_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    tool_manager = get_tool_manager()
    if not tool_manager:
        return []

    available_tools = tool_manager.list_tools_with_type()
    dao = MCPServerDao()
    all_servers = await dao.get_list(user_id=None)
    source_owner_map = {server.name: server.user_id or "" for server in all_servers}

    tools: List[Dict[str, Any]] = []
    for tool_info in available_tools:
        current_tool_type = tool_info.get("type", "basic")
        source = tool_info.get("source", "internal")
        normalized_source = normalize_tool_source(source)

        if tool_type is not None and current_tool_type != tool_type:
            continue

        if role != "admin" and current_tool_type == "mcp":
            owner = source_owner_map.get(normalized_source)
            if owner is None:
                continue
            if owner and owner != user_id:
                continue

        tool_owner = (
            source_owner_map.get(normalized_source, "")
            if current_tool_type == "mcp"
            else ""
        )
        tools.append(
            {
                "name": tool_info.get("name", ""),
                "description": tool_info.get("description", ""),
                "parameters": tool_info.get("parameters", {}),
                "type": current_tool_type,
                "source": source,
                "user_id": tool_owner,
            }
        )

    return tools

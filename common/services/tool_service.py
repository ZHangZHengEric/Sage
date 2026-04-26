import json
from typing import Any, Dict, List, Optional

from loguru import logger
from sagents.tool.tool_manager import get_tool_manager

from common.core.exceptions import SageHTTPException
from common.models.mcp_server import MCPServerDao
from common.services.mcp_service import ensure_default_anytool_server
from sagents.utils.serialization import make_serializable


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


def _try_parse_json_like(value: Any) -> Any:
    current = value
    for _ in range(3):
        if isinstance(current, dict):
            content = current.get("content")
            if isinstance(content, str):
                nested = _try_parse_json_like(content)
                if nested != content:
                    return nested
            return current
        if not isinstance(current, str):
            return current

        text = current.strip()
        if not text:
            return current

        try:
            current = json.loads(text)
            continue
        except Exception:
            return current

    return current


def _format_result_text(parsed: Any, raw_text: str) -> str:
    if isinstance(parsed, (dict, list)):
        return json.dumps(parsed, ensure_ascii=False, indent=2, default=str)
    if parsed is None:
        return raw_text or ""
    if isinstance(parsed, str):
        return parsed
    return str(parsed)


def _normalize_tool_result(tool_response: Any) -> Dict[str, Any]:
    raw_text = ""
    parsed: Any = None
    if isinstance(tool_response, dict):
        raw_text = str(tool_response.get("raw_text") or "")
        parsed = tool_response.get("parsed")
        if parsed is None:
            parsed = tool_response.get("content")
        if parsed is None:
            parsed = tool_response.get("result")
        if not raw_text:
            raw_text = tool_response.get("content") if isinstance(tool_response.get("content"), str) else ""
    elif isinstance(tool_response, str):
        raw_text = tool_response
        parsed = tool_response
    else:
        parsed = tool_response

    parsed = _try_parse_json_like(parsed)
    if not raw_text:
        raw_text = _format_result_text(parsed, raw_text)
    formatted_text = _format_result_text(parsed, raw_text)

    return {
        "raw_text": raw_text,
        "parsed": make_serializable(parsed),
        "content": make_serializable(parsed),
        "formatted_text": formatted_text,
        "tool_response": make_serializable(tool_response),
    }


async def execute_tool(
    tool_name: str,
    tool_params: Dict[str, Any],
    *,
    user_id: str = "",
    role: str = "user",
) -> Any:
    logger.info(f"执行工具请求: tool={tool_name}")

    try:
        await ensure_default_anytool_server()
    except Exception as exc:
        logger.warning(f"AnyTool 预激活失败，继续执行普通工具: {exc}")
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
        session_id="",
        user_id=user_id,
        **tool_params,
    )
    if tool_response is not None:
        logger.info(f"执行工具成功: {tool_name}")
        return _normalize_tool_result(tool_response)

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
    try:
        await ensure_default_anytool_server()
    except Exception as exc:
        logger.warning(f"AnyTool 预激活失败，继续列出工具: {exc}")
    tool_manager = get_tool_manager()
    if not tool_manager:
        return []

    available_tools = tool_manager.list_tools_with_type()
    # 隐藏工具：
    # - turn_status：协议性内置工具，由 SimpleAgent 强制注入，不让用户单独勾选；
    # - await_shell / kill_shell：与 execute_shell_command 共享后台任务注册表，作为捆绑工具
    #   随 execute_shell_command 一起解锁（见 ToolProxy._TOOL_BUNDLES），不在勾选列表单独出现。
    _HIDDEN_TOOLS = {"turn_status", "await_shell", "kill_shell"}
    available_tools = [t for t in available_tools if t.get("name") not in _HIDDEN_TOOLS]
    dao = MCPServerDao()
    all_servers = await dao.get_list(user_id=None)
    source_owner_map = {server.name: server.user_id or "" for server in all_servers}
    source_kind_map = {
        server.name: (server.config or {}).get("kind", "external")
        for server in all_servers
    }

    tools: List[Dict[str, Any]] = []
    for tool_info in available_tools:
        current_tool_type = tool_info.get("type", "basic")
        source = tool_info.get("source", "internal")
        normalized_source = normalize_tool_source(source)
        server_kind = source_kind_map.get(normalized_source, "")

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
        if current_tool_type == "mcp" and server_kind == "anytool":
            source = f"内置MCP: {normalized_source}"
        tools.append(
            {
                "name": tool_info.get("name", ""),
                "description": tool_info.get("description", ""),
                "parameters": tool_info.get("parameters", {}),
                "required": tool_info.get("required", []),
                "type": current_tool_type,
                "source": source,
                "user_id": tool_owner,
                "server_kind": server_kind,
            }
        )

    return tools

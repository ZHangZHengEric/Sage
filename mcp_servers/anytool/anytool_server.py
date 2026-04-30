from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List

from mcp import types
from mcp.server import Server

from .anytool_runtime import generate_anytool_result, normalize_anytool_tools


_HIDDEN_CONTEXT_PARAM_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "session_id": {
        "type": "string",
        "description": "Hidden Sage session id. Auto-injected by the backend.",
    },
    "user_id": {
        "type": "string",
        "description": "Hidden Sage user id. Auto-injected by the backend.",
    },
}


def _ensure_object_schema(schema: Any, *, allow_any_properties: bool = False) -> Dict[str, Any]:
    if not isinstance(schema, dict) or not schema:
        return {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": allow_any_properties,
        }

    normalized = dict(schema)
    if normalized.get("type") != "object":
        normalized = {
            "type": "object",
            "properties": normalized.get("properties", {}) if isinstance(normalized.get("properties"), dict) else {},
            "required": normalized.get("required", []) if isinstance(normalized.get("required"), list) else [],
        }

    if not isinstance(normalized.get("properties"), dict):
        normalized["properties"] = {}
    if not isinstance(normalized.get("required"), list):
        normalized["required"] = []
    normalized.setdefault("additionalProperties", allow_any_properties if not normalized["properties"] else False)
    return normalized


def _ensure_anytool_input_schema(schema: Any) -> Dict[str, Any]:
    """Build the runtime AnyTool input schema with hidden Sage context fields."""
    normalized = _ensure_object_schema(deepcopy(schema), allow_any_properties=True)
    properties = normalized.setdefault("properties", {})
    for key, param_schema in _HIDDEN_CONTEXT_PARAM_SCHEMAS.items():
        properties.setdefault(key, dict(param_schema))
    return normalized


def _coerce_output_to_schema(parsed: Dict[str, Any], returns_schema: Any) -> Dict[str, Any]:
    if not isinstance(returns_schema, dict) or not returns_schema:
        return parsed
    properties = returns_schema.get("properties")
    if not isinstance(properties, dict) or not properties:
        return parsed
    allowed_keys = set(properties.keys())
    coerced: Dict[str, Any] = {key: parsed[key] for key in parsed if key in allowed_keys}
    for required_key in returns_schema.get("required", []) or []:
        if isinstance(required_key, str) and required_key not in coerced:
            coerced[required_key] = None
    return coerced


def _build_tool_schema(tool_def: Dict[str, Any]) -> types.Tool:
    returns_schema = tool_def.get("returns")
    output_schema = None
    # 只有用户显式定义了 properties 才下发 outputSchema 做严格校验；
    # 否则 MCP 默认 additionalProperties=False + properties={} 会把任何键全部拒掉
    if isinstance(returns_schema, dict) and isinstance(returns_schema.get("properties"), dict) and returns_schema["properties"]:
        output_schema = _ensure_object_schema(returns_schema, allow_any_properties=False)
    return types.Tool(
        name=str(tool_def.get("name", "")).strip(),
        title=str(tool_def.get("title", "")).strip() or None,
        description=str(tool_def.get("description", "")).strip() or None,
        inputSchema=_ensure_anytool_input_schema(tool_def.get("parameters")),
        outputSchema=output_schema,
    )


def build_anytool_server(server_name: str, server_config: Dict[str, Any]) -> Server:
    """Build an in-process MCP server for AnyTool."""

    normalized_config = dict(server_config or {})
    normalized_config["kind"] = "anytool"
    normalized_config["protocol"] = "streamable_http"
    normalized_tools = normalize_anytool_tools(normalized_config.get("tools", []))
    normalized_config["tools"] = normalized_tools
    owner_user_id = str(normalized_config.get("user_id", "") or "")

    server = Server(
        name=f"AnyTool:{server_name}",
        version="1.0.0",
        instructions="Built-in AnyTool MCP server hosted by Sage backend.",
    )

    @server.list_tools()
    async def _list_tools() -> List[types.Tool]:
        return [_build_tool_schema(tool_def) for tool_def in normalized_tools if tool_def.get("name")]

    @server.call_tool()
    async def _call_tool(tool_name: str, arguments: Dict[str, Any]) -> Any:
        tool_def = next((item for item in normalized_tools if item.get("name") == tool_name), None)
        if not tool_def:
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=f"AnyTool '{tool_name}' 不存在")],
                isError=True,
            )

        tool_arguments = dict(arguments or {})
        session_id = str(tool_arguments.pop("session_id", "") or "")
        request_user_id = str(tool_arguments.pop("user_id", "") or "")
        result = await generate_anytool_result(
            server_name=server_name,
            tool_def=tool_def,
            arguments=tool_arguments,
            server_config=normalized_config,
            user_id=request_user_id or owner_user_id,
            session_id=session_id or None,
        )
        parsed = result.get("parsed")
        if not isinstance(parsed, dict):
            parsed = {"result": parsed}
        # MCP 会用 outputSchema 校验返回；模型可能多出 message/explanation 等键，按 schema 过滤掉避免
        # "Additional properties are not allowed" 失败。schema 为空/无 properties 时原样返回。
        return _coerce_output_to_schema(parsed, tool_def.get("returns"))

    return server

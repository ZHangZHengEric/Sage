import os
from typing import Any, Dict, List, Optional

from loguru import logger
from sagents.tool.tool_manager import get_tool_manager

from common.core import config
from common.core.exceptions import SageHTTPException
from common.models.mcp_server import MCPServer, MCPServerDao
from mcp_servers.anytool.anytool_runtime import (
    generate_anytool_result,
    normalize_anytool_tools,
)

DEFAULT_ANYTOOL_SERVER_NAME = "AnyTool"


def _has_anytool_name_whitespace(name: Any) -> bool:
    return any(ch.isspace() for ch in str(name or ""))


def _get_cfg() -> config.StartupConfig:
    cfg = config.get_startup_config()
    if not cfg:
        raise RuntimeError("Startup config not initialized")
    return cfg


def _get_backend_port() -> int:
    port = os.environ.get("SAGE_PORT")
    if port:
        try:
            return int(port)
        except Exception:
            pass
    return int(_get_cfg().port)


def _build_server_config(
    protocol: str,
    server_name: str,
    streamable_http_url: Optional[str] = None,
    sse_url: Optional[str] = None,
    api_key: Optional[str] = None,
    command: Optional[str] = None,
    args: Optional[List[str]] = None,
    env: Optional[Dict[str, str]] = None,
    disabled: bool = False,
    kind: str = "external",
    tools: Optional[List[Dict[str, Any]]] = None,
    simulator: Optional[Dict[str, Any]] = None,
    description: Optional[str] = None,
) -> Dict[str, Any]:
    server_config: Dict[str, Any] = {
        "disabled": disabled,
        "kind": kind,
    }
    if description and description.strip():
        server_config["description"] = description

    if kind == "anytool":
        server_config["protocol"] = "streamable_http"
        server_config["streamable_http_url"] = (
            f"http://127.0.0.1:{_get_backend_port()}/api/mcp/anytool/{server_name}"
        )
    else:
        server_config["protocol"] = protocol
        if streamable_http_url and streamable_http_url.strip():
            server_config["streamable_http_url"] = streamable_http_url
        if sse_url and sse_url.strip():
            server_config["sse_url"] = sse_url
        if api_key and api_key.strip():
            server_config["api_key"] = api_key

        if _get_cfg().app_mode == "desktop":
            if command and command.strip():
                server_config["command"] = command
            if args:
                server_config["args"] = args
            if env:
                server_config["env"] = env

    if kind == "anytool":
        server_config["tools"] = normalize_anytool_tools(tools or [])
        if simulator:
            server_config["simulator"] = simulator

    return server_config


def _build_default_anytool_config() -> Dict[str, Any]:
    return _build_server_config(
        protocol="streamable_http",
        server_name=DEFAULT_ANYTOOL_SERVER_NAME,
        kind="anytool",
        disabled=False,
        tools=[],
        simulator={},
        description="Built-in AnyTool MCP server",
    )


def _normalize_server_config(config_data: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(config_data or {})
    normalized.setdefault("disabled", False)
    normalized.setdefault("protocol", "stdio")
    normalized.setdefault("kind", "external")
    if normalized.get("kind") == "anytool":
        normalized["protocol"] = "streamable_http"
        normalized.setdefault(
            "streamable_http_url",
            f"http://127.0.0.1:{_get_backend_port()}/api/mcp/anytool/{normalized.get('name', '')}",
        )
        normalized["tools"] = normalize_anytool_tools(normalized.get("tools", []))
        simulator = normalized.get("simulator")
        if simulator is not None and not isinstance(simulator, dict):
            normalized["simulator"] = {}
    return normalized


def _build_runtime_server_config(server_config: Dict[str, Any], user_id: Optional[str]) -> Dict[str, Any]:
    runtime_config = _normalize_server_config(server_config)
    if user_id is not None:
        runtime_config["user_id"] = user_id
    return runtime_config


async def ensure_default_anytool_server(
    *,
    register_tool_manager: bool = True,
) -> Optional[MCPServer]:
    dao = MCPServerDao()
    existing_server = await dao.get_by_name(DEFAULT_ANYTOOL_SERVER_NAME)
    if existing_server:
        existing_config = _normalize_server_config(existing_server.config or {})
        if existing_config.get("kind") != "anytool":
            normalized = dict(existing_config)
            normalized["kind"] = "anytool"
            normalized["protocol"] = "streamable_http"
            normalized["streamable_http_url"] = (
                f"http://127.0.0.1:{_get_backend_port()}/api/mcp/anytool/{DEFAULT_ANYTOOL_SERVER_NAME}"
            )
            await dao.save_mcp_server(
                name=DEFAULT_ANYTOOL_SERVER_NAME,
                config=normalized,
                user_id=existing_server.user_id,
            )
            existing_server = await dao.get_by_name(DEFAULT_ANYTOOL_SERVER_NAME)
            existing_config = _normalize_server_config(existing_server.config or {})
        if register_tool_manager and existing_config.get("kind") == "anytool":
            try:
                runtime_config = _build_runtime_server_config(existing_config, existing_server.user_id)
                tm = get_tool_manager()
                await tm.register_mcp_server(DEFAULT_ANYTOOL_SERVER_NAME, runtime_config)
            except Exception as exc:
                logger.warning(f"默认 AnyTool MCP server 激活失败: {exc}")
        return existing_server

    server_config = _build_default_anytool_config()
    runtime_config = _build_runtime_server_config(server_config, "")
    if register_tool_manager:
        tm = get_tool_manager()
        success = await tm.register_mcp_server(DEFAULT_ANYTOOL_SERVER_NAME, runtime_config)
        if not success:
            logger.warning("默认 AnyTool MCP server 注册失败")
            return await dao.save_mcp_server(
                name=DEFAULT_ANYTOOL_SERVER_NAME,
                config=server_config,
                user_id="",
            )

    return await dao.save_mcp_server(
        name=DEFAULT_ANYTOOL_SERVER_NAME,
        config=server_config,
        user_id="",
    )


async def add_mcp_server(
    name: str,
    protocol: str,
    streamable_http_url: Optional[str] = None,
    sse_url: Optional[str] = None,
    api_key: Optional[str] = None,
    command: Optional[str] = None,
    args: Optional[List[str]] = None,
    env: Optional[Dict[str, str]] = None,
    disabled: bool = False,
    kind: str = "external",
    tools: Optional[List[Dict[str, Any]]] = None,
    simulator: Optional[Dict[str, Any]] = None,
    description: Optional[str] = None,
    user_id: Optional[str] = None,
) -> str:
    dao = MCPServerDao()
    target_name = DEFAULT_ANYTOOL_SERVER_NAME if kind == "anytool" else name.strip()
    existing_server = await dao.get_by_name(target_name)
    if existing_server and kind != "anytool":
        raise SageHTTPException(
            status_code=500 if _get_cfg().app_mode == "desktop" else 400,
            detail=f"MCP服务器 '{target_name}' 已存在",
            error_detail="MCP服务器名称已存在",
        )
    if existing_server and kind == "anytool" and (existing_server.config or {}).get("kind") != "anytool":
        raise SageHTTPException(
            status_code=400,
            detail=f"MCP服务器 '{target_name}' 已被其他类型占用",
            error_detail="MCP server name conflict",
        )

    server_config = _build_server_config(
        protocol=protocol,
        server_name=target_name,
        streamable_http_url=streamable_http_url,
        sse_url=sse_url,
        api_key=api_key,
        command=command,
        args=args,
        env=env,
        disabled=disabled,
        kind=kind,
        tools=tools,
        simulator=simulator,
        description=description,
    )

    tm = get_tool_manager()
    runtime_config = _build_runtime_server_config(server_config, user_id)
    success = await tm.register_mcp_server(target_name, runtime_config)
    if not success:
        raise SageHTTPException(
            status_code=500,
            detail=f"MCP server {target_name} 注册失败",
            error_detail="Tool manager registration failed",
        )

    await dao.save_mcp_server(name=target_name, config=server_config, user_id=user_id)
    return target_name


async def update_mcp_server(
    server_name: str,
    name: str,
    protocol: str,
    streamable_http_url: Optional[str] = None,
    sse_url: Optional[str] = None,
    api_key: Optional[str] = None,
    command: Optional[str] = None,
    args: Optional[List[str]] = None,
    env: Optional[Dict[str, str]] = None,
    disabled: bool = False,
    kind: str = "external",
    tools: Optional[List[Dict[str, Any]]] = None,
    simulator: Optional[Dict[str, Any]] = None,
    description: Optional[str] = None,
    user_id: Optional[str] = None,
    role: str = "user",
) -> str:
    dao = MCPServerDao()
    existing_server = await dao.get_by_name(server_name)
    if not existing_server:
        raise SageHTTPException(
            status_code=500 if _get_cfg().app_mode == "desktop" else 400,
            detail=f"MCP服务器 '{server_name}' 不存在",
            error_detail="MCP服务器不存在",
        )

    if (
        _get_cfg().app_mode == "server"
        and role != "admin"
        and existing_server.user_id != (user_id or "")
    ):
        raise SageHTTPException(
            detail="无权修改该MCP服务器",
            error_detail="Permission denied",
        )

    target_name = server_name.strip()
    requested_name = (name or server_name).strip()
    if kind == "anytool" and requested_name not in {target_name, DEFAULT_ANYTOOL_SERVER_NAME}:
        raise SageHTTPException(
            status_code=400,
            detail="AnyTool 不支持重命名",
            error_detail="AnyTool server name is fixed",
        )
    if target_name != server_name:
        duplicate = await dao.get_by_name(target_name)
        if duplicate:
            raise SageHTTPException(
                detail=f"MCP服务器 '{target_name}' 已存在",
                error_detail="MCP服务器名称已存在",
            )

    server_config = _build_server_config(
        protocol=protocol,
        server_name=target_name,
        streamable_http_url=streamable_http_url,
        sse_url=sse_url,
        api_key=api_key,
        command=command,
        args=args,
        env=env,
        disabled=disabled,
        kind=kind,
        tools=tools,
        simulator=simulator,
        description=description,
    )

    tm = get_tool_manager()
    old_config = dict(existing_server.config or {})
    try:
        await tm.remove_tool_by_mcp(server_name)
        runtime_config = _build_runtime_server_config(server_config, user_id)
        success = await tm.register_mcp_server(target_name, runtime_config)
        if not success and not server_config.get("disabled", False):
            raise SageHTTPException(
                status_code=500,
                detail=f"MCP server {target_name} 更新失败",
                error_detail="Tool manager registration failed",
            )

        await dao.save_mcp_server(name=target_name, config=server_config, user_id=user_id)
        if target_name != server_name:
            await dao.delete_by_name(server_name)
        return target_name
    except Exception:
        if old_config and not old_config.get("disabled", False):
            try:
                await tm.register_mcp_server(server_name, _build_runtime_server_config(old_config, existing_server.user_id))
            except Exception as restore_error:
                logger.error(f"回滚旧 MCP server 失败: {server_name}, {restore_error}")
        raise


async def list_mcp_servers(user_id: Optional[str] = None) -> List[MCPServer]:
    await ensure_default_anytool_server()
    dao = MCPServerDao()
    return await dao.get_list(user_id)


def serialize_mcp_server(server: MCPServer) -> Dict[str, Any]:
    config = _normalize_server_config(server.config or {})
    return {
        "name": server.name,
        "protocol": config.get("protocol"),
        "kind": config.get("kind", "external"),
        "disabled": config.get("disabled", False),
        "streamable_http_url": config.get("streamable_http_url"),
        "sse_url": config.get("sse_url"),
        "api_key": config.get("api_key"),
        "command": config.get("command"),
        "args": config.get("args"),
        "env": config.get("env"),
        "tools": config.get("tools", []),
        "simulator": config.get("simulator", {}),
        "description": config.get("description", ""),
        "user_id": server.user_id,
    }


async def remove_mcp_server(
    server_name: str,
    user_id: Optional[str] = None,
    role: str = "user",
) -> str:
    tm = get_tool_manager()
    dao = MCPServerDao()
    existing_server = await dao.get_by_name(server_name)
    if not existing_server:
        raise SageHTTPException(
            status_code=500 if _get_cfg().app_mode == "desktop" else 400,
            detail=f"MCP服务器 '{server_name}' 不存在",
            error_detail=f"MCP服务器 '{server_name}' 不存在",
        )

    if (
        _get_cfg().app_mode == "server"
        and role != "admin"
        and existing_server.user_id != (user_id or "")
    ):
        raise SageHTTPException(
            detail="无权删除该MCP服务器",
            error_detail="Permission denied",
        )

    if (existing_server.config or {}).get("kind") == "anytool":
        raise SageHTTPException(
            status_code=403,
            detail="AnyTool 只能关闭，不能删除",
            error_detail="AnyTool server cannot be deleted",
        )

    success = await tm.remove_tool_by_mcp(server_name)
    if not success:
        raise SageHTTPException(
            status_code=500,
            detail=f"MCP服务器 '{server_name}' 删除失败",
            error_detail="工具管理器移除失败",
        )

    await dao.delete_by_name(server_name)
    logger.info(f"MCP server {server_name} 删除成功")
    return server_name


async def preview_mcp_server(
    server_name: str,
    tool_name: str,
    arguments: Dict[str, Any],
    user_id: Optional[str] = None,
    role: str = "user",
) -> Dict[str, Any]:
    dao = MCPServerDao()
    existing_server = await dao.get_by_name(server_name)
    if not existing_server:
        raise SageHTTPException(
            status_code=500 if _get_cfg().app_mode == "desktop" else 400,
            detail=f"MCP服务器 '{server_name}' 不存在",
            error_detail=f"MCP服务器 '{server_name}' 不存在",
        )

    if (
        _get_cfg().app_mode == "server"
        and role != "admin"
        and existing_server.user_id != (user_id or "")
    ):
        raise SageHTTPException(
            detail="无权使用该MCP服务器",
            error_detail="Permission denied",
        )

    server_config = _normalize_server_config(existing_server.config or {})
    if server_config.get("kind") != "anytool":
        raise SageHTTPException(
            status_code=400,
            detail="仅 AnyTool 支持预览执行",
            error_detail="preview only available for anytool servers",
        )

    tools = server_config.get("tools", [])
    tool_def = next((item for item in tools if item.get("name") == tool_name), None)
    if not tool_def:
        raise SageHTTPException(
            status_code=404,
            detail=f"AnyTool '{tool_name}' 不存在",
            error_detail="tool definition not found",
        )

    return await generate_anytool_result(
        server_name=server_name,
        tool_def=tool_def,
        arguments=arguments,
        server_config=server_config,
        user_id=user_id,
        prefer_first_provider=True,
    )


async def preview_anytool_draft(
    *,
    tool_definition: Dict[str, Any],
    arguments: Dict[str, Any],
    simulator: Optional[Dict[str, Any]] = None,
    server_name: str = "draft",
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    tool_name = str((tool_definition or {}).get("name", "")).strip()
    if not tool_name or _has_anytool_name_whitespace(tool_name):
        raise SageHTTPException(
            status_code=400,
            detail="AnyTool 名称不能为空且不能包含空格",
            error_detail="AnyTool tool name cannot contain whitespace",
        )
    tool_list = normalize_anytool_tools([tool_definition])
    if not tool_list:
        raise SageHTTPException(
            status_code=400,
            detail="tool_definition 无效",
            error_detail="invalid AnyTool definition",
        )

    server_config: Dict[str, Any] = {
        "kind": "anytool",
        "protocol": "streamable_http",
        "tools": tool_list,
    }
    if isinstance(simulator, dict):
        server_config["simulator"] = simulator

    return await generate_anytool_result(
        server_name=server_name or "draft",
        tool_def=tool_list[0],
        arguments=arguments,
        server_config=server_config,
        user_id=user_id,
        prefer_first_provider=True,
    )


async def upsert_anytool_tool(
    *,
    tool_definition: Dict[str, Any],
    original_name: Optional[str] = None,
    server_name: str = DEFAULT_ANYTOOL_SERVER_NAME,
    user_id: Optional[str] = None,
    role: str = "user",
) -> Dict[str, Any]:
    dao = MCPServerDao()
    existing_server = await dao.get_by_name(server_name)
    if not existing_server:
        existing_server = await ensure_default_anytool_server(register_tool_manager=False)
    if not existing_server:
        raise SageHTTPException(
            status_code=500,
            detail="AnyTool server 不存在",
            error_detail="AnyTool server not found",
        )

    if (
        _get_cfg().app_mode == "server"
        and role != "admin"
        and existing_server.user_id not in {"", user_id or ""}
    ):
        raise SageHTTPException(
            detail="无权修改该 AnyTool",
            error_detail="Permission denied",
        )

    server_config = _normalize_server_config(existing_server.config or {})
    if server_config.get("kind") != "anytool":
        raise SageHTTPException(
            status_code=400,
            detail="仅 AnyTool 支持工具编辑",
            error_detail="upsert only available for anytool servers",
        )

    normalized_tool_list = normalize_anytool_tools([tool_definition])
    if not normalized_tool_list:
        raise SageHTTPException(
            status_code=400,
            detail="tool_definition 无效",
            error_detail="invalid AnyTool definition",
        )
    next_tool = normalized_tool_list[0]
    if _has_anytool_name_whitespace(next_tool.get("name")):
        raise SageHTTPException(
            status_code=400,
            detail="AnyTool 名称不能包含空格",
            error_detail="AnyTool tool name cannot contain whitespace",
        )

    current_tools = normalize_anytool_tools(server_config.get("tools", []))
    keep_tools: List[Dict[str, Any]] = []
    original_name = (original_name or "").strip()
    next_name = next_tool.get("name", "").strip()

    for tool in current_tools:
        tool_name = str(tool.get("name", "")).strip()
        if original_name and tool_name == original_name:
            continue
        if not original_name and tool_name == next_name:
            raise SageHTTPException(
                status_code=400,
                detail=f"AnyTool '{next_name}' 已存在",
                error_detail="tool definition already exists",
            )
        keep_tools.append(tool)

    if original_name and original_name != next_name:
        duplicate = next((item for item in keep_tools if item.get("name") == next_name), None)
        if duplicate:
            raise SageHTTPException(
                status_code=400,
                detail=f"AnyTool '{next_name}' 已存在",
                error_detail="tool definition already exists",
            )

    keep_tools.append(next_tool)
    updated_tools = normalize_anytool_tools(keep_tools)

    await update_mcp_server(
        server_name=server_name,
        name=server_name,
        protocol=server_config.get("protocol", "streamable_http"),
        kind="anytool",
        streamable_http_url=server_config.get("streamable_http_url"),
        sse_url=server_config.get("sse_url"),
        api_key=server_config.get("api_key"),
        command=server_config.get("command"),
        args=server_config.get("args"),
        env=server_config.get("env"),
        disabled=server_config.get("disabled", False),
        tools=updated_tools,
        simulator=server_config.get("simulator", {}),
        description=server_config.get("description", "Built-in AnyTool MCP server"),
        user_id=existing_server.user_id,
        role=role,
    )

    # 同 delete：DB 写入后再强制重注册一次，避免首次 list 拿到旧工具
    try:
        tm = get_tool_manager()
        await tm.remove_tool_by_mcp(server_name)
        latest = await dao.get_by_name(server_name)
        if latest:
            runtime_config = _build_runtime_server_config(
                _normalize_server_config(latest.config or {}),
                latest.user_id,
            )
            if not runtime_config.get("disabled", False):
                await tm.register_mcp_server(server_name, runtime_config)
    except Exception as exc:
        logger.warning(f"[AnyTool] post-upsert refresh failed: {exc}")

    return {
        "server_name": server_name,
        "tool_name": next_name,
        "original_name": original_name or next_name,
    }


async def delete_anytool_tool(
    *,
    tool_name: str,
    server_name: str = DEFAULT_ANYTOOL_SERVER_NAME,
    user_id: Optional[str] = None,
    role: str = "user",
) -> Dict[str, Any]:
    target = (tool_name or "").strip()
    if not target:
        raise SageHTTPException(
            status_code=400,
            detail="tool_name 必填",
            error_detail="tool_name is required",
        )

    dao = MCPServerDao()
    existing_server = await dao.get_by_name(server_name)
    if not existing_server:
        raise SageHTTPException(
            status_code=404,
            detail="AnyTool server 不存在",
            error_detail="AnyTool server not found",
        )

    if (
        _get_cfg().app_mode == "server"
        and role != "admin"
        and existing_server.user_id not in {"", user_id or ""}
    ):
        raise SageHTTPException(
            detail="无权修改该 AnyTool",
            error_detail="Permission denied",
        )

    server_config = _normalize_server_config(existing_server.config or {})
    if server_config.get("kind") != "anytool":
        raise SageHTTPException(
            status_code=400,
            detail="仅 AnyTool 支持工具删除",
            error_detail="delete only available for anytool servers",
        )

    current_tools = normalize_anytool_tools(server_config.get("tools", []))
    keep_tools = [t for t in current_tools if str(t.get("name", "")).strip() != target]
    if len(keep_tools) == len(current_tools):
        raise SageHTTPException(
            status_code=404,
            detail=f"AnyTool '{target}' 不存在",
            error_detail="tool definition not found",
        )

    await update_mcp_server(
        server_name=server_name,
        name=server_name,
        protocol=server_config.get("protocol", "streamable_http"),
        kind="anytool",
        streamable_http_url=server_config.get("streamable_http_url"),
        sse_url=server_config.get("sse_url"),
        api_key=server_config.get("api_key"),
        command=server_config.get("command"),
        args=server_config.get("args"),
        env=server_config.get("env"),
        disabled=server_config.get("disabled", False),
        tools=keep_tools,
        simulator=server_config.get("simulator", {}),
        description=server_config.get("description", "Built-in AnyTool MCP server"),
        user_id=existing_server.user_id,
        role=role,
    )

    # update_mcp_server 内部 register → save 顺序导致首次注册时 AnyTool HTTP 仍读到旧 DB 工具，
    # 这里在 DB 已写入后再强制清理并重注册一次，确保 tool_manager 立即反映最新工具列表
    try:
        tm = get_tool_manager()
        await tm.remove_tool_by_mcp(server_name)
        latest = await dao.get_by_name(server_name)
        if latest:
            runtime_config = _build_runtime_server_config(
                _normalize_server_config(latest.config or {}),
                latest.user_id,
            )
            if not runtime_config.get("disabled", False):
                await tm.register_mcp_server(server_name, runtime_config)
    except Exception as exc:
        logger.warning(f"[AnyTool] post-delete refresh failed: {exc}")

    return {"server_name": server_name, "tool_name": target}


async def reload_all_mcp_tools() -> None:
    tm = get_tool_manager()
    dao = MCPServerDao()
    await tm.clear_mcp_tools()

    all_servers = await dao.get_list()
    enabled_servers = [server for server in all_servers if not (server.config or {}).get("disabled", False)]
    for server in enabled_servers:
        if (server.config or {}).get("kind") == "anytool":
            logger.info(f"[MCP Reload] 跳过内置 AnyTool 的常规注册: {server.name}")
            continue
        try:
            success = await tm.register_mcp_server(server.name, _build_runtime_server_config(server.config or {}, server.user_id))
            if success:
                logger.info(f"[MCP Reload] 成功注册 MCP Server: {server.name}")
            else:
                logger.warning(f"[MCP Reload] 注册 MCP Server 失败: {server.name}")
        except Exception as e:
            logger.error(f"[MCP Reload] 注册 MCP Server 异常: {server.name}, {e}")

    try:
        await ensure_default_anytool_server(register_tool_manager=True)
    except Exception as e:
        logger.warning(f"[MCP Reload] 恢复内置 AnyTool 失败: {e}")


async def toggle_mcp_server(server_name: str, user_id: Optional[str] = None) -> tuple[bool, str]:
    dao = MCPServerDao()
    existing_server = await dao.get_by_name(server_name)
    if not existing_server:
        raise SageHTTPException(
            status_code=500 if _get_cfg().app_mode == "desktop" else 400,
            detail=f"MCP服务器 '{server_name}' 不存在",
            error_detail=f"MCP服务器 '{server_name}' 不存在",
        )

    tm = get_tool_manager()
    server_config = existing_server.config
    new_disabled = not server_config.get("disabled", False)
    server_config["disabled"] = new_disabled
    await dao.save_mcp_server(server_name, server_config, user_id=user_id)

    if _get_cfg().app_mode == "desktop":
        await reload_all_mcp_tools()
    else:
        if new_disabled:
            await tm.remove_tool_by_mcp(server_name)
        else:
            success = await tm.register_mcp_server(server_name, _build_runtime_server_config(server_config, existing_server.user_id))
            if not success:
                raise SageHTTPException(
                    detail=f"MCP服务器 '{server_name}' 启用失败",
                    error_detail="工具管理器注册失败",
                )

    return new_disabled, "禁用" if new_disabled else "启用"


async def refresh_mcp_server(
    server_name: str,
    user_id: Optional[str] = None,
    role: str = "user",
) -> str:
    tm = get_tool_manager()
    dao = MCPServerDao()
    existing_server = await dao.get_by_name(server_name)
    if not existing_server:
        raise SageHTTPException(
            status_code=500 if _get_cfg().app_mode == "desktop" else 400,
            detail=f"MCP服务器 '{server_name}' 不存在",
            error_detail=f"MCP服务器 '{server_name}' 不存在",
        )

    if (
        _get_cfg().app_mode == "server"
        and role != "admin"
        and existing_server.user_id != (user_id or "")
    ):
        raise SageHTTPException(
            detail="无权操作该MCP服务器",
            error_detail="Permission denied",
        )

    await tm.remove_tool_by_mcp(server_name)
    server_config = existing_server.config
    server_config["disabled"] = False
    success = await tm.register_mcp_server(server_name, _build_runtime_server_config(server_config, existing_server.user_id))
    if success:
        logger.info(f"MCP server {server_name} 刷新成功")
        server_config["disabled"] = False
        await dao.save_mcp_server(name=server_name, config=server_config)
        return "refreshed"

    logger.warning(f"MCP server {server_name} 刷新失败，将其设置为禁用状态")
    server_config["disabled"] = True
    await dao.save_mcp_server(name=server_name, config=server_config)
    return "disabled"

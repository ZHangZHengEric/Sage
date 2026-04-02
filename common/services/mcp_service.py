from typing import Any, Dict, List, Optional

from loguru import logger
from sagents.tool.tool_manager import get_tool_manager

from common.core import config
from common.core.exceptions import SageHTTPException
from common.models.mcp_server import MCPServer, MCPServerDao


def _get_cfg() -> config.StartupConfig:
    cfg = config.get_startup_config()
    if not cfg:
        raise RuntimeError("Startup config not initialized")
    return cfg


def _build_server_config(
    protocol: str,
    streamable_http_url: Optional[str] = None,
    sse_url: Optional[str] = None,
    api_key: Optional[str] = None,
    command: Optional[str] = None,
    args: Optional[List[str]] = None,
    env: Optional[Dict[str, str]] = None,
    disabled: bool = False,
) -> Dict[str, Any]:
    server_config: Dict[str, Any] = {
        "disabled": disabled,
        "protocol": protocol,
    }
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

    return server_config


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
    user_id: Optional[str] = None,
) -> str:
    dao = MCPServerDao()
    existing_server = await dao.get_by_name(name)
    if existing_server:
        raise SageHTTPException(
            status_code=500 if _get_cfg().app_mode == "desktop" else 400,
            detail=f"MCP服务器 '{name}' 已存在",
            error_detail="MCP服务器名称已存在",
        )

    server_config = _build_server_config(
        protocol=protocol,
        streamable_http_url=streamable_http_url,
        sse_url=sse_url,
        api_key=api_key,
        command=command,
        args=args,
        env=env,
        disabled=disabled,
    )

    tm = get_tool_manager()
    success = await tm.register_mcp_server(name, server_config)
    if not success:
        raise SageHTTPException(
            status_code=500,
            detail=f"MCP server {name} 注册失败",
            error_detail="Tool manager registration failed",
        )

    await dao.save_mcp_server(name=name, config=server_config, user_id=user_id)
    return name


async def list_mcp_servers(user_id: Optional[str] = None) -> List[MCPServer]:
    dao = MCPServerDao()
    return await dao.get_list(user_id if _get_cfg().app_mode == "server" else None)


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


async def reload_all_mcp_tools() -> None:
    tm = get_tool_manager()
    dao = MCPServerDao()
    await tm.clear_mcp_tools()

    all_servers = await dao.get_list()
    enabled_servers = [server for server in all_servers if not server.config.get("disabled", False)]
    for server in enabled_servers:
        try:
            success = await tm.register_mcp_server(server.name, server.config)
            if success:
                logger.info(f"[MCP Reload] 成功注册 MCP Server: {server.name}")
            else:
                logger.warning(f"[MCP Reload] 注册 MCP Server 失败: {server.name}")
        except Exception as e:
            logger.error(f"[MCP Reload] 注册 MCP Server 异常: {server.name}, {e}")


async def toggle_mcp_server(server_name: str) -> tuple[bool, str]:
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
    await dao.save_mcp_server(server_name, server_config)

    if _get_cfg().app_mode == "desktop":
        await reload_all_mcp_tools()
    else:
        if new_disabled:
            tm.remove_tool_by_mcp(server_name)
        else:
            success = await tm.register_mcp_server(server_name, server_config)
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
    success = await tm.register_mcp_server(server_name, server_config)
    if success:
        logger.info(f"MCP server {server_name} 刷新成功")
        server_config["disabled"] = False
        await dao.save_mcp_server(name=server_name, config=server_config)
        return "refreshed"

    logger.warning(f"MCP server {server_name} 刷新失败，将其设置为禁用状态")
    server_config["disabled"] = True
    await dao.save_mcp_server(name=server_name, config=server_config)
    return "disabled"

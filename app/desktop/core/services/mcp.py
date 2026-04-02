"""
MCP 业务处理模块

封装 MCP 相关的业务逻辑，供路由层调用。
"""

from typing import Any, Dict, List, Optional

from loguru import logger
from sagents.tool.tool_manager import get_tool_manager

from common.core.exceptions import SageHTTPException
from common.models.mcp_server import MCPServer, MCPServerDao


def _build_server_config(
    name: str,
    protocol: str,
    streamable_http_url: str,
    sse_url: str,
    api_key: str,
    command: str,
    args: List[str],
    env: Dict[str, str],
    disabled: bool = False,
) -> Dict[str, Any]:
    """从请求构建服务器配置字典，去除空值"""
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
    streamable_http_url: str,
    sse_url: str,
    api_key: str,
    command: str,
    args: List[str],
    env: Dict[str, str],
    disabled: bool = False,
) -> str:
    """添加 MCP 服务器并保存到数据库，返回响应数据字典"""

    logger.info(f"[MCP Add] Starting to add MCP server: {name}")
    logger.info(f"[MCP Add] Protocol: {protocol}")
    logger.debug(f"[MCP Add] command: {command}, args: {args}, env: {env}")
    logger.debug(f"[MCP Add] streamable_http_url: {streamable_http_url}, sse_url: {sse_url}")

    dao = MCPServerDao()
    # 检查服务器名称是否已存在
    existing_server = await dao.get_by_name(name)
    if existing_server:
        logger.warning(f"[MCP Add] Server '{name}' already exists")
        raise SageHTTPException(
            status_code=500,
            detail=f"MCP服务器 '{name}' 已存在",
            error_detail="MCP服务器名称已存在",
        )
    # 注册到全局工具管理器
    server_config = _build_server_config(
        name, protocol, streamable_http_url, sse_url, api_key, command, args, env, disabled
    )
    logger.info(f"[MCP Add] Built server_config: {server_config}")

    tm = get_tool_manager()
    logger.info(f"[MCP Add] Calling tool_manager.register_mcp_server for {name}")
    success = await tm.register_mcp_server(name, server_config)
    logger.info(f"[MCP Add] tool_manager.register_mcp_server returned: {success}")

    if not success:
        logger.error(f"[MCP Add] Failed to register MCP server {name} in tool_manager")
        raise SageHTTPException(
            status_code=500,
            detail=f"MCP server {name} 注册失败",
            error_detail="Tool manager registration failed",
        )
    # 保存到数据库
    logger.info(f"[MCP Add] Saving MCP server {name} to database")
    await dao.save_mcp_server(name=name, config=server_config)
    logger.info(f"[MCP Add] Successfully added MCP server: {name}")
    return name


async def list_mcp_servers() -> List[MCPServer]:
    """获取所有 MCP 服务器并转换为简化响应结构"""
    dao = MCPServerDao()
    mcp_servers = await dao.get_list()
    return mcp_servers


async def remove_mcp_server(server_name: str) -> str:
    """删除 MCP 服务器，返回 server_name"""
    tm = get_tool_manager()

    dao = MCPServerDao()
    existing_server = await dao.get_by_name(server_name)
    if not existing_server:
        raise SageHTTPException(
            status_code=500,
            detail=f"MCP服务器 '{server_name}' 不存在",
            error_detail=f"MCP服务器 '{server_name}' 不存在",
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


async def toggle_mcp_server(server_name: str) -> (bool, str):
    """切换 MCP 服务器启用/禁用状态，返回 (disabled, status_text)"""
    dao = MCPServerDao()
    existing_server = await dao.get_by_name(server_name)
    if not existing_server:
        raise SageHTTPException(
            status_code=500,
            detail=f"MCP服务器 '{server_name}' 不存在",
            error_detail=f"MCP服务器 '{server_name}' 不存在",
        )

    server_config = existing_server.config
    new_disabled = not server_config.get("disabled", False)
    server_config["disabled"] = new_disabled

    await dao.save_mcp_server(server_name, server_config)

    # 重新初始化所有 MCP 工具（根据最新配置）
    await reload_all_mcp_tools()

    status_text = "禁用" if new_disabled else "启用"
    return new_disabled, status_text


async def reload_all_mcp_tools():
    """重新加载所有启用的 MCP 工具"""
    tm = get_tool_manager()
    dao = MCPServerDao()

    # 1. 清除所有 MCP 工具
    await tm.clear_mcp_tools()

    # 2. 从数据库获取所有启用的 MCP Server
    all_servers = await dao.get_list()
    enabled_servers = [s for s in all_servers if not s.config.get("disabled", False)]

    # 3. 重新注册所有启用的 MCP Server
    for server in enabled_servers:
        try:
            success = await tm.register_mcp_server(server.name, server.config)
            if success:
                logger.info(f"[MCP Reload] 成功注册 MCP Server: {server.name}")
            else:
                logger.warning(f"[MCP Reload] 注册 MCP Server 失败: {server.name}")
        except Exception as e:
            logger.error(f"[MCP Reload] 注册 MCP Server 异常: {server.name}, {e}")


async def refresh_mcp_server(server_name: str) -> str:
    """刷新 MCP 服务器连接，返回是否成功"""
    tm = get_tool_manager()
    dao = MCPServerDao()
    existing_server = await dao.get_by_name(server_name)
    if not existing_server:
        raise SageHTTPException(
            status_code=500,
            detail=f"MCP服务器 '{server_name}' 不存在",
            error_detail=f"MCP服务器 '{server_name}' 不存在",
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

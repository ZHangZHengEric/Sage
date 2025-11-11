"""
MCP 业务处理模块

封装 MCP 相关的业务逻辑，供路由层调用。
"""

from typing import Dict, Any, List

from sagents.utils.logger import logger
import core.globals as global_vars
from common.exceptions import SageHTTPException
from models.mcp_server import MCPServerDao, MCPServer


def _build_server_config(
    name: str,
    protocol: str,
    streamable_http_url: str,
    sse_url: str,
    api_key: str,
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
    return server_config


async def add_mcp_server(
    name: str,
    protocol: str,
    streamable_http_url: str,
    sse_url: str,
    api_key: str,
    disabled: bool = False,
) -> str:
    """添加 MCP 服务器并保存到数据库，返回响应数据字典"""
    logger.info(f"开始添加MCP server: {name}")

    dao = await MCPServerDao.create()
    # 检查服务器名称是否已存在
    existing_server = await dao.get_by_name(name)
    if existing_server:
        raise SageHTTPException(
            status_code=500,
            detail=f"MCP服务器 '{name}' 已存在",
            error_detail="MCP服务器名称已存在",
        )
    # 注册到全局工具管理器
    tm = global_vars.get_tool_manager()
    server_config = _build_server_config(
        name, protocol, streamable_http_url, sse_url, api_key, disabled
    )
    success = await tm.register_mcp_server(name, server_config)
    if not success:
        raise SageHTTPException(
            status_code=500,
            detail=f"MCP server {name} 注册失败",
            error_detail="Tool manager registration failed",
        )
    # 保存到数据库
    await dao.save_mcp_server(name=name, config=server_config)
    return name


async def list_mcp_servers() -> List[MCPServer]:
    """获取所有 MCP 服务器并转换为简化响应结构"""
    logger.info("获取MCP服务器列表")
    dao = await MCPServerDao.create()
    mcp_servers = await dao.get_all()
    return mcp_servers


async def remove_mcp_server(server_name: str) -> str:
    """删除 MCP 服务器，返回 server_name"""
    logger.info(f"开始删除MCP server: {server_name}")
    tm = global_vars.get_tool_manager()

    dao = await MCPServerDao.create()
    existing_server = await dao.get_by_name(server_name)
    if not existing_server:
        raise SageHTTPException(
            status_code=404,
            detail=f"MCP服务器 '{server_name}' 不存在",
            error_detail=f"MCP服务器 '{server_name}' 不存在",
        )

    success = tm.remove_mcp_server(server_name)
    if not success:
        raise SageHTTPException(
            status_code=400,
            detail=f"MCP服务器 '{server_name}' 删除失败",
            error_detail="工具管理器移除失败",
        )

    await dao.delete_by_name(server_name)
    logger.info(f"MCP server {server_name} 删除成功")
    return server_name


async def toggle_mcp_server(server_name: str) -> (bool, str):
    """切换 MCP 服务器启用/禁用状态，返回 (disabled, status_text)"""
    logger.info(f"开始切换MCP server状态: {server_name}")
    tm = global_vars.get_tool_manager()

    dao = await MCPServerDao.create()
    existing_server = await dao.get_by_name(server_name)
    if not existing_server:
        raise SageHTTPException(
            status_code=404,
            detail=f"MCP服务器 '{server_name}' 不存在",
            error_detail=f"MCP服务器 '{server_name}' 不存在",
        )

    server_config = existing_server.config
    new_disabled = not server_config.get("disabled", False)
    server_config["disabled"] = new_disabled

    await dao.save_mcp_server(server_name, server_config)

    if new_disabled:
        tm.remove_tool_by_mcp(server_name)
        status_text = "禁用"
    else:
        success = await tm.register_mcp_server(server_name, server_config)
        if not success:
            raise SageHTTPException(
                status_code=400,
                detail=f"MCP服务器 '{server_name}' 启用失败",
                error_detail="工具管理器注册失败",
            )
        status_text = "启用"
    return new_disabled, status_text


async def refresh_mcp_server(server_name: str) -> str:
    """刷新 MCP 服务器连接，返回是否成功"""
    logger.info(f"开始刷新MCP server: {server_name}")
    tm = global_vars.get_tool_manager()

    dao = await MCPServerDao.create()
    existing_server = await dao.get_by_name(server_name)
    if not existing_server:
        raise SageHTTPException(
            status_code=404,
            detail=f"MCP服务器 '{server_name}' 不存在",
            error_detail=f"MCP服务器 '{server_name}' 不存在",
        )

    server_config = existing_server.config
    if server_config.get("disabled", False):
        raise SageHTTPException(
            status_code=400,
            detail=f"MCP服务器 '{server_name}' 已被禁用，无法刷新",
            error_detail="禁用的服务器无法刷新",
        )

    success = await tm.register_mcp_server(server_name, server_config)
    if success:
        logger.info(f"MCP server {server_name} 刷新成功")
        return "refreshed"
    logger.warning(f"MCP server {server_name} 刷新失败，将其设置为禁用状态")
    server_config["disabled"] = True
    await dao.save_mcp_server(name=server_name, config=server_config)
    return "disabled"


async def validate_and_disable_mcp_servers():
    """验证数据库中的 MCP 服务器配置并注册到 ToolManager；清理不可用项。

    - 对每个保存的 MCP 服务器尝试注册；
    - 若注册抛出异常或失败，则从数据库中删除该服务器；
    - 若之前有部分注册的工具，尝试从 ToolManager 中移除。
    """
    mcp_dao = await MCPServerDao.create()
    servers = await mcp_dao.get_all()
    removed_count = 0
    registered_count = 0
    for srv in servers:
        status = await refresh_mcp_server(srv.name)
        if status == "disabled":
            removed_count += 1
        else:
            registered_count += 1
    logger.info(
        f"MCP 验证完成：成功 {registered_count} 个，禁用 {removed_count} 个不可用服务器"
    )

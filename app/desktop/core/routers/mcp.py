"""
MCP (Model Context Protocol) 相关路由

提供MCP服务器的管理接口，包括添加、删除、配置等功能
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request
from loguru import logger
from pydantic import BaseModel

from common.core.render import Response
from ..services.mcp import (
    add_mcp_server,
    list_mcp_servers,
    refresh_mcp_server,
    remove_mcp_server,
    toggle_mcp_server,
)

# 创建路由器
mcp_router = APIRouter(prefix="/api/mcp", tags=["MCP"])


class MCPServerRequest(BaseModel):
    name: str
    protocol: str  # 协议类型：streamable_http, sse, stdio
    streamable_http_url: Optional[str] = None
    sse_url: Optional[str] = None
    api_key: Optional[str] = None
    command: Optional[str] = None  # stdio 协议的命令
    args: Optional[List[str]] = None  # stdio 协议的参数
    env: Optional[Dict[str, str]] = None  # stdio 协议的环境变量


@mcp_router.post("/add")
async def add(req: MCPServerRequest, http_request: Request):
    """
    添加MCP服务器到工具管理器

    Args:
        request: MCP服务器配置请求
        response: HTTP响应对象

    Returns:
        StandardResponse: 包含操作结果的标准响应
    """
    logger.info(f"[MCP Router] Received add request for server: {req.name}")
    logger.debug(f"[MCP Router] Request data: {req.dict()}")

    try:
        server_name = await add_mcp_server(
            name=req.name,
            protocol=req.protocol,
            streamable_http_url=req.streamable_http_url,
            sse_url=req.sse_url,
            api_key=req.api_key,
            command=req.command,
            args=req.args,
            env=req.env,
            disabled=False,
        )
        logger.info(f"[MCP Router] Successfully added server: {server_name}")
        return await Response.succ(
            data={"server_name": server_name, "status": "success"},
            message=f"MCP server {req.name} 添加成功",
        )
    except Exception as e:
        logger.error(f"[MCP Router] Failed to add server {req.name}: {str(e)}")
        logger.error(f"[MCP Router] Request was: {req.dict()}")
        raise


@mcp_router.get("/list")
async def list(http_request: Request):
    """
    获取所有MCP服务器列表

    Returns:
        StandardResponse: 包含MCP服务器列表的标准响应
    """
    mcp_servers = await list_mcp_servers()
    
    servers: List[Dict[str, Any]] = []
    for server in mcp_servers:
        config = server.config
        servers.append(
            {
                "name": server.name,
                "protocol": config.get("protocol"),
                "disabled": config.get("disabled", False),
                "streamable_http_url": config.get("streamable_http_url"),
                "sse_url": config.get("sse_url"),
                "api_key": config.get("api_key"),
                "command": config.get("command"),
                "args": config.get("args"),
                "env": config.get("env"),
            }
        )
    return await Response.succ(
        data={"servers": servers}, message="获取MCP服务器列表成功"
    )


@mcp_router.delete("/{server_name}")
async def remove(server_name: str, http_request: Request):
    """
    删除MCP服务器

    Args:
        server_name: 服务器名称

    Returns:
        StandardResponse: 包含操作结果的标准响应
    """
    logger.info(f"开始删除MCP server: {server_name}")
    await remove_mcp_server(server_name)
    return await Response.succ(
        data={"server_name": server_name}, message=f"MCP服务器 '{server_name}' 删除成功"
    )


@mcp_router.post("/{server_name}/refresh")
async def refresh(server_name: str, http_request: Request):
    """
    刷新MCP服务器连接

    Args:
        server_name: 服务器名称

    Returns:
        StandardResponse: 包含操作结果的标准响应
    """
    status = await refresh_mcp_server(server_name)
    return await Response.succ(data={"server_name": server_name, "status": status})


@mcp_router.put("/{server_name}/toggle")
async def toggle(server_name: str, http_request: Request):
    """
    切换MCP服务器启用/禁用状态

    Args:
        server_name: 服务器名称

    Returns:
        StandardResponse: 包含操作结果的标准响应
    """
    disabled, status_text = await toggle_mcp_server(server_name)
    return await Response.succ(
        data={"server_name": server_name, "disabled": disabled},
        message=f"MCP服务器 '{server_name}' 已{status_text}"
    )

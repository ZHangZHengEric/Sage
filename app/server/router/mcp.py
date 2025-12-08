"""
MCP (Model Context Protocol) 相关路由

提供MCP服务器的管理接口，包括添加、删除、配置等功能
"""

from typing import Optional, List, Dict, Any
from sagents.utils.logger import logger
from fastapi import APIRouter, Request
from pydantic import BaseModel
from common.render import Response

from service.mcp import (
    add_mcp_server,
    list_mcp_servers,
    remove_mcp_server,
    refresh_mcp_server,
)

# 创建路由器
mcp_router = APIRouter(prefix="/api/mcp", tags=["MCP"])


class MCPServerRequest(BaseModel):
    name: str
    protocol: str  # 协议类型：streamable_http, sse
    streamable_http_url: Optional[str] = None
    sse_url: Optional[str] = None
    api_key: Optional[str] = None


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
    logger.info(f"开始添加MCP server: {req.name}")
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    server_name = await add_mcp_server(
        name=req.name,
        protocol=req.protocol,
        streamable_http_url=req.streamable_http_url,
        sse_url=req.sse_url,
        api_key=req.api_key,
        disabled=False,
        user_id=user_id,
    )
    return await Response.succ(
        data={"server_name": server_name, "status": "success"},
        message=f"MCP server {req.name} 添加成功",
    )


@mcp_router.get("/list")
async def list(http_request: Request):
    """
    获取所有MCP服务器列表

    Returns:
        StandardResponse: 包含MCP服务器列表的标准响应
    """
    logger.info("获取MCP服务器列表")

    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    mcp_servers = await list_mcp_servers(user_id=user_id)
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
            }
        )
    return await Response.succ(
        data={"servers": servers}, message="获取MCP服务器列表成功"
    )


@mcp_router.delete("/{server_name}")
async def remove(server_name: str):
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
async def refresh(server_name: str):
    """
    刷新MCP服务器连接

    Args:
        server_name: 服务器名称

    Returns:
        StandardResponse: 包含操作结果的标准响应
    """
    logger.info(f"开始刷新MCP server: {server_name}")

    status = await refresh_mcp_server(server_name)
    return await Response.succ(data={"server_name": server_name, "status": status})

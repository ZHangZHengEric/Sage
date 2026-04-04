"""
MCP (Model Context Protocol) 相关路由

提供MCP服务器的管理接口，包括添加、删除、配置等功能
"""

from typing import Optional

from fastapi import APIRouter, Request
from loguru import logger
from pydantic import BaseModel

from common.core.request_identity import get_request_role, get_request_user_id
from common.core.render import Response
from common.services import mcp_service

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
    user_id = get_request_user_id(http_request)
    server_name = await mcp_service.add_mcp_server(
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

    user_id = get_request_user_id(http_request)
    role = get_request_role(http_request)
    
    # Admin sees all (user_id=None), User sees own (user_id=user_id)
    target_user_id = None if role == "admin" else user_id
    mcp_servers = await mcp_service.list_mcp_servers(user_id=target_user_id)
    servers = [mcp_service.serialize_mcp_server(server) for server in mcp_servers]
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
    user_id = get_request_user_id(http_request)
    role = get_request_role(http_request)
    
    logger.info(f"开始删除MCP server: {server_name}")
    await mcp_service.remove_mcp_server(server_name, user_id, role)
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
    user_id = get_request_user_id(http_request)
    role = get_request_role(http_request)


    status = await mcp_service.refresh_mcp_server(server_name, user_id, role)
    return await Response.succ(data={"server_name": server_name, "status": status})

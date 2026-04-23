"""MCP (Model Context Protocol) 相关路由"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request
from loguru import logger
from pydantic import BaseModel, Field

from common.core.request_identity import get_request_role, get_request_user_id
from common.core.render import Response
from common.services import mcp_service

# 创建路由器
mcp_router = APIRouter(prefix="/api/mcp", tags=["MCP"])


class MCPServerRequest(BaseModel):
    name: str
    protocol: str
    kind: str = "external"
    streamable_http_url: Optional[str] = None
    sse_url: Optional[str] = None
    api_key: Optional[str] = None
    command: Optional[str] = None
    args: Optional[List[str]] = None
    env: Optional[Dict[str, str]] = None
    tools: Optional[List[Dict[str, Any]]] = None
    simulator: Optional[Dict[str, Any]] = None
    description: Optional[str] = None


class AnyToolPreviewRequest(BaseModel):
    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


class AnyToolDraftPreviewRequest(BaseModel):
    tool_definition: Dict[str, Any]
    arguments: Dict[str, Any] = Field(default_factory=dict)
    simulator: Optional[Dict[str, Any]] = None
    server_name: Optional[str] = None


class AnyToolToolUpsertRequest(BaseModel):
    tool_definition: Dict[str, Any]
    original_name: Optional[str] = None
    server_name: Optional[str] = None


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
        kind=req.kind,
        streamable_http_url=req.streamable_http_url,
        sse_url=req.sse_url,
        api_key=req.api_key,
        command=req.command,
        args=req.args,
        env=req.env,
        tools=req.tools,
        simulator=req.simulator,
        description=req.description,
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


@mcp_router.put("/{server_name}")
async def update(server_name: str, req: MCPServerRequest, http_request: Request):
    user_id = get_request_user_id(http_request)
    role = get_request_role(http_request)
    if role != "admin" and req.kind == "anytool":
        # 编辑权限最终仍由存储时的 owner 校验，这里只是透传
        pass
    await mcp_service.update_mcp_server(
        server_name=server_name,
        name=req.name,
        protocol=req.protocol,
        kind=req.kind,
        streamable_http_url=req.streamable_http_url,
        sse_url=req.sse_url,
        api_key=req.api_key,
        command=req.command,
        args=req.args,
        env=req.env,
        tools=req.tools,
        simulator=req.simulator,
        description=req.description,
        disabled=False,
        user_id=user_id,
        role=role,
    )
    return await Response.succ(
        data={"server_name": server_name, "status": "success"},
        message=f"MCP server {server_name} 更新成功",
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


@mcp_router.put("/{server_name}/toggle")
async def toggle(server_name: str, http_request: Request):
    user_id = get_request_user_id(http_request)
    disabled, status_text = await mcp_service.toggle_mcp_server(server_name, user_id)
    return await Response.succ(
        data={"server_name": server_name, "disabled": disabled},
        message=f"MCP服务器 '{server_name}' 已{status_text}",
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


@mcp_router.post("/{server_name}/preview")
async def preview(server_name: str, req: AnyToolPreviewRequest, http_request: Request):
    user_id = get_request_user_id(http_request)
    role = get_request_role(http_request)
    result = await mcp_service.preview_mcp_server(
        server_name=server_name,
        tool_name=req.tool_name,
        arguments=req.arguments,
        user_id=user_id,
        role=role,
    )
    return await Response.succ(
        data=result,
        message=f"AnyTool 预览执行成功: {req.tool_name}",
    )


@mcp_router.post("/anytool/preview-draft")
async def preview_draft(req: AnyToolDraftPreviewRequest, http_request: Request):
    user_id = get_request_user_id(http_request)
    role = get_request_role(http_request)
    result = await mcp_service.preview_anytool_draft(
        tool_definition=req.tool_definition,
        arguments=req.arguments,
        simulator=req.simulator,
        server_name=req.server_name or "draft",
        user_id=user_id,
    )
    return await Response.succ(
        data=result,
        message=f"AnyTool 草稿预览执行成功: {req.tool_definition.get('name', '')}",
    )


@mcp_router.post("/anytool/tool")
async def upsert_anytool_tool(req: AnyToolToolUpsertRequest, http_request: Request):
    user_id = get_request_user_id(http_request)
    role = get_request_role(http_request)
    result = await mcp_service.upsert_anytool_tool(
        tool_definition=req.tool_definition,
        original_name=req.original_name,
        server_name=req.server_name or "AnyTool",
        user_id=user_id,
        role=role,
    )
    return await Response.succ(
        data=result,
        message=f"AnyTool 工具保存成功: {req.tool_definition.get('name', '')}",
    )


@mcp_router.delete("/anytool/tool/{tool_name}")
async def delete_anytool_tool(tool_name: str, http_request: Request, server_name: Optional[str] = None):
    # 必须显式声明，否则会落到 mount 的 AnyToolStreamableHTTPApp 上。
    result = await mcp_service.delete_anytool_tool(
        tool_name=tool_name,
        server_name=server_name or "AnyTool",
        user_id=get_request_user_id(http_request),
        role=get_request_role(http_request),
    )
    return await Response.succ(data=result, message=f"AnyTool 工具已删除: {tool_name}")

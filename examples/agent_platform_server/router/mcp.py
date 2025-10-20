"""
MCP (Model Context Protocol) 相关路由

提供MCP服务器的管理接口，包括添加、删除、配置等功能
"""

import os
import json
from typing import Dict, Any, Optional
from sagents.utils.logger import logger
from fastapi import APIRouter
from entities.entities import (
    StandardResponse, MCPServerRequest, MCPServerData,
    create_success_response, SageHTTPException, Response
)
import globals.variables as global_vars

# 创建路由器
mcp_router = APIRouter(prefix="/api/mcp", tags=["MCP"])


@mcp_router.post("/add")
async def add_mcp_server(
    request: MCPServerRequest
):
    """
    添加MCP服务器到工具管理器
    
    Args:
        request: MCP服务器配置请求
        response: HTTP响应对象
    
    Returns:
        StandardResponse: 包含操作结果的标准响应
    """
    logger.info(f"开始添加MCP server: {request.name}")
    
    # 获取依赖
    tm = global_vars.get_tool_manager()
    db_manager = global_vars.get_database_manager()
    
    # 构建服务器配置
    server_config = {
        "disabled": request.disabled,
        "protocol": request.protocol
    }
    
    if request.streamable_http_url and request.streamable_http_url.strip():
        server_config["streamable_http_url"] = request.streamable_http_url
    if request.sse_url and request.sse_url.strip():
        server_config["sse_url"] = request.sse_url
    if request.api_key and request.api_key.strip():
        server_config["api_key"] = request.api_key
    
    # 添加MCP服务器到工具管理器
    success = await tm.register_mcp_server(request.name, server_config)
    
    if success:
        # 保存到数据库
        await db_manager.save_mcp_server(
            name=request.name,
            config=server_config
        )
        
        data = MCPServerData(
            server_name=request.name,
            status="success"
        )
        
        return await Response.succ(
            data=data.model_dump(),
            message=f"MCP server {request.name} 添加成功"
        )
    else:
        raise SageHTTPException(
            status_code=500,
            detail=f"MCP server {request.name} 注册失败",
            error_detail="Tool manager registration failed"
        )


@mcp_router.get("/list")
async def list_mcp_servers():
    """
    获取所有MCP服务器列表
    
    Returns:
        StandardResponse: 包含MCP服务器列表的标准响应
    """
    logger.info("获取MCP服务器列表")
    
    # 获取依赖
    db_manager = global_vars.get_database_manager()
    
    # 从数据库获取MCP服务器列表
    mcp_servers = await db_manager.get_all_mcp_servers()
    
    # 转换为响应格式
    servers = []
    for server in mcp_servers:
        config = server.config
        server_data = {
            "name": server.name,
            "protocol": config.get("protocol", None),
            "disabled": config.get("disabled", False),
            "streamable_http_url": config.get("streamable_http_url", None),
            "sse_url": config.get("sse_url", None),
            "api_key": config.get("api_key", None)
        }
        servers.append(server_data)
    
    return await Response.succ(
        data={"servers": servers},
        message="获取MCP服务器列表成功"
    )


@mcp_router.delete("/{server_name}")
async def remove_mcp_server(
    server_name: str
):
    """
    删除MCP服务器
    
    Args:
        server_name: 服务器名称
        
    Returns:
        StandardResponse: 包含操作结果的标准响应
    """
    logger.info(f"开始删除MCP server: {server_name}")
    
    # 获取依赖
    tm = global_vars.get_tool_manager()
    db_manager = global_vars.get_database_manager()
    
    # 检查服务器是否存在
    existing_server = db_manager.get_mcp_server(server_name)
    if not existing_server:
        raise SageHTTPException(
            status_code=404,
            detail=f"MCP服务器 '{server_name}' 不存在",
            error_detail=f"MCP服务器 '{server_name}' 不存在"
        )
    
    # 从工具管理器中移除
    success = tm.remove_mcp_server(server_name)
    if not success:
        raise SageHTTPException(
            status_code=400,
            detail=f"MCP服务器 '{server_name}' 删除失败",
            error_detail="工具管理器移除失败"
        )
    
    # 从数据库删除
    db_manager.delete_mcp_server(server_name)

    logger.info(f"MCP server {server_name} 删除成功")
    return await Response.succ(
        data={"server_name": server_name},
        message=f"MCP服务器 '{server_name}' 删除成功"
    )


@mcp_router.put("/{server_name}/toggle")
async def toggle_mcp_server(
    server_name: str
):
    """
    切换MCP服务器的启用/禁用状态
    
    Args:
        server_name: 服务器名称
        
    Returns:
        StandardResponse: 包含操作结果的标准响应
    """
    logger.info(f"开始切换MCP server状态: {server_name}")
    
    # 获取依赖
    tm = global_vars.get_tool_manager()
    db_manager = global_vars.get_database_manager()
    
    # 检查服务器是否存在
    existing_config = db_manager.get_mcp_config(server_name)
    if not existing_config:
        raise SageHTTPException(
            status_code=404,
            detail=f"MCP服务器 '{server_name}' 不存在",
            error_detail=f"MCP服务器 '{server_name}' 不存在"
        )
    
    # 切换状态
    new_disabled = not existing_config.disabled
    
    # 更新数据库
    db_manager.save_mcp_config(
        server_name, 
        existing_config.streamable_http_url,
        existing_config.sse_url,
        existing_config.api_key,
        new_disabled
    )
    
    # 根据新状态处理工具管理器
    if new_disabled:
        # 禁用：从工具管理器移除
        tm.remove_mcp_server(server_name)
        status_text = "禁用"
    else:
        # 启用：添加到工具管理器
        success = tm.add_mcp_server(
            server_name,
            existing_config.streamable_http_url,
            existing_config.sse_url,
            existing_config.api_key
        )
        if not success:
            raise SageHTTPException(
                status_code=400,
                detail=f"MCP服务器 '{server_name}' 启用失败",
                error_detail="工具管理器注册失败"
            )
        status_text = "启用"
    
    logger.info(f"MCP server {server_name} 状态切换成功: {status_text}")
    return create_success_response(
        data={
            "server_name": server_name,
            "disabled": new_disabled,
            "status": status_text
        },
        message=f"MCP服务器 '{server_name}' {status_text}成功"
    )


@mcp_router.post("/{server_name}/refresh")
async def refresh_mcp_server(
    server_name: str
):
    """
    刷新MCP服务器连接
    
    Args:
        server_name: 服务器名称
        
    Returns:
        StandardResponse: 包含操作结果的标准响应
    """
    logger.info(f"开始刷新MCP server: {server_name}")
    
    # 获取依赖
    tm = global_vars.get_tool_manager()
    db_manager = global_vars.get_database_manager()
    
    # 检查服务器是否存在
    existing_server = await db_manager.get_mcp_server(server_name)
    if not existing_server:
        raise SageHTTPException(
            status_code=404,
            detail=f"MCP服务器 '{server_name}' 不存在",
            error_detail=f"MCP服务器 '{server_name}' 不存在"
        )
    
    # 获取服务器配置
    server_config = existing_server.config
    
    # 如果服务器被禁用，不允许刷新
    if server_config.get("disabled", False):
        raise SageHTTPException(
            status_code=400,
            detail=f"MCP服务器 '{server_name}' 已被禁用，无法刷新",
            error_detail="禁用的服务器无法刷新"
        )
    

    # 重新注册MCP服务器
    success = await tm.register_mcp_server(server_name, server_config)
    
    if success:
        data = MCPServerData(
            server_name=server_name,
            status="refreshed"
        )
        
        logger.info(f"MCP server {server_name} 刷新成功")
        return await Response.succ(
            data=data.model_dump(),
            message=f"MCP服务器 '{server_name}' 刷新成功"
        )
    else:
        # 刷新失败时，将服务器设置为禁用状态
        logger.warning(f"MCP server {server_name} 刷新失败，将其设置为禁用状态")
        
        # 更新服务器配置为禁用状态
        server_config["disabled"] = True
        await db_manager.save_mcp_server(
            name=server_name,
            config=server_config
        )
        
        data = MCPServerData(
            server_name=server_name,
            status="disabled_due_to_failure"
        )
        
        return await Response.succ(
            data=data.model_dump(),
            message=f"MCP服务器 '{server_name}' 刷新失败，已自动禁用"
        )


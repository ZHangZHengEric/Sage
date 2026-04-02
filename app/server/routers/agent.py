"""
Agent 相关路由
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from common.core.render import Response
from common.models.conversation import ConversationDao
from common.schemas.agent import (
    AgentConfigDTO,
    AutoGenAgentRequest,
    AuthorizationRequest,
    SystemPromptOptimizeRequest,
    convert_agent_to_config,
    convert_config_to_agent,
)
from common.services import agent_service
from sagents.utils.prompt_manager import PromptManager
from loguru import logger


# 创建路由器
agent_router = APIRouter(prefix="/api/agent", tags=["Agent"])


@agent_router.get("/list")
async def list(http_request: Request):
    """
    获取所有Agent列表（简要信息，不包含详细配置）

    Returns:
        StandardResponse: 包含所有Agent简要信息的标准响应
    """
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    role = claims.get("role") or "user"
    
    # Admin sees all (user_id=None), User sees own (user_id=user_id)
    target_user_id = None if role == "admin" else user_id
    all_configs = await agent_service.list_agents(target_user_id)
    agents_data: List[Dict[str, Any]] = []
    for agent in all_configs:
        agent_id = agent.agent_id
        agent_resp = convert_config_to_agent(agent_id, agent.config, agent.user_id)
        agents_data.append(agent_resp.model_dump())
    # 根据agent名称排序
    agents_data.sort(key=lambda x: x["name"])
    return await Response.succ(
        data=agents_data, message=f"成功获取 {len(agents_data)} 个Agent"
    )


@agent_router.get("/template/default_system_prompt")
async def get_default_system_prompt(language: str = "zh"):
    """
    获取默认的System Prompt模板（用于创建空白Agent时的初始草稿）

    Args:
        language: 语言代码，默认为zh

    Returns:
        StandardResponse: 包含默认System Prompt的内容
    """
    try:
        content = PromptManager().get_prompt(
            'agent_intro_template',
            agent='common',
            language=language,
            default=""
        )
        # 如果是模板格式（包含{agent_name}），可以预填一个默认值或者保留占位符
        # 这里为了作为草稿，我们预填 Sage
        if "{agent_name}" in content:
            content = content.format(agent_name="Sage")
            
        return await Response.succ(
            data={"content": content},
            message="成功获取默认System Prompt模板"
        )
    except Exception as e:
        return await Response.error(
            message=f"获取默认System Prompt模板失败: {str(e)}"
        )


@agent_router.post("/create")
async def create(agent: AgentConfigDTO, http_request: Request):
    """
    创建新的Agent

    Args:
        agent: Agent配置对象

    Returns:
        StandardResponse: 包含操作结果的标准响应
    """
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    created_agent = await agent_service.create_agent(
        agent.name,
        convert_agent_to_config(agent),
        user_id,
    )
    return await Response.succ(
        data={"agent_id": created_agent.agent_id}, message=f"Agent '{created_agent.agent_id}' 创建成功"
    )


@agent_router.get("/{agent_id}")
async def get(agent_id: str, http_request: Request):
    """
    根据ID获取Agent配置

    Args:
        agent_id: Agent ID

    Returns:
        StandardResponse: 包含Agent配置的标准响应
    """
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    role = claims.get("role") or "user"
    
    target_user_id = None if role == "admin" else user_id
    agent = await agent_service.get_agent(agent_id, target_user_id)
    agent_resp = convert_config_to_agent(agent_id, agent.config, agent.user_id)
    return await Response.succ(
        data=agent_resp.model_dump(), message=f"获取Agent '{agent_id}' 成功"
    )


@agent_router.put("/{agent_id}")
async def update(agent_id: str, agent: AgentConfigDTO, http_request: Request):
    """
    更新Agent配置

    Args:
        agent_id: Agent ID
        agent: 更新的Agent配置

    """
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    role = claims.get("role") or "user"
    await agent_service.update_agent(
        agent_id,
        agent.name,
        convert_agent_to_config(agent),
        user_id,
        role,
    )
    return await Response.succ(
        data={"agent_id": agent_id}, message=f"Agent '{agent_id}' 更新成功"
    )


@agent_router.delete("/{agent_id}")
async def delete(agent_id: str, http_request: Request):
    """
    删除Agent

    Args:
        agent_id: Agent ID

    """
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    role = claims.get("role") or "user"
    await agent_service.delete_agent(agent_id, user_id, role)
    return await Response.succ(
        data={"agent_id": agent_id}, message=f"Agent '{agent_id}' 删除成功"
    )


@agent_router.post("/auto-generate")
async def auto_generate(request: AutoGenAgentRequest, http_request: Request):
    """
    自动生成Agent

    Args:
        request: 自动生成Agent请求

    """
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    agent_config = await agent_service.auto_generate_agent(
        agent_description=request.agent_description,
        available_tools=request.available_tools,
        user_id=user_id,
    )
    return await Response.succ(
        data=agent_config, message="Agent自动生成成功"
    )


@agent_router.post("/system-prompt/optimize")
async def optimize(request: SystemPromptOptimizeRequest, http_request: Request):
    """
    优化系统提示词

    Args:
        request: 系统提示词优化请求

    Returns:
        StandardResponse: 包含优化后的系统提示词的标准响应
    """
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    res = await agent_service.optimize_system_prompt(
        original_prompt=request.original_prompt,
        optimization_goal=request.optimization_goal,
        user_id=user_id,
    )
    return await Response.succ(data=res, message="系统提示词优化成功")


@agent_router.get("/{agent_id}/auth")
async def get_auth(agent_id: str, http_request: Request):
    """
    获取Agent的授权用户列表
    """
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    role = claims.get("role") or "user"
    
    users = await agent_service.get_agent_authorized_users(agent_id, user_id, role)
    return await Response.succ(data=users, message="获取授权用户列表成功")


@agent_router.post("/{agent_id}/auth")
async def update_auth(agent_id: str, req: AuthorizationRequest, http_request: Request):
    """
    更新Agent的授权用户列表
    """
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    role = claims.get("role") or "user"
    
    await agent_service.update_agent_authorizations(agent_id, req.user_ids, user_id, role)
    return await Response.succ(data={}, message="更新授权成功")

@agent_router.post("/{agent_id}/file_workspace")
async def get_workspace(agent_id: str, request: Request, session_id: Optional[str] = None):
    """获取指定会话的文件工作空间"""
    claims = getattr(request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    role = claims.get("role") or "user"

    if role == "admin" and session_id:
        dao = ConversationDao()
        conversation = await dao.get_by_session_id(session_id)
        if conversation:
            user_id = conversation.user_id

    result = await agent_service.get_server_file_workspace(agent_id, user_id)
    files = result.get("files", [])
    logger.bind(agent_id=agent_id).info(f"获取工作空间文件数量：{len(files)}")
    return await Response.succ(message=result.get("message", "获取文件列表成功"), data={**result, "user_id": user_id})

@agent_router.get("/{agent_id}/file_workspace/download")
async def download_file(agent_id: str, request: Request, session_id: Optional[str] = None):
    """获取指定会话的文件工作空间"""
    claims = getattr(request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    role = claims.get("role") or "user"

    if role == "admin" and session_id:
        dao = ConversationDao()
        conversation = await dao.get_by_session_id(session_id)
        if conversation:
            user_id = conversation.user_id
            
    file_path = request.query_params.get("file_path")
    logger.info(f"Download request: file_path={file_path}")
    try:
        path, filename, media_type = await agent_service.download_server_agent_file(
            agent_id,
            user_id,
            file_path,
        )
        logger.info(f"Download resolved: path={path}")
        return FileResponse(
            path=path, filename=filename, media_type=media_type
        )
    except Exception as e:
        logger.error(f"Download failed: {e}")
        raise


@agent_router.delete("/{agent_id}/file_workspace/delete")
async def delete_file(agent_id: str, request: Request, session_id: Optional[str] = None):
    """删除指定会话的文件"""
    claims = getattr(request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    role = claims.get("role") or "user"
    
    if role == "admin" and session_id:
        dao = ConversationDao()
        conversation = await dao.get_by_session_id(session_id)
        if conversation:
            user_id = conversation.user_id
            
    file_path = request.query_params.get("file_path")
    logger.info(f"Delete request: file_path={file_path}")
    try:
        await agent_service.delete_server_agent_file(agent_id, user_id, file_path)
        return await Response.succ(message=f"文件 {file_path} 已删除")
    except Exception as e:
        logger.error(f"Delete failed: {e}")
        raise

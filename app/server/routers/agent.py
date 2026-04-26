"""
Agent 相关路由
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from common.core.request_identity import (
    get_request_role,
    get_request_user_id,
    get_target_user_id_for_role,
)
from common.core.render import Response
from common.models.conversation import ConversationDao
from common.schemas.agent import (
    AgentAbilitiesRequest,
    AgentConfigDTO,
    AutoGenAgentRequest,
    DeleteAgentWorkspaceRequest,
    AuthorizationRequest,
    SystemPromptOptimizeRequest,
    convert_agent_to_config,
)
from common.services import agent_router_service, agent_service
from common.services.agent_view_service import serialize_agent, serialize_agents
from loguru import logger


# 创建路由器
agent_router = APIRouter(prefix="/api/agent", tags=["Agent"])


def _resolve_request_language(http_request: Request, language: Optional[str] = None, default: str = "en") -> str:
    candidate = (language or "").strip()
    if not candidate:
        headers = http_request.headers
        candidate = (
            headers.get("x-accept-language")
            or headers.get("accept-language")
            or ""
        ).strip()
    lowered = candidate.lower()
    if lowered.startswith("pt"):
        return "pt"
    if lowered.startswith("en"):
        return "en"
    if lowered.startswith("zh") or lowered.startswith("cn"):
        return "zh"
    return default


@agent_router.get("/list")
async def list(http_request: Request):
    """
    获取所有Agent列表（简要信息，不包含详细配置）

    Returns:
        StandardResponse: 包含所有Agent简要信息的标准响应
    """
    target_user_id = get_target_user_id_for_role(http_request)
    all_configs = await agent_service.list_agents(target_user_id)
    agents_data = serialize_agents(all_configs)
    return await Response.succ(
        data=agents_data, message=f"成功获取 {len(agents_data)} 个Agent"
    )


@agent_router.get("/template/default_system_prompt")
async def get_default_system_prompt(http_request: Request, language: str = "en"):
    """
    获取默认的System Prompt模板（用于创建空白Agent时的初始草稿）

    Args:
        language: 语言代码，默认为en

    Returns:
        StandardResponse: 包含默认System Prompt的内容
    """
    try:
        resolved_language = _resolve_request_language(http_request, language, default="zh")
        result = await agent_router_service.build_default_system_prompt_response(
            language=resolved_language,
        )
        return await Response.succ(data=result["data"], message=result["message"])
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
    user_id = get_request_user_id(http_request)
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
    target_user_id = get_target_user_id_for_role(http_request)
    agent = await agent_service.get_agent(agent_id, target_user_id)
    return await Response.succ(
        data=serialize_agent(agent), message=f"获取Agent '{agent_id}' 成功"
    )


@agent_router.put("/{agent_id}")
async def update(agent_id: str, agent: AgentConfigDTO, http_request: Request):
    """
    更新Agent配置

    Args:
        agent_id: Agent ID
        agent: 更新的Agent配置

    """
    user_id = get_request_user_id(http_request)
    role = get_request_role(http_request)
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
    user_id = get_request_user_id(http_request)
    role = get_request_role(http_request)
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
    user_id = get_request_user_id(http_request)
    language = _resolve_request_language(http_request, request.language, default="en")
    result = await agent_router_service.build_auto_generate_response(
        agent_description=request.agent_description,
        available_tools=request.available_tools,
        user_id=user_id,
        language=language,
    )
    return await Response.succ(data=result["data"], message=result["message"])


@agent_router.post("/auto-generate/submit")
async def auto_generate_submit(request: AutoGenAgentRequest, http_request: Request):
    user_id = get_request_user_id(http_request)
    language = _resolve_request_language(http_request, request.language, default="en")
    result = await agent_router_service.submit_auto_generate_task(
        agent_description=request.agent_description,
        available_tools=request.available_tools,
        user_id=user_id,
        language=language,
    )
    return await Response.succ(data=result["data"], message=result["message"])


@agent_router.post("/system-prompt/optimize")
async def optimize(request: SystemPromptOptimizeRequest, http_request: Request):
    """
    优化系统提示词

    Args:
        request: 系统提示词优化请求

    Returns:
        StandardResponse: 包含优化后的系统提示词的标准响应
    """
    user_id = get_request_user_id(http_request)
    language = _resolve_request_language(http_request, request.language, default="en")
    result = await agent_router_service.build_system_prompt_optimize_response(
        original_prompt=request.original_prompt,
        optimization_goal=request.optimization_goal,
        user_id=user_id,
        language=language,
    )
    return await Response.succ(data=result["data"], message=result["message"])


@agent_router.post("/system-prompt/optimize/submit")
async def optimize_submit(request: SystemPromptOptimizeRequest, http_request: Request):
    user_id = get_request_user_id(http_request)
    language = _resolve_request_language(http_request, request.language, default="en")
    result = await agent_router_service.submit_system_prompt_optimize_task(
        original_prompt=request.original_prompt,
        optimization_goal=request.optimization_goal,
        user_id=user_id,
        language=language,
    )
    return await Response.succ(data=result["data"], message=result["message"])


@agent_router.post("/abilities")
async def get_agent_abilities(req: AgentAbilitiesRequest, http_request: Request):
    user_id = get_request_user_id(http_request)
    language = _resolve_request_language(http_request, req.language, default="en")
    result = await agent_router_service.build_agent_abilities_response(
        agent_id=req.agent_id,
        session_id=req.session_id,
        context=req.context,
        language=language,
        user_id=user_id,
    )
    return await Response.succ(data=result["data"], message=result["message"])


@agent_router.get("/tasks/{task_id}")
async def get_task(task_id: str, http_request: Request):
    user_id = get_request_user_id(http_request)
    from common.services.async_task_service import get_async_task_service

    task = await get_async_task_service().get(task_id, user_id)
    return await Response.succ(data=task, message="获取任务状态成功")


@agent_router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str, http_request: Request):
    user_id = get_request_user_id(http_request)
    from common.services.async_task_service import get_async_task_service

    task = await get_async_task_service().cancel(task_id, user_id)
    return await Response.succ(data=task, message="任务取消请求已提交")


@agent_router.get("/{agent_id}/auth")
async def get_auth(agent_id: str, http_request: Request):
    """
    获取Agent的授权用户列表
    """
    user_id = get_request_user_id(http_request)
    role = get_request_role(http_request)
    
    users = await agent_service.get_agent_authorized_users(agent_id, user_id, role)
    return await Response.succ(data=users, message="获取授权用户列表成功")


@agent_router.post("/{agent_id}/auth")
async def update_auth(agent_id: str, req: AuthorizationRequest, http_request: Request):
    """
    更新Agent的授权用户列表
    """
    user_id = get_request_user_id(http_request)
    role = get_request_role(http_request)
    
    await agent_service.update_agent_authorizations(agent_id, req.user_ids, user_id, role)
    return await Response.succ(data={}, message="更新授权成功")

@agent_router.post("/{agent_id}/file_workspace")
async def get_workspace(agent_id: str, request: Request, session_id: Optional[str] = None):
    """获取指定会话的文件工作空间"""
    user_id = get_request_user_id(request)
    role = get_request_role(request)

    if role == "admin" and session_id:
        dao = ConversationDao()
        conversation = await dao.get_by_session_id(session_id)
        if conversation:
            user_id = conversation.user_id

    result = await agent_router_service.build_workspace_listing_response(
        agent_id=agent_id,
        user_id=user_id,
        fetcher=lambda: agent_service.get_server_file_workspace(agent_id, user_id),
    )
    files = result["data"].get("files", [])
    logger.bind(agent_id=agent_id).info(f"获取工作空间文件数量：{len(files)}")
    return await Response.succ(message=result["message"], data=result["data"])

@agent_router.get("/{agent_id}/file_workspace/download")
async def download_file(agent_id: str, request: Request, session_id: Optional[str] = None):
    """获取指定会话的文件工作空间"""
    user_id = get_request_user_id(request)
    role = get_request_role(request)

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
    user_id = get_request_user_id(request)
    role = get_request_role(request)
    
    if role == "admin" and session_id:
        dao = ConversationDao()
        conversation = await dao.get_by_session_id(session_id)
        if conversation:
            user_id = conversation.user_id
            
    file_path = request.query_params.get("file_path")
    logger.info(f"Delete request: file_path={file_path}")
    try:
        result = await agent_router_service.build_workspace_delete_response(
            file_path=file_path,
            deleter=lambda: agent_service.delete_server_agent_file(agent_id, user_id, file_path),
        )
        return await Response.succ(message=result["message"], data=result["data"])
    except Exception as e:
        logger.error(f"Delete failed: {e}")
        raise


@agent_router.post("/workspace/delete")
async def delete_agent_workspace(req: DeleteAgentWorkspaceRequest):
    """
    删除指定用户个人工作空间下的 Agent workspace。

    注意：该接口不做业务鉴权校验，由调用方自行控制。
    """
    result = await agent_router_service.build_agent_workspace_delete_response(
        agent_id=req.agent_id,
        user_id=req.user_id,
        deleter=lambda: agent_service.delete_server_agent_workspace(req.agent_id, req.user_id),
    )
    return await Response.succ(message=result["message"], data=result["data"])

"""
工具执行接口路由模块
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, Request, UploadFile
from pydantic import BaseModel

from common.core.request_identity import get_request_role, get_request_user_id
from common.core.render import Response
from common.services import skill_router_service
from loguru import logger
# 创建路由器
skill_router = APIRouter(prefix="/api/skills")


class UrlImportRequest(BaseModel):
    url: str
    is_system: bool = False
    is_agent: bool = False
    agent_id: Optional[str] = None


class SkillUpdateRequest(BaseModel):
    name: str
    content: str


class SyncWorkspaceSkillsRequest(BaseModel):
    user_id: str
    agent_id: str
    purge_extra: bool = False


@skill_router.get("")
async def get_skills(
    http_request: Request,
    agent_id: Optional[str] = None,
    dimension: Optional[str] = None
):
    """
    获取可用技能列表
    
    Args:
        agent_id: 可选，过滤特定Agent的技能
        dimension: 可选，按维度过滤 (system, user, agent)
    """
    result = await skill_router_service.build_skills_response(
        user_id=get_request_user_id(http_request),
        role=get_request_role(http_request),
        agent_id=agent_id,
        dimension=dimension,
    )
    return await Response.succ(message=result["message"], data=result["data"])


@skill_router.get("/agent-available")
async def get_agent_available_skills(
    http_request: Request,
    agent_id: str
):
    """
    获取Agent可用的技能列表（带维度来源标签）
    
    根据skill name去重，优先级：系统 < 用户 < Agent
    每个技能会标注其来源维度 (system, user, agent)
    
    Args:
        agent_id: Agent ID（必填）
    """
    result = await skill_router_service.build_agent_available_skills_response(
        agent_id=agent_id,
        user_id=get_request_user_id(http_request),
        role=get_request_role(http_request),
    )
    return await Response.succ(message=result["message"], data=result["data"])


@skill_router.post("/upload")
async def upload_skill(
    http_request: Request,
    file: UploadFile = File(...),
    is_system: bool = Form(False),
    is_agent: bool = Form(False),
    agent_id: Optional[str] = Form(None)
):
    """
    通过上传 ZIP 文件导入技能
    """
    result = await skill_router_service.build_upload_skill_response(
        file=file,
        user_id=get_request_user_id(http_request),
        role=get_request_role(http_request),
        is_system=is_system,
        is_agent=is_agent,
        agent_id=agent_id,
        include_user_id=True,
    )
    return await Response.succ(message=result["message"], data=result["data"])


@skill_router.post("/import-url")
async def import_skill_from_url(request: UrlImportRequest, http_request: Request):
    """
    通过 URL 导入技能 (ZIP)
    """
    result = await skill_router_service.build_import_skill_url_response(
        url=request.url,
        user_id=get_request_user_id(http_request),
        role=get_request_role(http_request),
        is_system=request.is_system,
        is_agent=request.is_agent,
        agent_id=request.agent_id,
        include_user_id=True,
    )
    return await Response.succ(message=result["message"], data=result["data"])


@skill_router.delete("")
async def delete_skill(
    name: str,
    http_request: Request,
    agent_id: Optional[str] = None
):
    """
    删除技能
    
    Args:
        name: 技能名称
        agent_id: 可选，如果提供则删除指定Agent工作空间下的skill
    """
    # name is query param
    result = await skill_router_service.build_delete_skill_response(
        name=name,
        user_id=get_request_user_id(http_request),
        role=get_request_role(http_request),
        agent_id=agent_id,
    )
    return await Response.succ(message=result["message"], data=result["data"])


@skill_router.get("/content")
async def get_skill_content(name: str, http_request: Request):
    """
    获取技能内容 (SKILL.md)
    """
    # name is query param, usually automatically decoded by FastAPI/Starlette, 
    # but let's ensure it's handled if passed as part of query string.
    # Actually FastAPI decodes query params automatically.
    logger.info(f"get_skill_content name: {name}")
    result = await skill_router_service.build_skill_content_response(
        name=name,
        user_id=get_request_user_id(http_request),
        role=get_request_role(http_request),
    )
    return await Response.succ(data=result["data"])


@skill_router.put("/content")
async def update_skill_content(request: SkillUpdateRequest, http_request: Request):
    """
    更新技能内容 (SKILL.md)
    """
    result = await skill_router_service.build_update_skill_content_response(
        name=request.name,
        content=request.content,
        user_id=get_request_user_id(http_request),
        role=get_request_role(http_request),
    )
    return await Response.succ(message=result["message"], data=result["data"])


@skill_router.post("/sync-to-agent")
async def sync_skill_to_agent(
    http_request: Request,
    skill_name: str = Form(...),
    agent_id: str = Form(...)
):
    """
    将技能同步到Agent工作空间

    从技能广场（系统或用户技能）复制技能到Agent工作空间。
    如果Agent工作空间已存在该技能，则会覆盖更新。

    Args:
        skill_name: 技能名称（必填）
        agent_id: Agent ID（必填）
    """
    result = await skill_router_service.build_sync_skill_to_agent_response(
        skill_name=skill_name,
        agent_id=agent_id,
        user_id=get_request_user_id(http_request),
        role=get_request_role(http_request),
    )
    return await Response.succ(message=result["message"], data=result["data"])


@skill_router.post("/sync-workspace-skills")
async def sync_workspace_skills(
    request: SyncWorkspaceSkillsRequest,
    http_request: Request,
):
    """
    批量同步 Agent 配置中的 skills 到其 workspace 目录。

    purge_extra=true 时，workspace 中多出来的 skill 也会被删除，完全对齐配置；
    purge_extra=false 时，只覆盖同名的，不删多余的。
    """
    target_user_id = request.user_id or get_request_user_id(http_request)
    result = await skill_router_service.build_sync_workspace_skills_response(
        user_id=target_user_id,
        agent_id=request.agent_id,
        purge_extra=request.purge_extra,
    )
    return await Response.succ(message=result["message"], data=result["data"])

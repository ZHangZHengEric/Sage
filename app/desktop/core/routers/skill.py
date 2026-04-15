"""
工具执行接口路由模块
"""

from typing import Any, Dict, List

from fastapi import APIRouter, File, Form, Request, UploadFile
from pydantic import BaseModel

from common.core.render import Response
from common.services import skill_router_service
from loguru import logger
from ..user_context import get_desktop_user_id, get_desktop_user_role
# 创建路由器
skill_router = APIRouter(prefix="/api/skills")


class UrlImportRequest(BaseModel):
    url: str


class SkillUpdateRequest(BaseModel):
    name: str
    content: str


class SyncWorkspaceSkillsRequest(BaseModel):
    user_id: str = ""
    agent_id: str
    purge_extra: bool = False


@skill_router.get("")
async def get_skills(http_request: Request):
    """
    获取可用技能列表
    """
    result = await skill_router_service.build_skills_response(
        user_id=get_desktop_user_id(http_request),
        role=get_desktop_user_role(http_request),
    )
    return await Response.succ(message=result["message"], data=result["data"])


@skill_router.post("/upload")
async def upload_skill(http_request: Request, file: UploadFile = File(...)):
    """
    通过上传 ZIP 文件导入技能
    """
    result = await skill_router_service.build_upload_skill_response(
        file=file,
        user_id=get_desktop_user_id(http_request),
        role=get_desktop_user_role(http_request),
    )
    return await Response.succ(message=result["message"], data=result["data"])


@skill_router.post("/import-url")
async def import_skill_from_url(request: UrlImportRequest, http_request: Request):
    """
    通过 URL 导入技能 (ZIP)
    """
    result = await skill_router_service.build_import_skill_url_response(
        url=request.url,
        user_id=get_desktop_user_id(http_request),
        role=get_desktop_user_role(http_request),
    )
    return await Response.succ(message=result["message"], data=result["data"])


@skill_router.delete("")
async def delete_skill(name: str, http_request: Request):
    """
    删除技能
    """
    # name is query param
    result = await skill_router_service.build_delete_skill_response(
        name=name,
        user_id=get_desktop_user_id(http_request),
        role=get_desktop_user_role(http_request),
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
        user_id=get_desktop_user_id(http_request),
        role=get_desktop_user_role(http_request),
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
        user_id=get_desktop_user_id(http_request),
        role=get_desktop_user_role(http_request),
    )
    return await Response.succ(message=result["message"], data=result["data"])


@skill_router.get("/agent-available")
async def get_agent_available_skills(
    http_request: Request,
    agent_id: str
):
    """
    获取Agent可用的技能列表（带维度来源标签和同步状态）

    Args:
        agent_id: Agent ID（必填）
    """
    result = await skill_router_service.build_agent_available_skills_response(
        agent_id=agent_id,
        user_id=get_desktop_user_id(http_request),
        role=get_desktop_user_role(http_request),
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

    Args:
        skill_name: 技能名称（必填）
        agent_id: Agent ID（必填）
    """
    result = await skill_router_service.build_sync_skill_to_agent_response(
        skill_name=skill_name,
        agent_id=agent_id,
        user_id=get_desktop_user_id(http_request),
        role=get_desktop_user_role(http_request),
    )
    return await Response.succ(message=result["message"], data=result["data"])


@skill_router.post("/sync-workspace-skills")
async def sync_workspace_skills(
    request: SyncWorkspaceSkillsRequest,
    http_request: Request,
):
    """
    批量同步 Agent 配置中的 skills 到其 workspace 目录。
    """
    target_user_id = request.user_id or get_desktop_user_id(http_request)
    result = await skill_router_service.build_sync_workspace_skills_response(
        user_id=target_user_id,
        agent_id=request.agent_id,
        purge_extra=request.purge_extra,
    )
    return await Response.succ(message=result["message"], data=result["data"])

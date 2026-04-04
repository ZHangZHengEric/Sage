"""
工具执行接口路由模块
"""

from typing import Any, Dict, List

from fastapi import APIRouter, File, Request, UploadFile
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

"""
工具执行接口路由模块
"""

from typing import Any, Dict

from fastapi import APIRouter, File, Request, UploadFile
from pydantic import BaseModel

from ..core.render import Response
from ..services import skill as skill_service

# 创建路由器
skill_router = APIRouter(prefix="/api/skills")


class UrlImportRequest(BaseModel):
    url: str


class SkillContentRequest(BaseModel):
    content: str


@skill_router.get("")
async def get_skills(http_request: Request):
    """
    获取可用技能列表
    """
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    role = claims.get("role") or "user"

    skills = await skill_service.list_skills(user_id, role)
    return await Response.succ(
        message="获取技能列表成功", data={"skills": skills}
    )


@skill_router.post("/upload")
async def upload_skill(http_request: Request, file: UploadFile = File(...)):
    """
    通过上传 ZIP 文件导入技能
    """
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""

    message = await skill_service.import_skill_by_file(file, user_id)
    return await Response.succ(message=message, data={"user_id": user_id})


@skill_router.post("/import-url")
async def import_skill_from_url(request: UrlImportRequest, http_request: Request):
    """
    通过 URL 导入技能 (ZIP)
    """
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""

    message = await skill_service.import_skill_by_url(request.url, user_id)
    return await Response.succ(message=message, data={"user_id": user_id})


@skill_router.delete("/{skill_name}")
async def delete_skill(skill_name: str, http_request: Request):
    """
    删除技能
    """
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    role = claims.get("role") or "user"

    await skill_service.delete_skill(skill_name, user_id, role)
    return await Response.succ(message=f"技能 '{skill_name}' 删除成功")


@skill_router.get("/{skill_name}/content")
async def get_skill_content(skill_name: str, http_request: Request):
    """
    获取技能内容 (SKILL.md)
    """
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    role = claims.get("role") or "user"

    content = await skill_service.get_skill_content(skill_name, user_id, role)
    return await Response.succ(data={"content": content})


@skill_router.put("/{skill_name}/content")
async def update_skill_content(skill_name: str, request: SkillContentRequest, http_request: Request):
    """
    更新技能内容 (SKILL.md)
    """
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    role = claims.get("role") or "user"

    message = await skill_service.update_skill_content(skill_name, request.content, user_id, role)
    return await Response.succ(message=message)


"""
工具执行接口路由模块
"""

from typing import Any, Dict, List

from fastapi import APIRouter, File, Request, UploadFile
from pydantic import BaseModel

from ..core.render import Response
from ..services import skill as skill_service
from loguru import logger
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
    skills = await skill_service.list_skills()
    return await Response.succ(
        message="获取技能列表成功", data={"skills": skills}
    )


@skill_router.post("/upload")
async def upload_skill(http_request: Request, file: UploadFile = File(...)):
    """
    通过上传 ZIP 文件导入技能
    """
    message = await skill_service.import_skill_by_file(file)
    return await Response.succ(message=message, data={})


@skill_router.post("/import-url")
async def import_skill_from_url(request: UrlImportRequest, http_request: Request):
    """
    通过 URL 导入技能 (ZIP)
    """
    message = await skill_service.import_skill_by_url(request.url)
    return await Response.succ(message=message, data={})


@skill_router.delete("")
async def delete_skill(name: str, http_request: Request):
    """
    删除技能
    """
    # name is query param
    await skill_service.delete_skill(name)
    return await Response.succ(message=f"技能 '{name}' 删除成功")


@skill_router.get("/content")
async def get_skill_content(name: str, http_request: Request):
    """
    获取技能内容 (SKILL.md)
    """
    # name is query param, usually automatically decoded by FastAPI/Starlette, 
    # but let's ensure it's handled if passed as part of query string.
    # Actually FastAPI decodes query params automatically.
    logger.info(f"get_skill_content name: {name}")
    content = await skill_service.get_skill_content(name)
    return await Response.succ(data={"content": content})


@skill_router.put("/content")
async def update_skill_content(request: SkillUpdateRequest, http_request: Request):
    """
    更新技能内容 (SKILL.md)
    """
    message = await skill_service.update_skill_content(request.name, request.content)
    return await Response.succ(message=message)

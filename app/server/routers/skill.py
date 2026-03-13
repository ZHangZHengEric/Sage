"""
工具执行接口路由模块
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, Request, UploadFile
from pydantic import BaseModel

from ..core.render import Response
from ..services import skill as skill_service
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
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    role = claims.get("role") or "user"

    skills = await skill_service.list_skills(user_id, role, agent_id, dimension)
    return await Response.succ(
        message="获取技能列表成功", data={"skills": skills}
    )


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
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    role = claims.get("role") or "user"

    skills = await skill_service.get_agent_available_skills(agent_id, user_id, role)
    return await Response.succ(
        message="获取Agent可用技能列表成功", data={"skills": skills}
    )


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
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    role = claims.get("role") or "user"

    message = await skill_service.import_skill_by_file(
        file, user_id, role, is_system, is_agent, agent_id
    )
    return await Response.succ(message=message, data={"user_id": user_id})


@skill_router.post("/import-url")
async def import_skill_from_url(request: UrlImportRequest, http_request: Request):
    """
    通过 URL 导入技能 (ZIP)
    """
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    role = claims.get("role") or "user"

    message = await skill_service.import_skill_by_url(
        request.url, user_id, role, request.is_system, request.is_agent, request.agent_id
    )
    return await Response.succ(message=message, data={"user_id": user_id})


@skill_router.delete("")
async def delete_skill(name: str, http_request: Request):
    """
    删除技能
    """
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    role = claims.get("role") or "user"
    # name is query param
    await skill_service.delete_skill(name, user_id, role)
    return await Response.succ(message=f"技能 '{name}' 删除成功")


@skill_router.get("/content")
async def get_skill_content(name: str, http_request: Request):
    """
    获取技能内容 (SKILL.md)
    """
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    role = claims.get("role") or "user"
    # name is query param, usually automatically decoded by FastAPI/Starlette, 
    # but let's ensure it's handled if passed as part of query string.
    # Actually FastAPI decodes query params automatically.
    logger.info(f"get_skill_content name: {name}")
    content = await skill_service.get_skill_content(name, user_id, role)
    return await Response.succ(data={"content": content})


@skill_router.put("/content")
async def update_skill_content(request: SkillUpdateRequest, http_request: Request):
    """
    更新技能内容 (SKILL.md)
    """
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    role = claims.get("role") or "user"

    message = await skill_service.update_skill_content(request.name, request.content , user_id, role)
    return await Response.succ(message=message)

from typing import Any, Dict, Optional

from fastapi import UploadFile

from common.services import skill_service


async def build_skills_response(
    *,
    user_id: str,
    role: str = "user",
    agent_id: Optional[str] = None,
    dimension: Optional[str] = None,
) -> Dict[str, Any]:
    skills = await skill_service.list_skills(user_id, role, agent_id, dimension)
    return {
        "message": "获取技能列表成功",
        "data": {"skills": skills},
    }


async def build_agent_available_skills_response(
    *,
    agent_id: str,
    user_id: str,
    role: str = "user",
) -> Dict[str, Any]:
    skills = await skill_service.get_agent_available_skills(agent_id, user_id, role)
    return {
        "message": "获取Agent可用技能列表成功",
        "data": {"skills": skills},
    }


async def build_upload_skill_response(
    *,
    file: UploadFile,
    user_id: str,
    role: str = "user",
    is_system: bool = False,
    is_agent: bool = False,
    agent_id: Optional[str] = None,
    include_user_id: bool = False,
) -> Dict[str, Any]:
    message = await skill_service.import_skill_by_file(
        file,
        user_id,
        role,
        is_system,
        is_agent,
        agent_id,
    )
    data: Dict[str, Any] = {}
    if include_user_id:
        data["user_id"] = user_id
    return {
        "message": message,
        "data": data,
    }


async def build_import_skill_url_response(
    *,
    url: str,
    user_id: str,
    role: str = "user",
    is_system: bool = False,
    is_agent: bool = False,
    agent_id: Optional[str] = None,
    include_user_id: bool = False,
) -> Dict[str, Any]:
    message = await skill_service.import_skill_by_url(
        url,
        user_id,
        role,
        is_system,
        is_agent,
        agent_id,
    )
    data: Dict[str, Any] = {}
    if include_user_id:
        data["user_id"] = user_id
    return {
        "message": message,
        "data": data,
    }


async def build_delete_skill_response(
    *,
    name: str,
    user_id: str,
    role: str = "user",
    agent_id: Optional[str] = None,
) -> Dict[str, Any]:
    await skill_service.delete_skill(name, user_id, role, agent_id)
    return {
        "message": f"技能 '{name}' 删除成功",
        "data": {},
    }


async def build_skill_content_response(
    *,
    name: str,
    user_id: str,
    role: str = "user",
) -> Dict[str, Any]:
    content = await skill_service.get_skill_content(name, user_id, role)
    return {
        "message": "",
        "data": {"content": content},
    }


async def build_update_skill_content_response(
    *,
    name: str,
    content: str,
    user_id: str,
    role: str = "user",
) -> Dict[str, Any]:
    message = await skill_service.update_skill_content(name, content, user_id, role)
    return {
        "message": message,
        "data": {},
    }


async def build_sync_skill_to_agent_response(
    *,
    skill_name: str,
    agent_id: str,
    user_id: str,
    role: str = "user",
) -> Dict[str, Any]:
    """
    构建同步技能到Agent的响应
    """
    result = await skill_service.sync_skill_to_agent(skill_name, agent_id, user_id, role)
    return {
        "message": f"技能 '{skill_name}' 已成功同步到Agent工作空间",
        "data": result,
    }

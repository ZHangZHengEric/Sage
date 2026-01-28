"""
工具执行接口路由模块
"""

from fastapi import APIRouter
from sagents.skills.skill_manager import get_skill_manager

from ..core.render import Response

# 创建路由器
skill_router = APIRouter(prefix="/api/skills")


@skill_router.get("")
async def get_skills():
    """
    获取可用技能列表

    Args:

    """
    skills = []

    tm = get_skill_manager()
    if tm:
        skills = tm.list_skills()

    return await Response.succ(message="获取技能列表成功", data={"skills": skills})

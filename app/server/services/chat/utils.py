import os
import random
from typing import Any, Dict, List, Optional

from loguru import logger
from openai import AsyncOpenAI

def create_model_client(client_params: Dict[str, Any]) -> Any:
    api_key = client_params.get("api_key")
    base_url = client_params.get("base_url")
    if api_key and isinstance(api_key, str) and "," in api_key:
        keys = [k.strip() for k in api_key.split(",") if k.strip()]
        if keys:
            api_key = random.choice(keys)
            logger.info(f"Using random key from {len(keys)} available keys")

    logger.info(f"初始化Chat模型客户端: model={client_params.get('model')}, base_url={base_url}")
    model_client = AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
    )
    model_client.model = client_params.get("model")
    return model_client

def create_tool_proxy(available_tools: List[str]):
    from sagents.tool.tool_manager import get_tool_manager
    from sagents.tool.tool_proxy import ToolProxy
    if not available_tools:
        return ToolProxy(get_tool_manager(), [])
    logger.info(f"初始化工具代理，可用工具: {available_tools}")
    tool_proxy = ToolProxy(get_tool_manager(), available_tools)
    return tool_proxy

def create_skill_proxy(
    available_skills: List[str],
    user_id: Optional[str] = None,
    agent_workspace: Optional[str] = None
):
    """
    创建带优先级的 SkillProxy

    优先级顺序 (高 -> 低):
    1. agent_workspace/skills/ - Agent 工作区中的技能
    2. users/{user_id}/skills/ - 用户上传的技能
    3. skills/ - 系统自带技能
    4. 全局技能管理器中的技能

    Args:
        available_skills: 可用技能名称列表
        user_id: 当前用户ID，用于查找用户技能
        agent_workspace: Agent 工作区路径，用于查找工作区技能
    """
    from sagents.skill.skill_manager import SkillManager, get_skill_manager
    from sagents.skill.skill_proxy import SkillProxy
    from app.server.core.config import get_startup_config

    if not available_skills:
        return SkillProxy(get_skill_manager(), []), None

    # 获取全局 skill_manager 作为基础
    global_skill_manager = get_skill_manager()

    # 从配置获取路径
    cfg = get_startup_config()
    skill_dir = cfg.skill_dir if cfg else "skills"
    user_dir = cfg.user_dir if cfg else "users"

    # 构建优先级列表 (高优先级在前)
    skill_managers = []
    agent_skill_manager = None
    # 1. Agent 工作区技能 (最高优先级)
    if agent_workspace:
        agent_skills_dir = os.path.join(agent_workspace, "skills")
        if os.path.exists(agent_skills_dir):
            agent_skill_manager = SkillManager(skill_dirs=[agent_skills_dir], isolated=True, include_global_skills=False)
            skill_managers.append(agent_skill_manager)
            logger.info(f"Agent工作区技能目录已加载: {agent_skills_dir}")

    # 2. 用户技能: users/{user_id}/skills/
    if user_id:
        user_skills_dir = os.path.join(user_dir, user_id, "skills")
        if os.path.exists(user_skills_dir):
            user_skill_manager = SkillManager(skill_dirs=[user_skills_dir], isolated=True, include_global_skills=False)
            skill_managers.append(user_skill_manager)
            logger.info(f"用户技能目录已加载: {user_skills_dir}")

    # 3. 系统技能: skills/
    if os.path.exists(skill_dir):
        system_skill_manager = SkillManager(skill_dirs=[skill_dir], isolated=True, include_global_skills=False)
        skill_managers.append(system_skill_manager)
        logger.info(f"系统技能目录已加载: {skill_dir}")

    # 4. 全局技能管理器 (最低优先级)
    skill_managers.append(global_skill_manager)

    logger.info(f"初始化技能代理，可用技能: {available_skills}, 优先级层数: {len(skill_managers)}")
    skill_proxy = SkillProxy(skill_managers, available_skills)
    return skill_proxy, agent_skill_manager

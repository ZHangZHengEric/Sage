import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger
from openai import AsyncOpenAI
from sagents.llm.chat import OpenAIChat

from common.core import config


def _get_cfg() -> config.StartupConfig:
    cfg = config.get_startup_config()
    if not cfg:
        raise RuntimeError("Startup config not initialized")
    return cfg


def _is_desktop_mode() -> bool:
    return _get_cfg().app_mode == "desktop"


def _get_first_api_key(api_key: Any) -> Any:
    if isinstance(api_key, str) and "," in api_key:
        keys = [key.strip() for key in api_key.split(",") if key.strip()]
        if keys:
            return keys[0]
    return api_key


def create_model_client(client_params: Dict[str, Any]) -> Any:
    """
    创建模型客户端
    
    支持标准模型和快速模型双配置
    快速模型配置参数（可选）：
    - fast_api_key: 快速模型 API Key（默认使用标准模型的 key）
    - fast_base_url: 快速模型 Base URL（默认使用标准模型的 URL）
    - fast_model_name: 快速模型名称（如果不设置，则不启用快速模型）
    """
    api_key = _get_first_api_key(client_params.get("api_key"))
    base_url = client_params.get("base_url")
    model_name = client_params.get("model")
    timeout = client_params.get("timeout", 60 * 30)
    
    # 快速模型配置（可选）
    fast_api_key = client_params.get("fast_api_key")
    fast_base_url = client_params.get("fast_base_url")
    fast_model_name = client_params.get("fast_model_name")

    logger.info(
        f"初始化Chat模型客户端: model={model_name}, base_url={base_url}, "
        f"fast_model={fast_model_name if fast_model_name else '未配置'}"
    )
    
    # 使用 OpenAIChat 创建客户端（支持双模型）
    openai_chat = OpenAIChat(
        api_key=api_key,
        base_url=base_url,
        model_name=model_name,
        fast_api_key=fast_api_key,
        fast_base_url=fast_base_url,
        fast_model_name=fast_model_name,
        model_capabilities={
            key: client_params[key]
            for key in ("supports_multimodal", "supports_structured_output")
            if key in client_params
        },
    )
    
    # 返回 SageAsyncOpenAI 实例
    return openai_chat.raw_client


def create_tool_proxy(available_tools: List[str]):
    from sagents.tool.tool_manager import get_tool_manager
    from sagents.tool.tool_proxy import ToolProxy

    if not available_tools:
        return ToolProxy(get_tool_manager(), [])
    logger.info(f"初始化工具代理，可用工具: {available_tools}")
    return ToolProxy(get_tool_manager(), available_tools)


def create_skill_proxy(
    available_skills: List[str],
    user_id: Optional[str] = None,
    agent_workspace: Optional[str] = None,
) -> Tuple[Any, Optional[Any]]:
    from sagents.skill.skill_manager import SkillManager, get_skill_manager
    from sagents.skill.skill_proxy import SkillProxy

    if not available_skills:
        return SkillProxy(get_skill_manager(), []), None

    if _is_desktop_mode():
        logger.info(f"初始化技能代理，可用技能: {available_skills}")
        return SkillProxy(get_skill_manager(), available_skills), None

    cfg = _get_cfg()
    skill_managers = []
    agent_skill_manager = None

    if agent_workspace:
        agent_skills_dir = os.path.join(agent_workspace, "skills")
        if os.path.exists(agent_skills_dir):
            agent_skill_manager = SkillManager(skill_dirs=[agent_skills_dir], isolated=True)
            skill_managers.append(agent_skill_manager)
            logger.info(f"Agent工作区技能目录已加载: {agent_skills_dir}")

    if user_id:
        user_skills_dir = os.path.join(cfg.user_dir, user_id, "skills")
        if os.path.exists(user_skills_dir):
            user_skill_manager = SkillManager(skill_dirs=[user_skills_dir], isolated=True)
            skill_managers.append(user_skill_manager)
            logger.info(f"用户技能目录已加载: {user_skills_dir}")

    if os.path.exists(cfg.skill_dir):
        system_skill_manager = SkillManager(skill_dirs=[cfg.skill_dir], isolated=True)
        skill_managers.append(system_skill_manager)
        logger.info(f"系统技能目录已加载: {cfg.skill_dir}")

    skill_managers.append(get_skill_manager())
    logger.info(
        f"初始化技能代理，可用技能: {available_skills}, 优先级层数: {len(skill_managers)}"
    )
    return SkillProxy(skill_managers, available_skills), agent_skill_manager


def get_sessions_root() -> str:
    if _is_desktop_mode():
        if os.environ.get("SAGE_SESSIONS_PATH"):
            return str(Path(os.environ.get("SAGE_SESSIONS_PATH")))
        return str(Path.home() / ".sage" / "sessions")
    return _get_cfg().session_dir

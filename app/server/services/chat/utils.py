import asyncio
import json
import random
from typing import Any, AsyncGenerator, Dict, List, Tuple

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

def create_skill_proxy(available_skills: List[str]):
    from sagents.skill.skill_manager import get_skill_manager
    from sagents.skill.skill_proxy import SkillProxy
    if not available_skills:
        return SkillProxy(get_skill_manager(), [])
    logger.info(f"初始化技能代理，可用技能: {available_skills}")
    skill_proxy = SkillProxy(get_skill_manager(), available_skills)
    return skill_proxy

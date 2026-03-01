"""
Agent 业务处理模块

封装 Agent 相关的业务逻辑，供路由层调用。
"""

import uuid
from typing import Any, Dict, List, Optional

from loguru import logger
from sagents.tool.tool_manager import get_tool_manager
from sagents.tool.tool_proxy import ToolProxy
from sagents.utils.auto_gen_agent import AutoGenAgentFunc
from sagents.utils.system_prompt_optimizer import SystemPromptOptimizer

from .. import models
from ..core import config
from ..core.client.chat import get_chat_client
from ..core.exceptions import SageHTTPException

# ================= 工具函数 =================


def generate_agent_id() -> str:
    """生成唯一的 Agent ID"""
    return f"agent_{uuid.uuid4().hex[:8]}"


# ================= 业务函数 =================


async def list_agents(user_id: Optional[str] = None) -> List[models.Agent]:
    """获取所有 Agent 的配置并转换为响应结构"""
    dao = models.AgentConfigDao()
    # Admin can see all agents; regular users only see their own OR authorized ones
    all_configs = await dao.get_list_with_auth(user_id)
    return all_configs


async def create_agent(
    agent_name: str, agent_config: Dict[str, Any], user_id: str
) -> models.Agent:
    """创建新的 Agent，返回创建的 Agent 对象"""
    agent_id = generate_agent_id()
    logger.info(f"开始创建Agent: {agent_id}")

    dao = models.AgentConfigDao()
    existing_config = await dao.get_by_name_and_user(agent_name, user_id)
    if existing_config:
        raise SageHTTPException(
            status_code=500,
            detail=f"Agent '{agent_name}' 已存在",
            error_detail=f"Agent '{agent_name}' 已存在",
        )
    orm_obj = models.Agent(agent_id=agent_id, name=agent_name, config=agent_config)
    orm_obj.user_id = user_id
    await dao.save(orm_obj)
    logger.info(f"Agent {agent_id} 创建成功")
    return orm_obj


async def get_agent(agent_id: str, user_id: Optional[str] = None) -> models.Agent:
    """根据 ID 获取 Agent 配置并转换为响应结构"""
    logger.info(f"获取Agent配置: {agent_id}")
    dao = models.AgentConfigDao()
    existing = await dao.get_by_id(agent_id)
    if not existing:
        raise SageHTTPException(
            status_code=500,
            detail=f"Agent '{agent_id}' 不存在",
            error_detail=f"Agent '{agent_id}' 不存在",
        )
    if user_id and existing.user_id != user_id:
        # Check if user is authorized
        authorized_users = await dao.get_authorized_users(agent_id)
        if user_id not in authorized_users:
            raise SageHTTPException(
                status_code=500,
                detail="无权访问该Agent",
                error_detail="forbidden",
            )
    return existing


async def get_agent_authorized_users(agent_id: str, user_id: str, role: str) -> List[str]:
    """Get list of authorized user IDs for an agent"""
    dao = models.AgentConfigDao()
    agent = await dao.get_by_id(agent_id)
    if not agent:
        raise SageHTTPException(status_code=500, detail="Agent不存在", error_detail="not found")
    
    # Only Admin or Owner can view authorized users
    if role != "admin" and agent.user_id != user_id:
        raise SageHTTPException(status_code=500, detail="无权查看授权用户", error_detail="forbidden")
        
    return await dao.get_authorized_users(agent_id)


async def update_agent_authorizations(
    agent_id: str, authorized_user_ids: List[str], user_id: str, role: str
) -> None:
    """Update authorized users for an agent"""
    dao = models.AgentConfigDao()
    agent = await dao.get_by_id(agent_id)
    if not agent:
        raise SageHTTPException(status_code=500, detail="Agent不存在", error_detail="not found")
    
    # Only Admin or Owner can update authorizations
    if role != "admin" and agent.user_id != user_id:
        raise SageHTTPException(status_code=500, detail="无权修改授权", error_detail="forbidden")
    
    # Remove owner from list if present (redundant)
    if agent.user_id in authorized_user_ids:
        authorized_user_ids.remove(agent.user_id)
        
    await dao.update_authorizations(agent_id, authorized_user_ids)


async def update_agent(
    agent_id: str, agent_name: str, agent_config: Dict[str, Any], user_id: Optional[str] = None, role: str = "user"
) -> models.Agent:
    """更新指定 Agent 的配置，返回 Agent 对象"""
    logger.info(f"开始更新Agent: {agent_id}")
    dao = models.AgentConfigDao()
    existing_config = await dao.get_by_id(agent_id)
    if not existing_config:
        raise SageHTTPException(
            status_code=500,
            detail=f"Agent '{agent_id}' 不存在",
            error_detail=f"Agent '{agent_id}' 不存在",
        )
    # Check permission: if user_id is provided, it must match
    if role != "admin" and user_id and existing_config.user_id and existing_config.user_id != user_id:
        raise SageHTTPException(
            status_code=500,
            detail="无权更新该Agent",
            error_detail="forbidden",
        )
    orm_obj = models.Agent(agent_id=agent_id, name=agent_name, config=agent_config)
    # 保留原始创建时间
    orm_obj.created_at = existing_config.created_at
    orm_obj.user_id = existing_config.user_id  # Keep original owner
    await dao.save(orm_obj)
    logger.info(f"Agent {agent_id} 更新成功")
    return orm_obj


async def delete_agent(agent_id: str, user_id: Optional[str] = None, role: str = "user") -> models.Agent:
    """删除指定 Agent，返回删除的 Agent 对象"""
    logger.info(f"开始删除Agent: {agent_id}")
    dao = models.AgentConfigDao()
    existing_config = await dao.get_by_id(agent_id)
    if not existing_config:
        raise SageHTTPException(
            status_code=500,
            detail=f"Agent '{agent_id}' 不存在",
            error_detail=f"Agent '{agent_id}' 不存在",
        )
    if role != "admin" and user_id and existing_config.user_id and existing_config.user_id != user_id:
        raise SageHTTPException(
            status_code=500,
            detail="无权删除该Agent",
            error_detail="forbidden",
        )
    await dao.delete_by_id(agent_id)
    logger.info(f"Agent {agent_id} 删除成功")
    return existing_config


async def auto_generate_agent(
    agent_description: str, available_tools: Optional[List[str]] = None
) -> Dict[str, Any]:
    """自动生成 Agent 配置"""
    logger.info(f"开始自动生成Agent: {agent_description}")
    model_client = get_chat_client()
    server_args = config.get_startup_config()

    auto_gen_func = AutoGenAgentFunc()

    if available_tools:
        logger.info(f"使用指定的工具列表: {available_tools}")
        tool_proxy = ToolProxy(get_tool_manager(), available_tools)
        tool_manager_or_proxy = tool_proxy
    else:
        logger.info("使用完整的工具管理器")
        tool_manager_or_proxy = get_tool_manager()

    agent_config = await auto_gen_func.generate_agent_config(
        agent_description=agent_description,
        tool_manager=tool_manager_or_proxy,
        llm_client=model_client,
        model=server_args.default_llm_model_name,
    )
    agent_config["id"] = ""

    if not agent_config:
        raise SageHTTPException(
            status_code=500,
            detail="自动生成Agent失败",
            error_detail="生成的Agent配置为空",
        )
    logger.info("Agent自动生成成功")
    return agent_config


async def optimize_system_prompt(
    original_prompt: str, optimization_goal: Optional[str] = None
) -> Dict[str, Any]:
    """优化系统提示词"""
    logger.info("开始优化系统提示词")
    model_client = get_chat_client()
    server_args = config.get_startup_config()

    optimizer = SystemPromptOptimizer()
    optimized_prompt = await optimizer.optimize_system_prompt(
        current_prompt=original_prompt,
        optimization_goal=optimization_goal,
        model=server_args.default_llm_model_name,
        llm_client=model_client,
    )

    if not optimized_prompt:
        raise SageHTTPException(
            status_code=500,
            detail="系统提示词优化失败",
            error_detail="优化后的提示词为空",
        )
    result = optimized_prompt
    result["optimization_details"] = {
        "original_length": len(original_prompt),
        "optimized_length": len(optimized_prompt),
        "optimization_goal": optimization_goal,
    }
    logger.info("系统提示词优化成功")
    return result

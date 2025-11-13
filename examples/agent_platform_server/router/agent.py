"""
Agent 相关路由
"""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
from common.render import Response
from sagents.utils.logger import logger

from service.agent import (
    list_agents,
    create_agent,
    get_agent,
    update_agent,
    delete_agent,
    auto_generate_agent,
    optimize_system_prompt,
)


# ============= Agent相关模型 =============


class AgentConfigDTO(BaseModel):
    id: Optional[str] = None
    name: str
    systemPrefix: Optional[str] = None
    systemContext: Optional[Dict[str, Any]] = None
    availableWorkflows: Optional[Dict[str, List[str]]] = None
    availableTools: Optional[List[str]] = None
    maxLoopCount: Optional[int] = 10
    deepThinking: Optional[bool] = False
    llmConfig: Optional[Dict[str, Any]] = None
    multiAgent: Optional[bool] = False
    description: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class AutoGenAgentRequest(BaseModel):
    agent_description: str  # Agent描述
    available_tools: Optional[List[str]] = (
        None  # 可选的工具名称列表，如果提供则只使用这些工具
    )


class SystemPromptOptimizeRequest(BaseModel):
    original_prompt: str  # 原始系统提示词
    optimization_goal: Optional[str] = None  # 优化目标（可选）


def convert_config_to_agent(agent_id: str, config: Dict[str, Any]) -> AgentConfigDTO:
    """将配置字典转换为 AgentConfigResp 对象"""
    return AgentConfigDTO(
        id=agent_id,
        name=config.get("name", f"Agent {agent_id}"),
        systemPrefix=config.get("systemPrefix") or config.get("system_prefix"),
        systemContext=config.get("systemContext") or config.get("system_context"),
        availableWorkflows=config.get("availableWorkflows")
        or config.get("available_workflows"),
        availableTools=config.get("availableTools") or config.get("available_tools"),
        maxLoopCount=config.get("maxLoopCount") or config.get("max_loop_count", 10),
        deepThinking=config.get("deepThinking") or config.get("deep_thinking", False),
        multiAgent=config.get("multiAgent") or config.get("multi_agent", False),
        description=config.get("description"),
        created_at=config.get("created_at"),
        updated_at=config.get("updated_at"),
        llmConfig=config.get("llmConfig", {}),
    )


def convert_agent_to_config(agent: AgentConfigDTO) -> Dict[str, Any]:
    """将 AgentConfigResp 对象转换为配置字典"""
    config = {
        "name": agent.name,
        "systemPrefix": agent.systemPrefix,
        "systemContext": agent.systemContext,
        "availableWorkflows": agent.availableWorkflows,
        "availableTools": agent.availableTools,
        "maxLoopCount": agent.maxLoopCount,
        "deepThinking": agent.deepThinking,
        "multiAgent": agent.multiAgent,
        "description": agent.description,
        "created_at": agent.created_at,
        "updated_at": agent.updated_at,
        "llmConfig": agent.llmConfig,
    }
    # 去除 None 值，保持存储整洁
    return {k: v for k, v in config.items() if v is not None}


# 创建路由器
agent_router = APIRouter(prefix="/api/agent", tags=["Agent"])


@agent_router.get("/list")
async def list():
    """
    获取所有Agent配置

    Returns:
        StandardResponse: 包含所有Agent配置的标准响应
    """
    # 从 handler 获取数据
    all_configs = await list_agents()
    agents_data: List[Dict[str, Any]] = []
    for agent in all_configs:
        agent_id = agent.agent_id
        agent_resp = convert_config_to_agent(agent_id, agent.config)
        agents_data.append(agent_resp.model_dump())
    logger.info(f"成功获取 {len(agents_data)} 个Agent配置")
    return await Response.succ(
        data=agents_data, message=f"成功获取 {len(agents_data)} 个Agent配置"
    )


@agent_router.post("/create")
async def create(agent: AgentConfigDTO):
    """
    创建新的Agent

    Args:
        agent: Agent配置对象

    Returns:
        StandardResponse: 包含操作结果的标准响应
    """
    agent_id = await create_agent(agent.name, convert_agent_to_config(agent))
    return await Response.succ(
        data={"agent_id": agent_id}, message=f"Agent '{agent_id}' 创建成功"
    )


@agent_router.get("/{agent_id}")
async def get(agent_id: str):
    """
    根据ID获取Agent配置

    Args:
        agent_id: Agent ID

    Returns:
        StandardResponse: 包含Agent配置的标准响应
    """
    agent = await get_agent(agent_id)
    agent_resp = convert_config_to_agent(agent_id, agent)
    return await Response.succ(
        data={"agent": agent_resp.model_dump()}, message=f"获取Agent '{agent_id}' 成功"
    )


@agent_router.put("/{agent_id}")
async def update(agent_id: str, agent: AgentConfigDTO):
    """
    更新Agent配置

    Args:
        agent_id: Agent ID
        agent: 更新的Agent配置

    """
    await update_agent(agent_id, agent.name, convert_agent_to_config(agent))
    return await Response.succ(
        data={"agent_id": agent_id}, message=f"Agent '{agent_id}' 更新成功"
    )


@agent_router.delete("/{agent_id}")
async def delete(agent_id: str):
    """
    删除Agent

    Args:
        agent_id: Agent ID

    """
    await delete_agent(agent_id)
    return await Response.succ(
        data={"agent_id": agent_id}, message=f"Agent '{agent_id}' 删除成功"
    )


@agent_router.post("/auto-generate")
async def auto_generate(request: AutoGenAgentRequest):
    """
    自动生成Agent

    Args:
        request: 自动生成Agent请求

    """
    agent_config = await auto_generate_agent(
        agent_description=request.agent_description,
        available_tools=request.available_tools,
    )
    return await Response.succ(
        data={"agent": agent_config}, message="Agent自动生成成功"
    )


@agent_router.post("/system-prompt/optimize")
async def optimize(request: SystemPromptOptimizeRequest):
    """
    优化系统提示词

    Args:
        request: 系统提示词优化请求

    Returns:
        StandardResponse: 包含优化后的系统提示词的标准响应
    """
    res = await optimize_system_prompt(
        original_prompt=request.original_prompt,
        optimization_goal=request.optimization_goal,
    )
    return await Response.succ(data=res, message="系统提示词优化成功")

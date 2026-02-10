"""
Agent 相关路由
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..core.render import Response
from ..services.agent import (
    auto_generate_agent,
    create_agent,
    delete_agent,
    get_agent,
    list_agents,
    optimize_system_prompt,
    update_agent,
)
from sagents.utils.prompt_manager import PromptManager

# ============= Agent相关模型 =============


class AgentConfigDTO(BaseModel):
    id: Optional[str] = None
    user_id: Optional[str] = None
    name: str
    systemPrefix: Optional[str] = None
    systemContext: Optional[Dict[str, Any]] = None
    availableWorkflows: Optional[Dict[str, List[str]]] = None
    availableTools: Optional[List[str]] = None
    availableSkills: Optional[List[str]] = None
    availableKnowledgeBases: Optional[List[str]] = None
    memoryType: Optional[str] = None
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


def convert_config_to_agent(
    agent_id: str, config: Dict[str, Any], user_id: Optional[str] = None
) -> AgentConfigDTO:
    """将配置字典转换为 AgentConfigResp 对象"""
    return AgentConfigDTO(
        id=agent_id,
        user_id=user_id,
        name=config.get("name", f"Agent {agent_id}"),
        systemPrefix=config.get("systemPrefix") or config.get("system_prefix"),
        systemContext=config.get("systemContext") or config.get("system_context"),
        availableWorkflows=config.get("availableWorkflows")
        or config.get("available_workflows"),
        availableTools=config.get("availableTools") or config.get("available_tools"),
        availableSkills=config.get("availableSkills") or config.get("available_skills"),
        availableKnowledgeBases=config.get("availableKnowledgeBases")
        or config.get("available_knowledge_bases"),
        memoryType=config.get("memoryType") or config.get("memory_type"),
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
        "availableSkills": agent.availableSkills,
        "availableKnowledgeBases": agent.availableKnowledgeBases,
        "memoryType": agent.memoryType,
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
async def list(http_request: Request):
    """
    获取所有Agent配置

    Returns:
        StandardResponse: 包含所有Agent配置的标准响应
    """
    all_configs = await list_agents()
    agents_data: List[Dict[str, Any]] = []
    for agent in all_configs:
        agent_id = agent.agent_id
        agent_resp = convert_config_to_agent(agent_id, agent.config, agent.user_id)
        agents_data.append(agent_resp.model_dump())
    # 根据agent名称排序
    agents_data.sort(key=lambda x: x["name"])
    return await Response.succ(
        data=agents_data, message=f"成功获取 {len(agents_data)} 个Agent配置"
    )


@agent_router.get("/template/default_system_prompt")
async def get_default_system_prompt(language: str = "zh"):
    """
    获取默认的System Prompt模板（用于创建空白Agent时的初始草稿）

    Args:
        language: 语言代码，默认为zh

    Returns:
        StandardResponse: 包含默认System Prompt的内容
    """
    try:
        content = PromptManager().get_prompt(
            'agent_intro_template',
            agent='common',
            language=language,
            default=""
        )
        # 如果是模板格式（包含{agent_name}），可以预填一个默认值或者保留占位符
        # 这里为了作为草稿，我们预填 Sage
        if "{agent_name}" in content:
            content = content.format(agent_name="Sage")
            
        return await Response.succ(
            data={"content": content},
            message="成功获取默认System Prompt模板"
        )
    except Exception as e:
        return await Response.error(
            message=f"获取默认System Prompt模板失败: {str(e)}"
        )


@agent_router.post("/create")
async def create(agent: AgentConfigDTO, http_request: Request):
    """
    创建新的Agent

    Args:
        agent: Agent配置对象

    Returns:
        StandardResponse: 包含操作结果的标准响应
    """
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    created_agent = await create_agent(agent.name, convert_agent_to_config(agent), user_id)
    return await Response.succ(
        data={"agent_id": created_agent.agent_id}, message=f"Agent '{created_agent.agent_id}' 创建成功"
    )


@agent_router.get("/{agent_id}")
async def get(agent_id: str, http_request: Request):
    """
    根据ID获取Agent配置

    Args:
        agent_id: Agent ID

    Returns:
        StandardResponse: 包含Agent配置的标准响应
    """
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    agent = await get_agent(agent_id, user_id)
    agent_resp = convert_config_to_agent(agent_id, agent.config, agent.user_id)
    return await Response.succ(
        data={"agent": agent_resp.model_dump()}, message=f"获取Agent '{agent_id}' 成功"
    )


@agent_router.put("/{agent_id}")
async def update(agent_id: str, agent: AgentConfigDTO, http_request: Request):
    """
    更新Agent配置

    Args:
        agent_id: Agent ID
        agent: 更新的Agent配置

    """
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    role = claims.get("role") or "user"
    await update_agent(agent_id, agent.name, convert_agent_to_config(agent), user_id, role)
    return await Response.succ(
        data={"agent_id": agent_id}, message=f"Agent '{agent_id}' 更新成功"
    )


@agent_router.delete("/{agent_id}")
async def delete(agent_id: str, http_request: Request):
    """
    删除Agent

    Args:
        agent_id: Agent ID

    """
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    role = claims.get("role") or "user"
    await delete_agent(agent_id, user_id, role)
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

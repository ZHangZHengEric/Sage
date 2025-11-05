"""
Agent 相关路由

提供Agent的管理接口，包括创建、更新、删除、列表等功能，
以及自动生成Agent和系统提示词优化功能
"""

import uuid
from typing import Dict, Any
from fastapi import APIRouter
from sagents.utils.logger import logger
from sagents.utils.auto_gen_agent import AutoGenAgentFunc
from sagents.utils.system_prompt_optimizer import SystemPromptOptimizer
from sagents.tool.tool_proxy import ToolProxy

from entities.entities import ( Response, 
    AgentConfig, AutoGenAgentRequest,
    SystemPromptOptimizeRequest,
     SageHTTPException
)
import globals.variables as global_vars

# 创建路由器
agent_router = APIRouter(prefix="/api/agent", tags=["Agent"])

@agent_router.get("/list")
async def get_agents():
    """
    获取所有Agent配置
    
    Returns:
        StandardResponse: 包含所有Agent配置的标准响应
    """
    # 获取数据库管理器
    db_manager = global_vars.get_database_manager()
    
    # 获取所有Agent配置
    all_configs = await db_manager.get_all_agent_configs()
    # 转换为响应格式
    agents_data = []
    # 如果返回的是列表格式 [config1, config2, ...]
    for agent in all_configs:
        agent_id = agent.agent_id
        agent_config = convert_config_to_agent(agent_id, agent.config)
        agents_data.append(agent_config)
    return await Response.succ(
        data=agents_data,
        message=f"成功获取 {len(agents_data)} 个Agent配置"
    )

@agent_router.post("/create")
async def create_agent(
    agent: AgentConfig
):
    """
    创建新的Agent
    
    Args:
        agent: Agent配置对象
        
    Returns:
        StandardResponse: 包含操作结果的标准响应
    """
    agent.id = generate_agent_id()
    logger.info(f"开始创建Agent: {agent.id}")
    
    # 获取数据库管理器
    db_manager = global_vars.get_database_manager()
    
    # 检查Agent是否已存在
    existing_config = await db_manager.get_agent_config(agent.id)
    if existing_config:
        raise SageHTTPException(
            status_code=400,
            detail=f"Agent '{agent.id}' 已存在",
            error_detail=f"Agent '{agent.id}' 已存在"
        )
    
    # 转换为数据库格式并保存
    agent_config = convert_agent_to_config(agent)
    await db_manager.save_agent_config(agent.id, agent.name, agent_config)
    
    logger.info(f"Agent {agent.id} 创建成功")
    return await Response.succ(
        data={"agent_id": agent.id},
        message=f"Agent '{agent.id}' 创建成功"
    )


@agent_router.get("/{agent_id}")
async def get_agent(
    agent_id: str):
    """
    根据ID获取Agent配置
    
    Args:
        agent_id: Agent ID
        
    Returns:
        StandardResponse: 包含Agent配置的标准响应
    """
    logger.info(f"获取Agent配置: {agent_id}")
    
    # 获取数据库管理器
    db_manager = global_vars.get_database_manager()
    
    # 从数据库获取Agent配置
    agent_config = await db_manager.get_agent_config(agent_id)
    if not agent_config:
        raise SageHTTPException(
            status_code=404,
            detail=f"Agent '{agent_id}' 不存在",
            error_detail=f"Agent '{agent_id}' 不存在"
        )
    
    # 转换为Agent模型
    agent = convert_config_to_agent(agent_id, agent_config)
    
    return await Response.succ(
        data={"agent": agent.model_dump()},
        message=f"获取Agent '{agent_id}' 成功"
    )


@agent_router.put("/{agent_id}")
async def update_agent(
    agent_id: str,
    agent: AgentConfig
):
    """
    更新Agent配置
    
    Args:
        agent_id: Agent ID
        agent: 更新的Agent配置

    """
    logger.info(f"开始更新Agent: {agent_id}")
    
    # 获取数据库管理器
    db_manager = global_vars.get_database_manager()
    
    # 检查Agent是否存在
    existing_config = await db_manager.get_agent_config(agent_id)
    if not existing_config:
        raise SageHTTPException(
            status_code=404,
            detail=f"Agent '{agent_id}' 不存在",
            error_detail=f"Agent '{agent_id}' 不存在"
        )
    
    # 转换为数据库格式并保存
    agent_config = convert_agent_to_config(agent)
    await db_manager.save_agent_config(agent_id, agent.name, agent_config)
    
    logger.info(f"Agent {agent_id} 更新成功")
    return await Response.succ(
        data={"agent_id": agent_id},
        message=f"Agent '{agent_id}' 更新成功"
    )


@agent_router.delete("/{agent_id}")
async def delete_agent(
    agent_id: str
):
    """
    删除Agent
    
    Args:
        agent_id: Agent ID

    """
    logger.info(f"开始删除Agent: {agent_id}")
    
    # 获取数据库管理器
    db_manager = global_vars.get_database_manager()
    
    # 检查Agent是否存在
    existing_config = await db_manager.get_agent_config(agent_id)
    if not existing_config:
        raise SageHTTPException(
            status_code=404,
            detail=f"Agent '{agent_id}' 不存在",
            error_detail=f"Agent '{agent_id}' 不存在"
        )
    
    # 从数据库删除
    await db_manager.delete_agent_config(agent_id)
    
    logger.info(f"Agent {agent_id} 删除成功")
    return await Response.succ(
        data={"agent_id": agent_id},
        message=f"Agent '{agent_id}' 删除成功"
    )


@agent_router.post("/auto-generate")
async def auto_generate_agent(
    request: AutoGenAgentRequest
):
    """
    自动生成Agent
    
    Args:
        request: 自动生成Agent请求

    """
    logger.info(f"开始自动生成Agent: {request.agent_description}")
    
    # 获取模型客户端
    model_client = global_vars.get_default_model_client()
    
    # 使用自动生成工具
    auto_gen_func = AutoGenAgentFunc()
            
    # 根据是否提供工具列表决定使用ToolManager还是ToolProxy
    if request.available_tools:
        logger.info(f"使用指定的工具列表: {request.available_tools}")
        # 创建ToolProxy，只包含指定的工具
        tool_proxy = ToolProxy(global_vars.get_tool_manager(), request.available_tools)
        tool_manager_or_proxy = tool_proxy
    else:
        logger.info("使用完整的工具管理器")
        tool_manager_or_proxy = global_vars.get_tool_manager()
    
    # 生成Agent配置
    agent_config = auto_gen_func.generate_agent_config(
        agent_description=request.agent_description,
        tool_manager=tool_manager_or_proxy,
        llm_client=model_client,
        model="qwen-plus",
    )
    agent_config["id"] = ''
    
    if not agent_config:
        raise SageHTTPException(
            status_code=400,
            detail="自动生成Agent失败",
            error_detail="生成的Agent配置为空"
        )
    
    logger.info("Agent自动生成成功")
    return await Response.succ(
        data={"agent": agent_config},
        message="Agent自动生成成功"
    )


@agent_router.post("/system-prompt/optimize")
async def optimize_system_prompt(
    request: SystemPromptOptimizeRequest
):
    """
    优化系统提示词
    
    Args:
        request: 系统提示词优化请求
        
    Returns:
        StandardResponse: 包含优化后的系统提示词的标准响应
    """
    logger.info("开始优化系统提示词")
    
    # 获取模型客户端
    model_client = global_vars.get_default_model_client()
    
    # 使用系统提示词优化器
    optimizer = SystemPromptOptimizer(model_client)
    
    # 优化系统提示词
    optimized_prompt = optimizer.optimize_system_prompt(
        original_prompt=request.original_prompt,
        optimization_goals=request.optimization_goals,
    )
    
    if not optimized_prompt:
        raise SageHTTPException(
            status_code=400,
            detail="系统提示词优化失败",
            error_detail="优化后的提示词为空"
        )
    
    logger.info("系统提示词优化成功")
    return await Response.succ(
        data={"optimized_prompt": optimized_prompt},
        message="系统提示词优化成功"
    )




def generate_agent_id() -> str:
    """生成agent ID"""
    return f"agent_{uuid.uuid4().hex[:8]}"


def convert_config_to_agent(agent_id: str, config: Dict[str, Any]) -> AgentConfig:
    """将配置字典转换为AgentConfig对象"""
    return AgentConfig(
        id=agent_id,
        name=config.get("name", f"Agent {agent_id}"),
        systemPrefix=config.get("systemPrefix") or config.get("system_prefix"),
        systemContext=config.get("systemContext") or config.get("system_context"),
        availableWorkflows=config.get("availableWorkflows") or config.get("available_workflows"),
        availableTools=config.get("availableTools") or config.get("available_tools"),
        maxLoopCount=config.get("maxLoopCount") or config.get("max_loop_count", 10),
        deepThinking=config.get("deepThinking") or config.get("deep_thinking", False),
        multiAgent=config.get("multiAgent") or config.get("multi_agent", False),
        description=config.get("description"),
        created_at=config.get("created_at"),
        updated_at=config.get("updated_at"),
        llmConfig=config.get("llmConfig")
    )


def convert_agent_to_config(agent: AgentConfig) -> Dict[str, Any]:
    """将AgentConfig对象转换为配置字典"""
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
        "llmConfig": agent.llmConfig
    }
    
    # 移除None值
    return {k: v for k, v in config.items() if v is not None}

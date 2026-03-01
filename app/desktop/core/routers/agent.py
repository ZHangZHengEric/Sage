"""
Agent 相关路由
"""

import os
import mimetypes
import tempfile
import zipfile
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from loguru import logger
from pydantic import BaseModel

from ..core.render import Response
from ..core.exceptions import SageHTTPException
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
    name: str
    systemPrefix: Optional[str] = None
    systemContext: Optional[Dict[str, Any]] = None
    availableWorkflows: Optional[Dict[str, List[str]]] = None
    availableTools: Optional[List[str]] = None
    availableSubAgentIds: Optional[List[str]] = None
    availableSkills: Optional[List[str]] = None
    memoryType: Optional[str] = None
    maxLoopCount: Optional[int] = 10
    deepThinking: Optional[bool] = False
    llm_provider_id: Optional[str] = None
    multiAgent: Optional[bool] = False
    agentMode: Optional[str] = None
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
    agent_id: str, config: Dict[str, Any]
) -> AgentConfigDTO:
    """将配置字典转换为 AgentConfigResp 对象"""
    
    return AgentConfigDTO(
        id=agent_id,
        name=config.get("name", f"Agent {agent_id}"),
        systemPrefix=config.get("systemPrefix") or config.get("system_prefix"),
        systemContext=config.get("systemContext") or config.get("system_context"),
        availableWorkflows=config.get("availableWorkflows")
        or config.get("available_workflows"),
        availableTools=config.get("availableTools") or config.get("available_tools"),
        availableSubAgentIds=config.get("availableSubAgentIds") or config.get("available_sub_agent_ids"),
        availableSkills=config.get("availableSkills") or config.get("available_skills"),

        memoryType=config.get("memoryType") or config.get("memory_type"),
        maxLoopCount=config.get("maxLoopCount") or config.get("max_loop_count", 10),
        deepThinking=config.get("deepThinking") or config.get("deep_thinking", False),
        multiAgent=config.get("multiAgent") or config.get("multi_agent", False),
        agentMode=config.get("agentMode") or config.get("agent_mode"),
        description=config.get("description"),
        created_at=config.get("created_at"),
        updated_at=config.get("updated_at"),
        llm_provider_id=config.get("llm_provider_id"),
    )


def convert_agent_to_config(agent: AgentConfigDTO) -> Dict[str, Any]:
    """将 AgentConfigResp 对象转换为配置字典"""
    config = {
        "name": agent.name,
        "systemPrefix": agent.systemPrefix,
        "systemContext": agent.systemContext,
        "availableWorkflows": agent.availableWorkflows,
        "availableTools": agent.availableTools,
        "availableSubAgentIds": agent.availableSubAgentIds,
        "availableSkills": agent.availableSkills,
        "memoryType": agent.memoryType,
        "maxLoopCount": agent.maxLoopCount,
        "deepThinking": agent.deepThinking,
        "multiAgent": agent.multiAgent,
        "agentMode": agent.agentMode,
        "description": agent.description,
        "created_at": agent.created_at,
        "updated_at": agent.updated_at,
        "llm_provider_id": agent.llm_provider_id,
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
        agent_resp = convert_config_to_agent(agent_id, agent.config)
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
        content = ""
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
    created_agent = await create_agent(agent.name, convert_agent_to_config(agent))
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
    agent = await get_agent(agent_id)
    agent_resp = convert_config_to_agent(agent.agent_id, agent.config)
    return await Response.succ(data=agent_resp.model_dump(), message="成功获取Agent配置")


@agent_router.put("/{agent_id}")
async def update(agent_id: str, agent: AgentConfigDTO, http_request: Request):
    """
    更新Agent配置

    Args:
        agent_id: Agent ID
        agent: Agent配置对象

    Returns:
        StandardResponse: 包含操作结果的标准响应
    """
    await update_agent(agent_id, agent.name, convert_agent_to_config(agent))
    return await Response.succ(
        data={"agent_id": agent_id}, message=f"Agent '{agent_id}' 更新成功"
    )


@agent_router.delete("/{agent_id}")
async def delete(agent_id: str, http_request: Request):
    """
    删除Agent

    Args:
        agent_id: Agent ID

    Returns:
        StandardResponse: 包含操作结果的标准响应
    """
    await delete_agent(agent_id)
    return await Response.succ(data={"agent_id": agent_id}, message=f"Agent '{agent_id}' 删除成功")


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


@agent_router.post("/{agent_id}/file_workspace")
async def get_workspace(agent_id: str, request: Request):
    """获取指定Agent的文件工作空间"""
    workspace_path = os.path.expanduser(f"~/.sage/{agent_id}/")

    if not workspace_path or not os.path.exists(workspace_path):
        return await Response.succ(
             message="工作空间为空",
             data={
                "agent_id": agent_id,
                "files": [],
                "message": "工作空间为空",
            }
        )

    files: List[Dict[str, Any]] = []
    for root, dirs, filenames in os.walk(workspace_path):
        # 过滤掉隐藏文件和文件夹
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        filenames = [f for f in filenames if not f.startswith(".")]
        for filename in filenames:
            file_path = os.path.join(root, filename)
            relative_path = os.path.relpath(file_path, workspace_path)
            file_stat = os.stat(file_path)
            files.append(
                {
                    "name": filename,
                    "path": relative_path,
                    "size": file_stat.st_size,
                    "modified_time": file_stat.st_mtime,
                    "is_directory": False,
                }
            )

        for dirname in dirs:
            dir_path = os.path.join(root, dirname)
            relative_path = os.path.relpath(dir_path, workspace_path)
            files.append(
                {
                    "name": dirname,
                    "path": relative_path,
                    "size": 0,
                    "modified_time": os.stat(dir_path).st_mtime,
                    "is_directory": True,
                }
            )

    logger.bind(agent_id=agent_id).info(f"获取工作空间文件数量：{len(files)}")
    result = {
        "agent_id": agent_id,
        "files": files,
        "message": "获取文件列表成功",
    }
    return await Response.succ(message=result.get("message", "获取文件列表成功"), data={**result})


@agent_router.get("/{agent_id}/file_workspace/download")
async def download_file(agent_id: str, request: Request):
    file_path = request.query_params.get("file_path")
    logger.bind(agent_id=agent_id).info(f"Download request: file_path={file_path}")
    
    workspace_path = os.path.expanduser(f"~/.sage/{agent_id}/")

    try:
        # Resolve path logic
        if not workspace_path or not file_path:
             raise SageHTTPException(status_code=500, detail="缺少必要的路径参数")
        
        full_file_path = os.path.join(workspace_path, file_path)
        if not os.path.abspath(full_file_path).startswith(os.path.abspath(workspace_path)):
             raise SageHTTPException(status_code=500, detail="访问被拒绝：文件路径超出工作空间范围")
        
        if not os.path.exists(full_file_path):
             raise SageHTTPException(status_code=500, detail=f"文件不存在: {file_path}")
             
        path = full_file_path
        
        # Directory zip logic
        if os.path.isdir(path):
            temp_dir = tempfile.gettempdir()
            zip_filename = f"{os.path.basename(path)}.zip"
            zip_path = os.path.join(temp_dir, zip_filename)
            
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(path):
                    for file in files:
                        file_abs_path = os.path.join(root, file)
                        rel_path = os.path.relpath(file_abs_path, path)
                        zipf.write(file_abs_path, rel_path)
            
            path = zip_path
            filename = zip_filename
            media_type = "application/zip"
        else:
            filename = os.path.basename(path)
            media_type, _ = mimetypes.guess_type(path)
            if media_type is None:
                media_type = "application/octet-stream"

        logger.bind(agent_id=agent_id).info(f"Download resolved: path={path}")
        return FileResponse(
            path=path, filename=filename, media_type=media_type
        )
    except Exception as e:
        logger.bind(agent_id=agent_id).error(f"Download failed: {e}")
        raise



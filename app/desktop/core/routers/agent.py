"""
Agent 相关路由
"""

import os
import mimetypes
import tempfile
import zipfile
from typing import Any, Dict, List, Optional
from pathlib import Path

from fastapi import APIRouter, Request, UploadFile, File
from fastapi.responses import FileResponse
from loguru import logger
from pydantic import BaseModel
import shutil

from common.core.exceptions import SageHTTPException
from common.core.render import Response
from common.models.agent import AgentConfigDao
from common.schemas.agent import AgentAbilitiesRequest, AgentAbilitiesData
from ..services.agent import (
    auto_generate_agent,
    create_agent,
    delete_agent,
    get_agent,
    import_openclaw_agent,
    list_agents,
    optimize_system_prompt,
    update_agent,
    generate_agent_abilities as generate_agent_abilities_service,
)
from sagents.utils.agent_abilities import AgentAbilitiesGenerationError
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
    enableMultimodal: Optional[bool] = False
    multiAgent: Optional[bool] = False
    agentMode: Optional[str] = None
    description: Optional[str] = None
    is_default: Optional[bool] = False
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    im_channels: Optional[Dict[str, Dict[str, Any]]] = None  # IM 渠道配置


class AutoGenAgentRequest(BaseModel):
    agent_description: str  # Agent描述
    available_tools: Optional[List[str]] = (
        None  # 可选的工具名称列表，如果提供则只使用这些工具
    )


class SystemPromptOptimizeRequest(BaseModel):
    original_prompt: str  # 原始系统提示词
    optimization_goal: Optional[str] = None  # 优化目标（可选）


def convert_config_to_agent(
    agent_id: str,
    config: Dict[str, Any],
    is_default: bool = False,
    agent_name: Optional[str] = None,
) -> AgentConfigDTO:
    """将配置字典转换为 AgentConfigResp 对象"""

    return AgentConfigDTO(
        id=agent_id,
        name=agent_name or config.get("name") or f"Agent {agent_id}",
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
        enableMultimodal=config.get("enableMultimodal") or config.get("enable_multimodal", False),
        multiAgent=config.get("multiAgent") or config.get("multi_agent", False),
        agentMode=config.get("agentMode") or config.get("agent_mode"),
        description=config.get("description"),
        is_default=is_default,
        created_at=config.get("created_at"),
        updated_at=config.get("updated_at"),
        llm_provider_id=config.get("llm_provider_id"),
    )


def convert_agent_to_config(agent: AgentConfigDTO) -> Dict[str, Any]:
    """将 AgentConfigResp 对象转换为配置字典"""
    logger.info(f"[convert_agent_to_config] Input: is_default={agent.is_default}, type={type(agent.is_default)}")
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
        "enableMultimodal": agent.enableMultimodal,
        "multiAgent": agent.multiAgent,
        "agentMode": agent.agentMode,
        "description": agent.description,
        "is_default": agent.is_default,
        "created_at": agent.created_at,
        "updated_at": agent.updated_at,
        "llm_provider_id": agent.llm_provider_id,
    }
    # 去除 None 值，保持存储整洁
    result = {k: v for k, v in config.items() if v is not None}
    logger.info(f"[convert_agent_to_config] Output: is_default={result.get('is_default')}")
    return result


# 创建路由器
agent_router = APIRouter(prefix="/api/agent", tags=["Agent"])

def _resolve_workspace_file_path(workspace_path: Path, file_path: str) -> str:
    if not workspace_path or not file_path:
        raise SageHTTPException(status_code=500, detail="缺少必要的路径参数")
    full_file_path = os.path.join(workspace_path, file_path)
    workspace_abs = os.path.normcase(os.path.abspath(workspace_path))
    full_file_abs = os.path.normcase(os.path.abspath(full_file_path))
    try:
        in_workspace = os.path.commonpath([workspace_abs, full_file_abs]) == workspace_abs
    except ValueError:
        in_workspace = False
    if not in_workspace:
        raise SageHTTPException(status_code=500, detail="访问被拒绝：文件路径超出工作空间范围")
    if not os.path.exists(full_file_abs):
        raise SageHTTPException(status_code=500, detail=f"文件不存在: {file_path}")
    return full_file_abs


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
        agent_resp = convert_config_to_agent(
            agent_id,
            agent.config,
            agent.is_default,
            agent_name=agent.name,
        )
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
    logger.info(f"[Agent Create] Received: id={agent.id}, name={agent.name}, is_default={agent.is_default}, im_channels={agent.im_channels}")

    # 检查是否有启用的 IM 频道，如果有则自动添加 IM 工具
    im_tools = ['send_message_through_im', 'send_file_through_im', 'send_image_through_im']
    has_enabled_im_channel = False

    if agent.im_channels:
        for provider, channel_data in agent.im_channels.items():
            if channel_data.get('enabled', False):
                has_enabled_im_channel = True
                break

    if has_enabled_im_channel:
        # 确保 availableTools 存在
        if agent.availableTools is None:
            agent.availableTools = []

        # 检查并添加缺失的 IM 工具
        tools_added = []
        for tool_name in im_tools:
            if tool_name not in agent.availableTools:
                agent.availableTools.append(tool_name)
                tools_added.append(tool_name)

        if tools_added:
            logger.info(f"[Agent Create] Auto-added IM tools for agent={agent.id}: {tools_added}")

    config_dict = convert_agent_to_config(agent)
    logger.info(f"[Agent Create] Config dict: is_default={config_dict.get('is_default')}")
    created_agent = await create_agent(agent.name, config_dict)
    return await Response.succ(
        data={"agent_id": created_agent.agent_id}, message=f"Agent '{created_agent.agent_id}' 创建成功"
    )


@agent_router.post("/import-openclaw")
async def import_openclaw(http_request: Request):
    """一键导入 OpenClaw 数据并创建对应 Agent。"""
    result = await import_openclaw_agent()

    skill_count = result.get("linked_skill_count", 0)
    if skill_count > 0:
        message = f"已导入 OpenClaw workspace，并关联 {skill_count} 个 skills"
    else:
        message = "已导入 OpenClaw workspace，未发现可关联的 skills"

    return await Response.succ(data=result, message=message)


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
    agent_resp = convert_config_to_agent(
        agent.agent_id,
        agent.config,
        agent.is_default,
        agent_name=agent.name,
    )
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
    logger.info(f"[Agent Update] Received update for agent={agent_id}, im_channels={agent.im_channels}")

    # 检查是否有启用的 IM 频道，如果有则自动添加 IM 工具
    im_tools = ['send_message_through_im', 'send_file_through_im', 'send_image_through_im']
    has_enabled_im_channel = False

    if agent.im_channels:
        for provider, channel_data in agent.im_channels.items():
            if channel_data.get('enabled', False):
                has_enabled_im_channel = True
                break

    if has_enabled_im_channel:
        # 确保 availableTools 存在
        if agent.availableTools is None:
            agent.availableTools = []

        # 检查并添加缺失的 IM 工具
        tools_added = []
        for tool_name in im_tools:
            if tool_name not in agent.availableTools:
                agent.availableTools.append(tool_name)
                tools_added.append(tool_name)

        if tools_added:
            logger.info(f"[Agent Update] Auto-added IM tools for agent={agent_id}: {tools_added}")

    # 更新 Agent 基本信息
    await update_agent(agent_id, agent.name, convert_agent_to_config(agent))
    
    # 保存 IM 渠道配置（如果存在）
    if agent.im_channels:
        logger.info(f"[Agent Update] Saving IM channels: {agent.im_channels}")
        try:
            from mcp_servers.im_server.agent_config import get_agent_im_config, find_agent_by_provider_id
            agent_config = get_agent_im_config(agent_id)
            
            # ID 字段映射
            id_field_map = {
                "wechat_work": "bot_id",
                "dingtalk": "client_id",
                "feishu": "app_id"
            }
            
            for provider, channel_data in agent.im_channels.items():
                enabled = channel_data.get('enabled', False)
                config = channel_data.get('config', {})
                
                # 验证 iMessage 只能在默认 Agent 上启用
                if provider == 'imessage' and enabled:
                    dao = AgentConfigDao()
                    agent_obj = await dao.get_by_id(agent_id)
                    if agent_obj and not agent_obj.is_default:
                        logger.warning(f"[Agent Update] iMessage can only be configured on default agent, skipping {agent_id}")
                        continue
                
                # 检查重复配置（仅对启用的渠道）
                if enabled:
                    id_field = id_field_map.get(provider)
                    if id_field and config:
                        id_value = config.get(id_field)
                        if id_value:
                            existing_agent = find_agent_by_provider_id(provider, id_value, exclude_agent_id=agent_id)
                            if existing_agent:
                                error_msg = f"{provider} 的 {id_field} '{id_value}' 已在 Agent '{existing_agent}' 配置，请勿重复配置"
                                logger.warning(f"[Agent Update] Duplicate {provider} {id_field} detected: {id_value} between agents {agent_id} and {existing_agent}")
                                return await Response.error(code=400, message=error_msg)
                
                # 保存渠道配置
                success = agent_config.set_provider_config(provider, enabled, config)
                if success:
                    logger.info(f"[Agent Update] Saved {provider} config for agent={agent_id}, enabled={enabled}")
                    
                    # 如果启用，启动 IM 渠道
                    if enabled:
                        try:
                            from mcp_servers.im_server.service_manager import get_service_manager
                            service_manager = get_service_manager()
                            logger.info(f"[Agent Update] Starting {provider} channel for agent={agent_id}")
                            await service_manager.start_channel(agent_id, provider)
                        except Exception as e:
                            logger.error(f"[Agent Update] Failed to start {provider} channel: {e}")
                else:
                    logger.error(f"[Agent Update] Failed to save {provider} config for agent={agent_id}")
        except Exception as e:
            logger.error(f"[Agent Update] Failed to save IM channels: {e}")
            # 不阻断主流程，仅记录错误
    
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


@agent_router.post("/{agent_id}/set-default")
async def set_default_agent(agent_id: str, http_request: Request):
    """
    设置指定 Agent 为默认 Agent

    Args:
        agent_id: Agent ID

    Returns:
        StandardResponse: 包含操作结果的标准响应
    """
    # 先检查 Agent 是否存在
    agent = await get_agent(agent_id)
    if not agent:
        return await Response.error(message=f"Agent '{agent_id}' 不存在")
    
    # 设置为默认
    dao = AgentConfigDao()
    success = await dao.set_default(agent_id)
    
    if success:
        return await Response.succ(data={"agent_id": agent_id}, message=f"Agent '{agent_id}' 已设为默认")
    else:
        return await Response.error(message=f"设置默认 Agent 失败")


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


@agent_router.post("/abilities")
async def get_agent_abilities(payload: AgentAbilitiesRequest):
    """Desktop 端：生成指定 Agent 的能力卡片列表"""
    try:
        logger.info(f"生成 Agent 语言: {payload.language}")
        items = await generate_agent_abilities_service(
            agent_id=payload.agent_id,
            session_id=payload.session_id,
            context=payload.context,
            language=payload.language or "zh",
        )
        data = AgentAbilitiesData(items=items)
        return await Response.succ(
            data=data.model_dump(),
            message="成功获取Agent能力列表",
        )
    except AgentAbilitiesGenerationError as e:
        logger.error(f"生成 Agent 能力列表失败: {e}")
        return await Response.error(
            message="获取能力列表失败，请稍后重试",
            error_detail=str(e),
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
    user_home = Path.home()
    sage_home = user_home / ".sage"
    workspace_path = sage_home / "agents" / agent_id
    logger.info(f"获取Agent {agent_id} 的工作空间路径：{workspace_path}")
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
    user_home = Path.home()
    sage_home = user_home / ".sage"
    workspace_path = sage_home / "agents" / agent_id

    try:
        path = _resolve_workspace_file_path(workspace_path, file_path)
        
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


@agent_router.delete("/{agent_id}/file_workspace/delete")
async def delete_file(agent_id: str, request: Request):
    file_path = request.query_params.get("file_path")
    logger.bind(agent_id=agent_id).info(f"Delete request: file_path={file_path}")
    user_home = Path.home()
    sage_home = user_home / ".sage"
    workspace_path = sage_home / "agents" / agent_id

    try:
        full_file_path = _resolve_workspace_file_path(workspace_path, file_path)

        if os.path.isfile(full_file_path):
            os.remove(full_file_path)
        elif os.path.isdir(full_file_path):
            import shutil
            shutil.rmtree(full_file_path)
        
        return await Response.succ(message=f"文件 {file_path} 已删除")
    except Exception as e:
        logger.bind(agent_id=agent_id).error(f"Delete failed: {e}")
        raise


@agent_router.post("/{agent_id}/file_workspace/upload")
async def upload_file(agent_id: str, file: UploadFile = File(...), target_path: str = ""):
    """上传文件到Agent工作空间"""
    logger.bind(agent_id=agent_id).info(f"Upload request: filename={file.filename}, target_path={target_path}")
    user_home = Path.home()
    sage_home = user_home / ".sage"
    workspace_path = sage_home / "agents" / agent_id
    
    try:
        # 确保工作空间目录存在
        workspace_path.mkdir(parents=True, exist_ok=True)
        
        # 构建目标文件路径
        if target_path:
            # 如果指定了目标路径，创建子目录
            target_dir = workspace_path / target_path
            target_dir.mkdir(parents=True, exist_ok=True)
            file_path = target_dir / file.filename
        else:
            file_path = workspace_path / file.filename
        
        # 安全检查：确保文件路径在工作空间内
        workspace_abs = os.path.normcase(os.path.abspath(workspace_path))
        file_abs = os.path.normcase(os.path.abspath(file_path))
        try:
            in_workspace = os.path.commonpath([workspace_abs, file_abs]) == workspace_abs
        except ValueError:
            in_workspace = False
        
        if not in_workspace:
            raise SageHTTPException(status_code=400, detail="访问被拒绝：文件路径超出工作空间范围")
        
        # 保存文件
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        file_size = os.path.getsize(file_path)
        logger.bind(agent_id=agent_id).info(f"Upload successful: {file_path}, size={file_size}")
        
        return await Response.succ(
            message=f"文件 {file.filename} 上传成功",
            data={
                "filename": file.filename,
                "path": str(file_path.relative_to(workspace_path)),
                "size": file_size,
            }
        )
    except Exception as e:
        logger.bind(agent_id=agent_id).error(f"Upload failed: {e}")
        raise


@agent_router.post("/{agent_id}/file_workspace/upload_folder")
async def upload_folder(agent_id: str, request: Request):
    """上传文件夹到Agent工作空间（通过文件列表）"""
    logger.bind(agent_id=agent_id).info(f"Upload folder request")
    user_home = Path.home()
    sage_home = user_home / ".sage"
    workspace_path = sage_home / "agents" / agent_id
    
    try:
        data = await request.json()
        files = data.get("files", [])
        target_folder = data.get("target_folder", "")
        
        if not files:
            raise SageHTTPException(status_code=400, detail="没有要上传的文件")
        
        # 确保工作空间目录存在
        workspace_path.mkdir(parents=True, exist_ok=True)
        
        # 构建目标目录
        if target_folder:
            target_dir = workspace_path / target_folder
            target_dir.mkdir(parents=True, exist_ok=True)
        else:
            target_dir = workspace_path
        
        uploaded_files = []
        
        for file_info in files:
            relative_path = file_info.get("relative_path", "")
            source_path = file_info.get("source_path", "")
            
            if not source_path or not os.path.exists(source_path):
                logger.warning(f"Source file not found: {source_path}")
                continue
            
            # 构建目标文件路径
            if relative_path:
                dest_path = target_dir / relative_path
                dest_path.parent.mkdir(parents=True, exist_ok=True)
            else:
                dest_path = target_dir / os.path.basename(source_path)
            
            # 安全检查
            workspace_abs = os.path.normcase(os.path.abspath(workspace_path))
            dest_abs = os.path.normcase(os.path.abspath(dest_path))
            try:
                in_workspace = os.path.commonpath([workspace_abs, dest_abs]) == workspace_abs
            except ValueError:
                in_workspace = False
            
            if not in_workspace:
                logger.warning(f"Path outside workspace: {dest_path}")
                continue
            
            # 复制文件
            shutil.copy2(source_path, dest_path)
            file_size = os.path.getsize(dest_path)
            
            uploaded_files.append({
                "filename": os.path.basename(source_path),
                "path": str(dest_path.relative_to(workspace_path)),
                "size": file_size,
            })
        
        logger.bind(agent_id=agent_id).info(f"Folder upload successful: {len(uploaded_files)} files")
        
        return await Response.succ(
            message=f"成功上传 {len(uploaded_files)} 个文件",
            data={"files": uploaded_files}
        )
    except Exception as e:
        logger.bind(agent_id=agent_id).error(f"Folder upload failed: {e}")
        raise

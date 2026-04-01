"""
Agent 业务处理模块

封装 Agent 相关的业务逻辑，供路由层调用。
"""
import mimetypes
import tempfile
import zipfile
import shutil
import uuid
import os
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger
from sagents.tool.tool_manager import get_tool_manager
from sagents.tool.tool_proxy import ToolProxy
from sagents.utils.auto_gen_agent import AutoGenAgentFunc
from sagents.utils.system_prompt_optimizer import SystemPromptOptimizer

from .. import models
from ..core import config
from ..core.exceptions import SageHTTPException
from .agent_inherit import ensure_agent_inherit_dir
from .chat.utils import create_model_client

# ================= 工具函数 =================


def generate_agent_id() -> str:
    """生成唯一的 Agent ID"""
    return f"agent_{uuid.uuid4().hex[:8]}"


def _select_provider(providers: List[models.LLMProvider]) -> Optional[models.LLMProvider]:
    """优先选择默认 provider，否则取列表中的第一个。"""
    if not providers:
        return None
    return next((provider for provider in providers if provider.is_default), providers[0])


async def _create_model_client_for_user(user_id: str) -> Tuple[Any, str]:
    """根据登录用户的 provider 创建模型客户端。"""
    provider_dao = models.LLMProviderDao()
    providers = await provider_dao.get_list(user_id=user_id)
    provider = _select_provider(providers)

    if not provider:
        raise SageHTTPException(
            detail="当前用户未配置可用的模型提供商",
            error_detail=f"user '{user_id or '<empty>'}' has no llm provider",
        )

    if not provider.api_key:
        raise SageHTTPException(
            detail="模型提供商未配置 API Key",
            error_detail=f"provider '{provider.id}' api_key is empty",
        )

    if not provider.model:
        raise SageHTTPException(
            detail="模型提供商未配置模型名称",
            error_detail=f"provider '{provider.id}' model is empty",
        )

    logger.info(
        f"为用户 {user_id or '<system>'} 使用模型提供商: "
        f"{provider.name} ({provider.id}), model={provider.model}"
    )
    model_client = create_model_client(
        {
            "api_key": provider.api_key,
            "base_url": provider.base_url,
            "model": provider.model,
        }
    )
    return model_client, provider.model


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
    # 强制添加必要的工具
    agent_config = _enforce_required_tools(agent_config)

    dao = models.AgentConfigDao()
    existing_config = await dao.get_by_name_and_user(agent_name, user_id)
    if existing_config:
        raise SageHTTPException(
            detail=f"Agent '{agent_name}' 已存在",
            error_detail=f"Agent '{agent_name}' 已存在",
        )
    orm_obj = models.Agent(agent_id=agent_id, name=agent_name, config=agent_config)
    orm_obj.user_id = user_id
    await dao.save(orm_obj)
    try:
        ensure_agent_inherit_dir(agent_id)
    except Exception as e:
        logger.error(f"Agent {agent_id} inherit 目录初始化失败: {e}")
        try:
            await dao.delete_by_id(agent_id)
            logger.info(f"Agent {agent_id} 已回滚删除")
        except Exception as rollback_error:
            logger.error(f"Agent {agent_id} 回滚删除失败: {rollback_error}")
        raise SageHTTPException(
            detail="Agent 初始化默认 inherit 目录失败",
            error_detail=str(e),
        )
    logger.info(f"Agent {agent_id} 创建成功")
    return orm_obj


async def get_agent(agent_id: str, user_id: Optional[str] = None) -> models.Agent:
    """根据 ID 获取 Agent 配置并转换为响应结构"""
    logger.info(f"获取Agent配置: {agent_id}")
    dao = models.AgentConfigDao()
    existing = await dao.get_by_id(agent_id)
    if not existing:
        raise SageHTTPException(
            detail=f"Agent '{agent_id}' 不存在",
            error_detail=f"Agent '{agent_id}' 不存在",
        )
    if user_id and existing.user_id != user_id:
        # Check if user is authorized
        authorized_users = await dao.get_authorized_users(agent_id)
        if user_id not in authorized_users:
            raise SageHTTPException(
                detail="无权访问该Agent",
                error_detail="forbidden",
            )
    return existing


async def get_agent_authorized_users(agent_id: str, user_id: str, role: str) -> List[str]:
    """Get list of authorized user IDs for an agent"""
    dao = models.AgentConfigDao()
    agent = await dao.get_by_id(agent_id)
    if not agent:
        raise SageHTTPException(detail="Agent不存在", error_detail="not found")
    
    # Only Admin or Owner can view authorized users
    if role != "admin" and agent.user_id != user_id:
        raise SageHTTPException(detail="无权查看授权用户", error_detail="forbidden")
        
    return await dao.get_authorized_users(agent_id)


async def update_agent_authorizations(
    agent_id: str, authorized_user_ids: List[str], user_id: str, role: str
) -> None:
    """Update authorized users for an agent"""
    dao = models.AgentConfigDao()
    agent = await dao.get_by_id(agent_id)
    if not agent:
        raise SageHTTPException(detail="Agent不存在", error_detail="not found")
    
    # Only Admin or Owner can update authorizations
    if role != "admin" and agent.user_id != user_id:
        raise SageHTTPException(detail="无权修改授权", error_detail="forbidden")
    
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
            detail=f"Agent '{agent_id}' 不存在",
            error_detail=f"Agent '{agent_id}' 不存在",
        )
    # 强制添加必要的工具
    agent_config = _enforce_required_tools(agent_config)

    # Check permission: if user_id is provided, it must match
    if role != "admin" and user_id and existing_config.user_id and existing_config.user_id != user_id:
        raise SageHTTPException(
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
            detail=f"Agent '{agent_id}' 不存在",
            error_detail=f"Agent '{agent_id}' 不存在",
        )
    if role != "admin" and user_id and existing_config.user_id and existing_config.user_id != user_id:
        raise SageHTTPException(
            detail="无权删除该Agent",
            error_detail="forbidden",
        )
    await dao.delete_by_id(agent_id)
    logger.info(f"Agent {agent_id} 删除成功")
    return existing_config


async def auto_generate_agent(
    agent_description: str, available_tools: Optional[List[str]] = None, user_id: str = ""
) -> Dict[str, Any]:
    """自动生成 Agent 配置"""
    logger.info(f"开始自动生成Agent: {agent_description}")
    model_client, model_name = await _create_model_client_for_user(user_id)

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
        model=model_name,
    )
    agent_config["id"] = ""

    if not agent_config:
        raise SageHTTPException(
            detail="自动生成Agent失败",
            error_detail="生成的Agent配置为空",
        )
    logger.info("Agent自动生成成功")
    return agent_config


async def optimize_system_prompt(
    original_prompt: str, optimization_goal: Optional[str] = None, user_id: str = ""
) -> Dict[str, Any]:
    """优化系统提示词"""
    logger.info("开始优化系统提示词")
    model_client, model_name = await _create_model_client_for_user(user_id)

    optimizer = SystemPromptOptimizer()
    optimized_prompt = await optimizer.optimize_system_prompt(
        current_prompt=original_prompt,
        optimization_goal=optimization_goal,
        model=model_name,
        llm_client=model_client,
    )

    if not optimized_prompt:
        raise SageHTTPException(
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



async def get_file_workspace(agent_id: str, user_id: str) -> Dict[str, Any]:
    """获取指定会话的文件工作空间内容"""
    # 尝试从 SessionContext 获取 agent_workspace
    cfg = config.get_startup_config()
    workspace_path = os.path.join(cfg.agents_dir, user_id, agent_id)
    if not workspace_path or not os.path.exists(workspace_path):
        return {
            "agent_id": agent_id,
            "files": [],
            "message": "工作空间为空",
        }

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

    logger.info(f"获取工作空间文件数量：{len(files)}")
    return {
        "agent_id": agent_id,
        "files": files,
        "message": "获取文件列表成功",
    }



async def download_agent_file(agent_id: str, user_id: str, file_path: str) -> Tuple[str, str, str]:
    """
    下载会话文件

    :param agent_id: 会话ID
    :param user_id: 用户ID
    :param file_path: 相对文件路径
    :return: (file_path, filename, media_type)
    """

    cfg = config.get_startup_config()
    workspace_path = os.path.join(cfg.agents_dir, user_id, agent_id)

    full_path = resolve_download_path(workspace_path, file_path)

    # 检查是否为文件或目录
    if os.path.isdir(full_path):
        # 如果是目录，创建zip文件并下载
        try:
            # 使用临时文件存储zip
            temp_dir = tempfile.gettempdir()
            zip_filename = f"{os.path.basename(full_path)}.zip"
            zip_path = os.path.join(temp_dir, zip_filename)

            # 创建zip文件
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(full_path):
                    for file in files:
                        file_abs_path = os.path.join(root, file)
                        # 计算在zip中的相对路径
                        rel_path = os.path.relpath(file_abs_path, full_path)
                        zipf.write(file_abs_path, rel_path)

            return zip_path, zip_filename, "application/zip"
        except Exception as e:
            raise SageHTTPException(
                detail=f"创建压缩文件失败: {str(e)}",
                error_detail=f"Failed to create zip file: {str(e)}",
            )

    if not os.path.isfile(full_path):
        raise SageHTTPException(
            detail=f"路径不是文件: {file_path}",
            error_detail=f"Path is not a file: {file_path}",
        )

    # 获取MIME类型
    mime_type, _ = mimetypes.guess_type(full_path)
    if mime_type is None:
        mime_type = "application/octet-stream"

    return full_path, os.path.basename(full_path), mime_type

async def delete_agent_file(agent_id: str, user_id: str, file_path: str) -> bool:
    """
    删除会话文件或目录

    :param agent_id: 会话ID
    :param user_id: 用户ID
    :param file_path: 相对文件路径
    :return: 是否删除成功
    """
    cfg = config.get_startup_config()
    workspace_path = os.path.join(cfg.agents_dir, user_id, agent_id)

    # 路径安全校验
    full_path = resolve_download_path(workspace_path, file_path)
    
    try:
        if os.path.isfile(full_path):
            os.remove(full_path)
        elif os.path.isdir(full_path):
            shutil.rmtree(full_path)
        else:
            raise SageHTTPException(
                detail=f"路径不存在: {file_path}",
                error_detail=f"Path not found: {file_path}",
            )
        return True
    except Exception as e:
        logger.error(f"删除文件失败: {e}")
        raise SageHTTPException(
            detail=f"删除文件失败: {str(e)}",
            error_detail=f"Failed to delete file: {str(e)}",
        )


def resolve_download_path(workspace_path: str, file_path: str) -> str:
    """校验并返回可下载的文件绝对路径"""
    if not workspace_path or not file_path:
        raise SageHTTPException(
            detail="缺少必要的路径参数",
            error_detail="workspace_path or file_path missing",
        )
    full_file_path = os.path.join(workspace_path, file_path)
    if not os.path.abspath(full_file_path).startswith(os.path.abspath(workspace_path)):
        raise SageHTTPException(
            detail="访问被拒绝：文件路径超出工作空间范围",
            error_detail="Access denied: file path outside workspace",
        )
    if not os.path.exists(full_file_path):
        raise SageHTTPException(
            detail=f"文件不存在: {file_path}",
            error_detail=f"File not found: {file_path}",
        )
    return full_file_path

def _enforce_required_tools(agent_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    根据 Agent 配置强制添加必要的工具

    - 如果记忆类型选择了"用户"，强制添加 search_memory 工具
    - 如果 Agent 策略是 fibre，强制添加 sys_spawn_agent、sys_delegate_task、sys_finish_task 工具
    """
    available_tools = agent_config.get("available_tools", []) or agent_config.get("availableTools", [])
    if not available_tools:
        available_tools = []

    # 转换为集合便于操作
    tools_set = set(available_tools)
    original_tools = tools_set.copy()

    # 检查记忆类型
    memory_type = agent_config.get("memoryType") or agent_config.get("memory_type")
    if memory_type == "user":
        tools_set.add("search_memory")
        logger.info("Agent 记忆类型为用户，强制添加 search_memory 工具")

    # 检查 Agent 策略/模式
    agent_mode = agent_config.get("agentMode") or agent_config.get("agent_mode")
    if agent_mode == "fibre":
        fibre_tools = {"sys_spawn_agent", "sys_delegate_task", "sys_finish_task"}
        tools_set.update(fibre_tools)
        logger.info(f"Agent 策略为 fibre，强制添加 fibre 工具: {fibre_tools}")

    # 如果有变化，更新配置
    if tools_set != original_tools:
        new_tools = list(tools_set)
        if "available_tools" in agent_config:
            agent_config["available_tools"] = new_tools
        if "availableTools" in agent_config:
            agent_config["availableTools"] = new_tools
        logger.info(f"Agent 工具列表已更新: {original_tools} -> {tools_set}")

    return agent_config

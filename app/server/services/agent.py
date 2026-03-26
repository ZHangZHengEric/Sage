"""
Agent 业务处理模块

封装 Agent 相关的业务逻辑，供路由层调用。
"""
import json
import mimetypes
import os
import posixpath
import shutil
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger
from sagents.runtime_context import RuntimeContext
from sagents.session_runtime import get_global_session_manager
from sagents.tool.tool_manager import get_tool_manager
from sagents.tool.tool_proxy import ToolProxy
from sagents.utils.auto_gen_agent import AutoGenAgentFunc
from sagents.utils.sandbox import SandboxConfig, SandboxProviderFactory, SandboxType
from sagents.utils.system_prompt_optimizer import SystemPromptOptimizer

from .. import models
from ..core import config
from ..core.exceptions import SageHTTPException
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


@dataclass
class WorkspaceAccess:
    mode: str
    runtime_context: RuntimeContext
    local_workspace_path: str
    sandbox: Optional[Any] = None


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


def _default_workspace_path(agent_id: str, user_id: str) -> str:
    cfg = config.get_startup_config()
    return os.path.join(cfg.agents_dir, user_id, agent_id)


def _load_runtime_context_from_session(session_id: Optional[str]) -> Optional[RuntimeContext]:
    if not session_id:
        return None

    cfg = config.get_startup_config()
    try:
        session_manager = get_global_session_manager(session_root_space=cfg.session_dir)
    except Exception as e:
        logger.warning(f"无法获取 SessionManager，回退本地工作区: {e}")
        return None

    session_workspace = session_manager.get_session_workspace(session_id)
    if not session_workspace:
        return None

    context_path = os.path.join(session_workspace, "session_context.json")
    if not os.path.exists(context_path):
        return None

    try:
        with open(context_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.warning(f"读取 session_context.json 失败，session_id={session_id}: {e}")
        return None

    runtime_context = data.get("runtime_context")
    host_workspace = data.get("host_workspace")
    virtual_workspace = data.get("virtual_workspace") or "/sage-workspace"
    if runtime_context:
        try:
            return RuntimeContext.from_input(
                runtime_context,
                host_workspace=host_workspace,
                virtual_workspace=virtual_workspace,
            )
        except Exception as e:
            logger.warning(f"恢复 runtime_context 失败，session_id={session_id}: {e}")
            return None

    if host_workspace:
        return RuntimeContext.from_input(
            None,
            sandbox_mode="local",
            host_workspace=host_workspace,
            virtual_workspace=virtual_workspace,
        )

    return None


async def _get_workspace_access(agent_id: str, user_id: str, session_id: Optional[str] = None) -> WorkspaceAccess:
    local_workspace_path = _default_workspace_path(agent_id, user_id)
    runtime_context = _load_runtime_context_from_session(session_id)
    if runtime_context is None:
        runtime_context = RuntimeContext(
            deployment_mode="server",
            sandbox_mode="local",
            host_workspace=local_workspace_path,
            virtual_workspace="/sage-workspace",
        )

    if runtime_context.is_remote():
        runtime_context.validate()
        sandbox_config = SandboxConfig(
            sandbox_id=runtime_context.sandbox_id,
            mode=SandboxType.REMOTE,
            workspace=runtime_context.host_workspace or ".",
            virtual_workspace=runtime_context.virtual_workspace,
            remote_provider=runtime_context.remote_provider or os.environ.get("SAGE_REMOTE_PROVIDER", "opensandbox"),
            remote_server_url=runtime_context.remote_server_url,
            remote_api_key=runtime_context.remote_api_key or os.environ.get("OPENSANDBOX_API_KEY"),
            remote_image=runtime_context.remote_image or os.environ.get("OPENSANDBOX_IMAGE", "opensandbox/code-interpreter:v1.0.2"),
            remote_timeout=int(runtime_context.remote_timeout or os.environ.get("OPENSANDBOX_TIMEOUT", "1800")),
            remote_persistent=True if runtime_context.remote_persistent is None else bool(runtime_context.remote_persistent),
            remote_sandbox_ttl=int(runtime_context.remote_sandbox_ttl or 3600),
        )
        sandbox = SandboxProviderFactory.create(sandbox_config)
        await sandbox.initialize()
        return WorkspaceAccess(
            mode="remote",
            runtime_context=runtime_context,
            local_workspace_path=local_workspace_path,
            sandbox=sandbox,
        )

    return WorkspaceAccess(
        mode="local",
        runtime_context=runtime_context,
        local_workspace_path=runtime_context.host_workspace or local_workspace_path,
        sandbox=None,
    )


def _resolve_virtual_workspace_path(workspace_root: str, file_path: str) -> str:
    if not workspace_root or not file_path:
        raise SageHTTPException(
            detail="缺少必要的路径参数",
            error_detail="workspace_root or file_path missing",
        )

    workspace_root = posixpath.normpath(workspace_root)
    normalized = str(file_path).replace("\\", "/")
    if normalized == workspace_root or normalized.startswith(f"{workspace_root}/"):
        candidate = posixpath.normpath(normalized)
    else:
        candidate = posixpath.normpath(posixpath.join(workspace_root, normalized.lstrip("/")))

    if candidate != workspace_root and not candidate.startswith(f"{workspace_root}/"):
        raise SageHTTPException(
            detail="访问被拒绝：文件路径超出工作空间范围",
            error_detail="Access denied: file path outside workspace",
        )

    return candidate


async def _list_remote_workspace_files(sandbox: Any, workspace_root: str) -> List[Dict[str, Any]]:
    files: List[Dict[str, Any]] = []

    async def walk(path: str) -> None:
        entries = await sandbox.list_directory(path, include_hidden=False)
        entries.sort(key=lambda entry: (not entry.is_dir, entry.path))
        for entry in entries:
            relative_path = posixpath.relpath(posixpath.normpath(entry.path), posixpath.normpath(workspace_root))
            files.append(
                {
                    "name": posixpath.basename(entry.path.rstrip("/")),
                    "path": relative_path,
                    "size": entry.size,
                    "modified_time": entry.modified_time,
                    "is_directory": entry.is_dir,
                }
            )
            if entry.is_dir:
                await walk(entry.path)

    await walk(workspace_root)
    return files


async def _get_remote_entry(sandbox: Any, workspace_root: str, file_path: str) -> Dict[str, Any]:
    virtual_path = _resolve_virtual_workspace_path(workspace_root, file_path)
    root_norm = posixpath.normpath(workspace_root)
    if virtual_path == root_norm:
        return {
            "path": virtual_path,
            "is_directory": True,
            "name": posixpath.basename(virtual_path.rstrip("/")) or "workspace",
        }

    parent_path = posixpath.dirname(virtual_path)
    for entry in await sandbox.list_directory(parent_path, include_hidden=True):
        if posixpath.normpath(entry.path) == virtual_path:
            return {
                "path": virtual_path,
                "is_directory": entry.is_dir,
                "name": posixpath.basename(entry.path.rstrip("/")),
            }

    raise SageHTTPException(
        detail=f"文件不存在: {file_path}",
        error_detail=f"Remote file not found: {file_path}",
    )


async def _download_remote_directory(sandbox: Any, source_dir: str, target_dir: str) -> None:
    os.makedirs(target_dir, exist_ok=True)
    for entry in await sandbox.list_directory(source_dir, include_hidden=True):
        target_path = os.path.join(target_dir, posixpath.basename(entry.path.rstrip("/")))
        if entry.is_dir:
            await _download_remote_directory(sandbox, entry.path, target_path)
        else:
            await sandbox.download_file(entry.path, target_path)


def _zip_directory(source_dir: str, zip_path: str) -> None:
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(source_dir):
            for file_name in files:
                file_abs_path = os.path.join(root, file_name)
                rel_path = os.path.relpath(file_abs_path, source_dir)
                zipf.write(file_abs_path, rel_path)



async def get_file_workspace(agent_id: str, user_id: str, session_id: Optional[str] = None) -> Dict[str, Any]:
    """获取指定会话的文件工作空间内容"""
    access = await _get_workspace_access(agent_id, user_id, session_id=session_id)
    try:
        if access.mode == "remote":
            files = await _list_remote_workspace_files(access.sandbox, access.runtime_context.virtual_workspace)
        else:
            workspace_path = access.local_workspace_path
            if not workspace_path or not os.path.exists(workspace_path):
                return {
                    "agent_id": agent_id,
                    "files": [],
                    "message": "工作空间为空",
                }

            files: List[Dict[str, Any]] = []
            for root, dirs, filenames in os.walk(workspace_path):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                filenames = [f for f in filenames if not f.startswith(".")]
                for filename in filenames:
                    full_path = os.path.join(root, filename)
                    relative_path = os.path.relpath(full_path, workspace_path)
                    file_stat = os.stat(full_path)
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
    finally:
        if access.sandbox:
            await access.sandbox.cleanup()



async def download_agent_file(
    agent_id: str,
    user_id: str,
    file_path: str,
    session_id: Optional[str] = None,
) -> Tuple[str, str, str]:
    """
    下载会话文件

    :param agent_id: 会话ID
    :param user_id: 用户ID
    :param file_path: 相对文件路径
    :return: (file_path, filename, media_type)
    """

    access = await _get_workspace_access(agent_id, user_id, session_id=session_id)
    try:
        if access.mode == "remote":
            entry = await _get_remote_entry(access.sandbox, access.runtime_context.virtual_workspace, file_path)
            temp_dir = tempfile.mkdtemp(prefix="sage-remote-download-")
            if entry["is_directory"]:
                dir_name = entry["name"] or "workspace"
                download_dir = os.path.join(temp_dir, dir_name)
                await _download_remote_directory(access.sandbox, entry["path"], download_dir)
                zip_filename = f"{dir_name}.zip"
                zip_path = os.path.join(temp_dir, zip_filename)
                _zip_directory(download_dir, zip_path)
                return zip_path, zip_filename, "application/zip"

            local_path = os.path.join(temp_dir, entry["name"])
            await access.sandbox.download_file(entry["path"], local_path)
            mime_type, _ = mimetypes.guess_type(local_path)
            if mime_type is None:
                mime_type = "application/octet-stream"
            return local_path, entry["name"], mime_type

        workspace_path = access.local_workspace_path
        full_path = resolve_download_path(workspace_path, file_path)
        if os.path.isdir(full_path):
            try:
                temp_dir = tempfile.gettempdir()
                zip_filename = f"{os.path.basename(full_path)}.zip"
                zip_path = os.path.join(temp_dir, zip_filename)
                _zip_directory(full_path, zip_path)
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

        mime_type, _ = mimetypes.guess_type(full_path)
        if mime_type is None:
            mime_type = "application/octet-stream"
        return full_path, os.path.basename(full_path), mime_type
    finally:
        if access.sandbox:
            await access.sandbox.cleanup()

async def delete_agent_file(
    agent_id: str,
    user_id: str,
    file_path: str,
    session_id: Optional[str] = None,
) -> bool:
    """
    删除会话文件或目录

    :param agent_id: 会话ID
    :param user_id: 用户ID
    :param file_path: 相对文件路径
    :return: 是否删除成功
    """
    access = await _get_workspace_access(agent_id, user_id, session_id=session_id)
    try:
        if access.mode == "remote":
            entry = await _get_remote_entry(access.sandbox, access.runtime_context.virtual_workspace, file_path)
            await access.sandbox.delete_file(entry["path"])
            return True

        workspace_path = access.local_workspace_path
        full_path = resolve_download_path(workspace_path, file_path)
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
    finally:
        if access.sandbox:
            await access.sandbox.cleanup()


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

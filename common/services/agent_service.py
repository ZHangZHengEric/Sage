import asyncio
import hashlib
import mimetypes
import os
import posixpath
import random
import shutil
import tempfile
import uuid
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from loguru import logger

from common.core import config
from common.core.client.chat import get_chat_client
from common.core.context import get_request_locale
from common.core.exceptions import SageHTTPException
from common.core.i18n import t
from common.models.agent import Agent, AgentConfigDao
from common.models.llm_provider import LLMProvider, LLMProviderDao
from common.services.agent_workspace import (
    cleanup_unselected_skills,
    get_agent_workspace_root,
    sync_selected_skills_to_workspace,
)
from common.schemas.agent import AgentAbilityItem

DEFAULT_OPENCLAW_AGENT_NAME = "openclaw的小龙虾"
DEFAULT_OPENCLAW_AGENT_DESCRIPTION = "从 OpenClaw 一键导入的智能体"
DEFAULT_OPENCLAW_AGENT_TOOLS = [
    "todo_write",
    "todo_read",
    "execute_shell_command",
    "file_read",
    "file_write",
    "file_update",
    "load_skill",
    "add_task",
    "delete_task",
    "complete_task",
    "enable_task",
    "get_task_details",
    "fetch_webpages",
    "search_web_page",
    "search_image_from_web",
]

_WORKSPACE_FILE_HASH_ALGORITHM = "md5"


def generate_agent_id() -> str:
    """生成唯一的 Agent ID。"""
    return f"agent_{uuid.uuid4().hex[:8]}"


def enforce_required_tools(agent_config: Dict[str, Any]) -> Dict[str, Any]:
    """根据 Agent 配置强制添加必要的工具（server / desktop 共享逻辑）。"""
    available_tools = agent_config.get("available_tools", []) or agent_config.get(
        "availableTools", []
    )
    if not available_tools:
        available_tools = []

    tools_set = set(available_tools)
    original_tools = tools_set.copy()

    memory_type = agent_config.get("memoryType") or agent_config.get("memory_type")
    if memory_type == "user":
        tools_set.add("search_memory")
        logger.info("Agent 记忆类型为用户，强制添加 search_memory 工具")

    agent_mode = agent_config.get("agentMode") or agent_config.get("agent_mode")
    if agent_mode == "fibre":
        fibre_tools = {"sys_spawn_agent", "sys_delegate_task"}
        team_tools = {"sys_team_delegate_task"}
        tools_set.update(fibre_tools)
        tools_set.difference_update(team_tools)
        logger.info(f"Agent 策略为 fibre，强制添加 fibre 工具: {fibre_tools}")
    elif agent_mode == "team":
        team_tools = {"sys_team_delegate_task"}
        fibre_tools = {
            "sys_spawn_agent",
            "sys_delegate_task",
        }
        tools_set.update(team_tools)
        tools_set.difference_update(fibre_tools)
        logger.info(f"Agent 策略为 team，强制添加 team 工具: {team_tools}")
    else:
        multi_agent_tools = {
            "sys_spawn_agent",
            "sys_delegate_task",
            "sys_team_delegate_task",
        }
        tools_set.difference_update(multi_agent_tools)

    if tools_set != original_tools:
        new_tools = list(tools_set)
        if "available_tools" in agent_config:
            agent_config["available_tools"] = new_tools
        if "availableTools" in agent_config:
            agent_config["availableTools"] = new_tools
        logger.info(f"Agent 工具列表已更新: {original_tools} -> {tools_set}")

    return agent_config


def validate_and_filter_tools(agent_config: Dict[str, Any]) -> Dict[str, Any]:
    """验证并过滤掉不可用的工具（server / desktop 共享逻辑）。"""
    from sagents.tool.tool_manager import get_tool_manager

    tm = get_tool_manager()
    if not tm:
        return agent_config

    available_tools = agent_config.get("available_tools", []) or agent_config.get(
        "availableTools", []
    )
    if not available_tools:
        return agent_config

    valid_tool_names = set(tm.list_all_tools_name())
    filtered_tools = [t for t in available_tools if t in valid_tool_names]
    if len(filtered_tools) != len(available_tools):
        removed_tools = set(available_tools) - set(filtered_tools)
        logger.warning(f"以下工具不可用，已自动移除: {removed_tools}")

        if "available_tools" in agent_config:
            agent_config["available_tools"] = filtered_tools
        if "availableTools" in agent_config:
            agent_config["availableTools"] = filtered_tools

    return agent_config


def _get_cfg() -> config.StartupConfig:
    cfg = config.get_startup_config()
    if not cfg:
        raise RuntimeError("Startup config not initialized")
    return cfg


def _require_agent_name(agent_name: str, *, agent_id: str = "") -> str:
    normalized = str(agent_name or "").strip()
    if not normalized:
        if agent_id:
            raise SageHTTPException(
                message_key="agent.name_missing_with_id",
                message_params={"agent_id": agent_id},
                error_detail=f"agent '{agent_id}' missing name",
            )
        raise SageHTTPException(
            message_key="agent.name_required",
            error_detail="agent name is required",
        )
    return normalized


def _normalize_max_loop_count(agent_config: Dict[str, Any]) -> Dict[str, Any]:
    loop_key = "maxLoopCount" if "maxLoopCount" in agent_config else "max_loop_count"
    if loop_key not in agent_config:
        loop_key = "maxLoopCount"

    value = agent_config.get(loop_key)
    if value is None or value == "":
        raise SageHTTPException(
            status_code=400,
            message_key="agent.max_loop_required",
            error_detail="maxLoopCount is required",
        )

    try:
        normalized_value = int(value)
    except (TypeError, ValueError):
        raise SageHTTPException(
            status_code=400,
            message_key="agent.max_loop_integer",
            error_detail="maxLoopCount must be an integer",
        )

    if normalized_value < 1:
        raise SageHTTPException(
            status_code=400,
            message_key="agent.max_loop_min",
            error_detail="maxLoopCount must be greater than or equal to 1",
        )

    agent_config[loop_key] = normalized_value
    return agent_config


def _normalize_agent_mode(agent_config: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize legacy agent mode values to explicit runtime modes."""
    mode_key = None
    if "agentMode" in agent_config:
        mode_key = "agentMode"
    elif "agent_mode" in agent_config:
        mode_key = "agent_mode"

    if not mode_key:
        return agent_config

    raw_value = str(agent_config.get(mode_key) or "").strip().lower()
    if raw_value in {"", "auto"}:
        normalized_value = "simple"
    elif raw_value in {"simple", "multi", "fibre", "team"}:
        normalized_value = raw_value
    else:
        normalized_value = "simple"

    agent_config[mode_key] = normalized_value
    return agent_config


def _create_model_client(
    client_params: Dict[str, Any], *, randomize_keys: bool = False
) -> Any:
    """
    创建模型客户端

    支持标准模型和快速模型双配置
    快速模型配置参数（可选）：
    - fast_api_key: 快速模型 API Key（默认使用标准模型的 key）
    - fast_base_url: 快速模型 Base URL（默认使用标准模型的 URL）
    - fast_model_name: 快速模型名称（如果不设置，则不启用快速模型）
    """
    api_key = client_params.get("api_key")
    base_url = client_params.get("base_url")
    model_name = client_params.get("model")
    client_params.get("timeout", 60 * 30)

    # 快速模型配置（可选）
    fast_api_key = client_params.get("fast_api_key")
    fast_base_url = client_params.get("fast_base_url")
    fast_model_name = client_params.get("fast_model_name")

    if randomize_keys and api_key and isinstance(api_key, str) and "," in api_key:
        keys = [k.strip() for k in api_key.split(",") if k.strip()]
        if keys:
            api_key = random.choice(keys)
            logger.info(f"Using random key from {len(keys)} available keys")

    logger.info(
        f"初始化Chat模型客户端: model={model_name}, base_url={base_url}, "
        f"fast_model={fast_model_name if fast_model_name else '未配置'}"
    )

    from sagents.llm.chat import OpenAIChat

    # 使用 OpenAIChat 创建客户端（支持双模型）
    openai_chat = OpenAIChat(
        api_key=api_key,  # pyright: ignore[reportArgumentType]
        base_url=base_url,
        model_name=model_name,
        fast_api_key=fast_api_key,
        fast_base_url=fast_base_url,
        fast_model_name=fast_model_name,
    )

    # 返回 SageAsyncOpenAI 实例
    return openai_chat.raw_client


def _select_provider(providers: List[LLMProvider]) -> Optional[LLMProvider]:
    if not providers:
        return None
    return next(
        (provider for provider in providers if provider.is_default), providers[0]
    )


async def _create_server_model_client_for_user(user_id: str) -> Tuple[Any, str]:
    provider_dao = LLMProviderDao()
    providers = await provider_dao.get_list(user_id=user_id)
    provider = _select_provider(providers)

    if not provider:
        raise SageHTTPException(
            message_key="agent.provider_missing",
            error_detail=f"user '{user_id or '<empty>'}' has no llm provider",
        )

    if not provider.api_key:
        raise SageHTTPException(
            message_key="agent.provider_api_key_missing",
            error_detail=f"provider '{provider.id}' api_key is empty",
        )

    if not provider.model:
        raise SageHTTPException(
            message_key="agent.provider_model_missing",
            error_detail=f"provider '{provider.id}' model is empty",
        )

    logger.info(
        f"为用户 {user_id or '<system>'} 使用模型提供商: "
        f"{provider.name} ({provider.id}), model={provider.model}"
    )
    return _create_model_client(
        {
            "api_key": provider.api_key,
            "base_url": provider.base_url,
            "model": provider.model,
        }
    ), provider.model


def _create_desktop_model_client(cfg: config.StartupConfig) -> Tuple[Any, str]:
    try:
        return get_chat_client(), cfg.default_llm_model_name
    except Exception:
        if not cfg.default_llm_api_key:
            raise

    model_name = cfg.default_llm_model_name
    return _create_model_client(
        {
            "api_key": cfg.default_llm_api_key,
            "base_url": cfg.default_llm_api_base_url,
            "model": model_name,
        },
        randomize_keys=True,
    ), model_name


async def _resolve_model_client(user_id: str = "") -> Tuple[Any, str]:
    cfg = _get_cfg()
    if cfg.app_mode == "server":
        return await _create_server_model_client_for_user(user_id)
    return _create_desktop_model_client(cfg)


async def list_agents(user_id: Optional[str] = None) -> List[Agent]:
    dao = AgentConfigDao()
    cfg = _get_cfg()
    if cfg.app_mode == "server":
        return await dao.get_list_with_auth(user_id)
    return await dao.get_list(user_id)


async def get_agent(agent_id: str, user_id: Optional[str] = None) -> Agent:
    logger.info(f"获取Agent配置: {agent_id}")
    dao = AgentConfigDao()
    existing = await dao.get_by_id(agent_id)
    if not existing:
        raise SageHTTPException(
            message_key="agent.not_found_with_id",
            message_params={"agent_id": agent_id},
            error_detail=f"Agent '{agent_id}' 不存在",
        )

    cfg = _get_cfg()
    if cfg.app_mode == "server" and user_id and existing.user_id != user_id:
        authorized_users = await dao.get_authorized_users(agent_id)
        if user_id not in authorized_users:
            raise SageHTTPException(
                message_key="agent.access_forbidden",
                error_detail="forbidden",
            )

    return existing


async def create_agent(
    agent_name: str,
    agent_config: Dict[str, Any],
    user_id: str = "",
) -> Agent:
    cfg = _get_cfg()
    dao = AgentConfigDao()
    normalized_config = dict(agent_config)
    agent_name = _require_agent_name(agent_name)
    normalized_config = _normalize_max_loop_count(normalized_config)
    normalized_config = _normalize_agent_mode(normalized_config)

    if cfg.app_mode == "desktop":
        agent_id = normalized_config.pop("id", None) or generate_agent_id()
        is_default = normalized_config.pop("is_default", False)

        logger.info(
            f"开始创建Agent: {agent_id}, is_default={is_default}, type={type(is_default)}"
        )
        normalized_config = enforce_required_tools(normalized_config)
        normalized_config = validate_and_filter_tools(normalized_config)

        existing_config = await dao.get_by_name_and_user(agent_name, user_id)
        if existing_config:
            raise SageHTTPException(
                status_code=500,
                message_key="agent.exists",
                message_params={"agent_name": agent_name},
                error_detail=f"Agent '{agent_name}' 已存在",
            )

        existing_default = await dao.get_default()
        if is_default and existing_default:
            logger.warning(
                f"已存在默认 Agent '{existing_default.agent_id}'，新 Agent 不设为默认"
            )
            is_default = False
        elif not existing_default:
            logger.info("没有默认 Agent，自动将新 Agent 设为默认")
            is_default = True

        orm_obj = Agent(
            agent_id=agent_id,
            name=agent_name,
            config=normalized_config,
            user_id=user_id,
            is_default=is_default,
        )
        await dao.save(orm_obj)
        await sync_selected_skills_to_workspace(
            agent_id,
            normalized_config,
            user_id=user_id,
            role="user",
        )
        logger.info(f"Agent {agent_id} 创建成功, is_default={is_default}")
        return orm_obj

    agent_id = generate_agent_id()
    logger.info(f"开始创建Agent: {agent_id}")
    normalized_config = enforce_required_tools(normalized_config)

    existing_config = await dao.get_by_name_and_user(agent_name, user_id)
    if existing_config:
        raise SageHTTPException(
            message_key="agent.exists",
            message_params={"agent_name": agent_name},
            error_detail=f"Agent '{agent_name}' 已存在",
        )

    orm_obj = Agent(
        agent_id=agent_id,
        name=agent_name,
        config=normalized_config,
        user_id=user_id,
    )
    await dao.save(orm_obj)
    try:
        from app.server.services.agent_inherit import ensure_agent_inherit_dir

        ensure_agent_inherit_dir(agent_id)
        await sync_selected_skills_to_workspace(
            agent_id,
            normalized_config,
            user_id=user_id,
            role="user",
        )
    except Exception as e:
        logger.error(f"Agent {agent_id} inherit 目录初始化失败: {e}")
        try:
            await dao.delete_by_id(agent_id)
            logger.info(f"Agent {agent_id} 已回滚删除")
        except Exception as rollback_error:
            logger.error(f"Agent {agent_id} 回滚删除失败: {rollback_error}")
        raise SageHTTPException(
            message_key="agent.inherit_init_failed",
            error_detail=str(e),
        )

    logger.info(f"Agent {agent_id} 创建成功")
    return orm_obj


async def update_agent(
    agent_id: str,
    agent_name: str,
    agent_config: Dict[str, Any],
    user_id: Optional[str] = None,
    role: str = "user",
) -> Agent:
    logger.info(f"开始更新Agent: {agent_id}")
    cfg = _get_cfg()
    dao = AgentConfigDao()
    existing_config = await dao.get_by_id(agent_id)
    if not existing_config:
        raise SageHTTPException(
            message_key="agent.not_found_with_id",
            message_params={"agent_id": agent_id},
            error_detail=f"Agent '{agent_id}' 不存在",
        )

    normalized_config = dict(agent_config)
    previous_config = dict(existing_config.config or {})
    agent_name = _require_agent_name(agent_name, agent_id=agent_id)
    normalized_config = _normalize_max_loop_count(normalized_config)
    normalized_config = _normalize_agent_mode(normalized_config)

    if cfg.app_mode == "desktop":
        if user_id and existing_config.user_id and existing_config.user_id != user_id:
            raise SageHTTPException(
                message_key="agent.update_forbidden",
                error_detail="forbidden",
            )
        normalized_config = enforce_required_tools(normalized_config)
        normalized_config = validate_and_filter_tools(normalized_config)
        is_default = normalized_config.get("is_default", existing_config.is_default)
        orm_obj = Agent(
            agent_id=agent_id,
            name=agent_name,
            config=normalized_config,
            user_id=existing_config.user_id,
            is_default=is_default,
            created_at=existing_config.created_at,
        )
        await dao.save(orm_obj)
        await sync_selected_skills_to_workspace(
            agent_id,
            normalized_config,
            user_id=existing_config.user_id or user_id or "",
            role=role,
        )
        await asyncio.to_thread(
            cleanup_unselected_skills,
            agent_id,
            normalized_config,
            previous_agent_config=previous_config,
            user_id=existing_config.user_id or user_id or "",
        )
        logger.info(f"Agent {agent_id} 更新成功")
        return orm_obj

    normalized_config = enforce_required_tools(normalized_config)
    if (
        role != "admin"
        and user_id
        and existing_config.user_id
        and existing_config.user_id != user_id
    ):
        raise SageHTTPException(
            message_key="agent.update_forbidden",
            error_detail="forbidden",
        )

    orm_obj = Agent(
        agent_id=agent_id,
        name=agent_name,
        config=normalized_config,
        user_id=existing_config.user_id,
        is_default=existing_config.is_default,
        created_at=existing_config.created_at,
    )
    await dao.save(orm_obj)
    await sync_selected_skills_to_workspace(
        agent_id,
        normalized_config,
        user_id=existing_config.user_id or user_id or "",
        role=role,
    )

    await asyncio.to_thread(
        cleanup_unselected_skills,
        agent_id,
        normalized_config,
        previous_agent_config=previous_config,
        user_id=existing_config.user_id or user_id or "",
    )

    logger.info(f"Agent {agent_id} 更新成功")
    return orm_obj


def _remove_agent_workspace_directory(
    workspace_path: Path,
    agent_id: str,
    user_id: str,
) -> Dict[str, Any]:
    """删除单个 Agent 工作区目录（若存在）。返回与 delete_server_agent_workspace 一致的结构。"""
    wp_str = str(workspace_path)
    if not workspace_path.exists():
        return {
            "agent_id": agent_id,
            "user_id": user_id,
            "workspace_path": wp_str,
            "deleted": False,
        }
    shutil.rmtree(workspace_path)
    logger.info(
        f"已删除Agent工作空间: agent_id={agent_id}, user_id={user_id}, path={wp_str}"
    )
    return {
        "agent_id": agent_id,
        "user_id": user_id,
        "workspace_path": wp_str,
        "deleted": True,
    }


def delete_agent_workspace_on_host(agent_id: str, user_id: str = "") -> Dict[str, Any]:
    """
    删除当前 app_mode 下 Agent 在宿主机上的工作区目录。

    本地/直通沙箱直接使用该路径；远程沙箱若通过 workspace_mount 将宿主机目录绑定到容器，
    删除宿主机目录即可同步清理挂载内容。未镜像到本机路径的纯远端数据不在此处理。
    """
    cfg = _get_cfg()
    if cfg.app_mode == "desktop":
        workspace_path = Path(
            get_agent_workspace_root(
                agent_id,
                app_mode="desktop",
                ensure_exists=False,
            )
        )
        return _remove_agent_workspace_directory(
            workspace_path, agent_id, user_id or ""
        )

    uid = (user_id or "").strip()
    if not uid:
        logger.warning(
            f"删除 Agent 工作空间跳过: server 模式缺少 user_id, agent_id={agent_id}"
        )
        return {
            "agent_id": agent_id,
            "user_id": "",
            "workspace_path": "",
            "deleted": False,
        }
    workspace_path = Path(
        get_agent_workspace_root(
            agent_id,
            user_id=uid,
            app_mode="server",
            ensure_exists=False,
        )
    )
    return _remove_agent_workspace_directory(workspace_path, agent_id, uid)


async def delete_agent(
    agent_id: str,
    user_id: Optional[str] = None,
    role: str = "user",
) -> Agent:
    logger.info(f"开始删除Agent: {agent_id}")
    cfg = _get_cfg()
    dao = AgentConfigDao()
    existing_config = await dao.get_by_id(agent_id)
    if not existing_config:
        raise SageHTTPException(
            message_key="agent.not_found_with_id",
            message_params={"agent_id": agent_id},
            error_detail=f"Agent '{agent_id}' 不存在",
        )

    if (
        cfg.app_mode in {"server", "desktop"}
        and role != "admin"
        and user_id
        and existing_config.user_id
        and existing_config.user_id != user_id
    ):
        raise SageHTTPException(
            message_key="agent.delete_forbidden",
            error_detail="forbidden",
        )

    owner_uid = existing_config.user_id or user_id or ""
    await dao.delete_by_id(agent_id)
    try:
        await asyncio.to_thread(delete_agent_workspace_on_host, agent_id, owner_uid)
    except Exception as e:
        logger.error(f"删除 Agent 工作空间失败: agent_id={agent_id}, error={e}")
    logger.info(f"Agent {agent_id} 删除成功")
    return existing_config


async def auto_generate_agent(
    agent_description: str,
    available_tools: Optional[List[str]] = None,
    user_id: str = "",
    language: str = "en",
) -> Dict[str, Any]:
    logger.info(f"开始自动生成Agent: {agent_description}")
    from sagents.tool.tool_manager import get_tool_manager
    from sagents.tool.tool_proxy import ToolProxy
    from sagents.utils.auto_gen_agent import AutoGenAgentFunc

    model_client, model_name = await _resolve_model_client(user_id)
    auto_gen_func = AutoGenAgentFunc()

    if available_tools:
        logger.info(f"使用指定的工具列表: {available_tools}")
        tool_manager_or_proxy = ToolProxy(get_tool_manager(), available_tools)  # pyright: ignore[reportArgumentType]
    else:
        logger.info("使用完整的工具管理器")
        tool_manager_or_proxy = get_tool_manager()

    agent_config = await auto_gen_func.generate_agent_config(
        agent_description=agent_description,
        tool_manager=tool_manager_or_proxy,  # pyright: ignore[reportArgumentType]
        llm_client=model_client,
        model=model_name,
        language=language,
    )
    if not agent_config:
        raise SageHTTPException(
            message_key="agent.auto_generate_failed",
            error_detail="生成的Agent配置为空",
        )

    agent_config["id"] = ""
    logger.info("Agent自动生成成功")
    return agent_config


async def optimize_system_prompt(
    original_prompt: str,
    optimization_goal: Optional[str] = None,
    user_id: str = "",
    language: str = "en",
) -> Dict[str, Any]:
    logger.info("开始优化系统提示词")
    from sagents.utils.system_prompt_optimizer import SystemPromptOptimizer

    model_client, model_name = await _resolve_model_client(user_id)

    optimizer = SystemPromptOptimizer()
    optimized_prompt = await optimizer.optimize_system_prompt(
        current_prompt=original_prompt,
        optimization_goal=optimization_goal,
        model=model_name,
        llm_client=model_client,
        language=language,
    )

    if not optimized_prompt:
        raise SageHTTPException(
            message_key="agent.prompt_optimize_failed",
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


def _get_sage_home() -> Path:
    sage_home = Path.home() / ".sage"
    sage_home.mkdir(parents=True, exist_ok=True)
    return sage_home


async def _resolve_default_llm_provider_id(user_id: str = "") -> str:
    provider_dao = LLMProviderDao()
    default_provider = await provider_dao.get_default(user_id=user_id or None)
    if default_provider:
        return default_provider.id

    providers = await provider_dao.get_list(user_id=user_id or None)
    if providers:
        return providers[0].id

    raise SageHTTPException(
        status_code=500,
        message_key="agent.no_provider_configured",
        error_detail="No LLM provider configured",
    )


def _build_openclaw_agent_config(
    llm_provider_id: str,
    available_skills: List[str],
) -> Dict[str, Any]:
    return {
        "name": DEFAULT_OPENCLAW_AGENT_NAME,
        "description": DEFAULT_OPENCLAW_AGENT_DESCRIPTION,
        "maxLoopCount": 100,
        "memoryType": "session",
        "agentMode": "fibre",
        "availableTools": DEFAULT_OPENCLAW_AGENT_TOOLS.copy(),
        "availableSkills": list(available_skills),
        "systemPrefix": "",
        "llm_provider_id": llm_provider_id,
    }


def _is_valid_skill_dir(path: Path) -> bool:
    if not path.is_dir():
        return False

    try:
        for child in path.iterdir():
            if child.is_file() and child.name.lower() == "skill.md":
                return True
    except Exception as e:
        logger.warning(f"读取 skill 目录失败 {path}: {e}")
    return False


def _detect_openclaw_skill_dirs(openclaw_home: Path) -> List[Path]:
    candidates = [
        openclaw_home / "skills",
        openclaw_home / "workspace" / "skills",
        openclaw_home / "users" / "openclaw" / "skills",
        openclaw_home / "users" / "default" / "skills",
        openclaw_home / "agents" / "main" / "skills",
        Path.home() / "skills",
    ]

    discovered: List[Path] = []
    seen = set()

    def _register(path: Path) -> None:
        normalized = str(path.resolve()) if path.exists() else str(path)
        if normalized in seen:
            return
        seen.add(normalized)
        discovered.append(path)

    for candidate in candidates:
        if candidate.exists() and candidate.is_dir():
            _register(candidate)

    try:
        for path in openclaw_home.rglob("skills"):
            if path.is_dir():
                _register(path)
    except Exception as e:
        logger.warning(f"扫描 OpenClaw skills 目录失败: {e}")

    return discovered


def _collect_openclaw_skill_sources(skill_dirs: List[Path]) -> Dict[str, Path]:
    skill_sources: Dict[str, Path] = {}

    for skill_dir in skill_dirs:
        try:
            for child in skill_dir.iterdir():
                if _is_valid_skill_dir(child):
                    skill_sources.setdefault(child.name, child)
        except Exception as e:
            logger.warning(f"读取 OpenClaw skills 根目录失败 {skill_dir}: {e}")

    return skill_sources


def _copy_directory_contents(
    source_dir: Path,
    target_dir: Path,
    exclude_names: Optional[set[str]] = None,
) -> None:
    if not source_dir.exists() or not source_dir.is_dir():
        raise SageHTTPException(
            status_code=500,
            message_key="agent.source_dir_missing",
            message_params={"source_dir": str(source_dir)},
            error_detail=str(source_dir),
        )

    target_dir.mkdir(parents=True, exist_ok=True)
    excluded = exclude_names or set()

    for child in source_dir.iterdir():
        if child.name in excluded:
            continue

        target_path = target_dir / child.name
        if child.is_dir():
            shutil.copytree(child, target_path, dirs_exist_ok=True)
        else:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(child, target_path)


def _copy_docs_to_workspace(agent_workspace: Path) -> None:
    """
    将项目文档复制到 Agent 工作空间中

    Args:
        agent_workspace: Agent 工作空间路径
    """
    # 获取项目根目录（假设当前文件在 common/services/ 下）
    project_root = Path(__file__).parent.parent.parent.parent
    docs_dir = project_root / "docs"

    if not docs_dir.exists() or not docs_dir.is_dir():
        logger.warning(f"Docs 目录不存在: {docs_dir}")
        return

    # 目标目录：workspace/docs
    target_docs_dir = agent_workspace / "docs"

    try:
        # 只复制 en 和 zh 目录下的 markdown 文件
        for lang in ["en", "zh"]:
            lang_dir = docs_dir / lang
            if lang_dir.exists() and lang_dir.is_dir():
                target_lang_dir = target_docs_dir / lang
                target_lang_dir.mkdir(parents=True, exist_ok=True)

                # 复制所有 .md 文件
                for md_file in lang_dir.glob("*.md"):
                    target_file = target_lang_dir / md_file.name
                    shutil.copy2(md_file, target_file)
                    logger.debug(f"复制文档: {md_file.name} -> {target_file}")

        logger.info(f"Docs 文档已复制到 Agent 工作空间: {target_docs_dir}")
    except Exception as e:
        logger.warning(f"复制 Docs 文档失败: {e}")


def _link_openclaw_skills(
    agent_workspace: Path, skill_sources: Dict[str, Path]
) -> List[str]:
    if not skill_sources:
        return []

    target_root = agent_workspace / "skills"
    target_root.mkdir(parents=True, exist_ok=True)

    linked_skills: List[str] = []
    for skill_name, source_path in skill_sources.items():
        target_path = target_root / skill_name
        if target_path.exists() or target_path.is_symlink():
            linked_skills.append(skill_name)
            continue

        try:
            target_path.symlink_to(source_path.resolve())
        except OSError:
            shutil.copytree(source_path, target_path, dirs_exist_ok=True)
        linked_skills.append(skill_name)

    return linked_skills


def _sync_agent_skills_to_global(agent_workspace: Path) -> List[str]:
    agent_skills_dir = agent_workspace / "skills"
    if not agent_skills_dir.exists() or not agent_skills_dir.is_dir():
        return []

    sage_skills_dir = _get_sage_home() / "skills"
    sage_skills_dir.mkdir(parents=True, exist_ok=True)

    synced_skills: List[str] = []
    for skill_path in agent_skills_dir.iterdir():
        if not _is_valid_skill_dir(skill_path):
            continue

        target_path = sage_skills_dir / skill_path.name
        if target_path.exists() and not target_path.is_dir():
            target_path.unlink()

        shutil.copytree(skill_path, target_path, dirs_exist_ok=True)
        synced_skills.append(skill_path.name)

    try:
        from sagents.skill import get_skill_manager

        tm = get_skill_manager()
        if tm:
            tm.reload()
    except Exception as e:
        logger.warning(f"刷新全局技能管理器失败: {e}")

    return synced_skills


def _load_openclaw_skill_sources_sync(
    openclaw_home: Path,
) -> Tuple[List[Path], Dict[str, Path], List[str]]:
    skill_dirs = _detect_openclaw_skill_dirs(openclaw_home)
    skill_sources = _collect_openclaw_skill_sources(skill_dirs)
    available_skills = sorted(skill_sources.keys())
    return skill_dirs, skill_sources, available_skills


def _import_openclaw_workspace_assets_sync(
    openclaw_workspace: Path,
    agent_workspace: Path,
    skill_dirs: List[Path],
    skill_sources: Dict[str, Path],
) -> Tuple[List[str], List[str]]:
    exclude_names = (
        {"skills"} if (openclaw_workspace / "skills") in skill_dirs else set()
    )
    _copy_directory_contents(openclaw_workspace, agent_workspace, exclude_names)

    linked_skills = _link_openclaw_skills(agent_workspace, skill_sources)
    synced_skills = _sync_agent_skills_to_global(agent_workspace)
    return linked_skills, synced_skills


def _cleanup_agent_workspace_skills(
    agent_id: str,
    agent_config: Dict[str, Any],
    user_id: str = "",
) -> None:
    cleanup_unselected_skills(
        agent_id,
        agent_config,
        user_id=user_id,
        app_mode=_get_cfg().app_mode,
    )


# 保留旧函数名以兼容现有代码
_cleanup_desktop_agent_workspace_skills = _cleanup_agent_workspace_skills


async def import_openclaw_agent(user_id: str = "") -> Dict[str, Any]:
    openclaw_home = Path.home() / ".openclaw"
    openclaw_workspace = openclaw_home / "workspace"

    if not openclaw_home.exists():
        raise SageHTTPException(
            status_code=500,
            message_key="agent.openclaw_data_missing",
            error_detail=str(openclaw_home),
        )

    if not openclaw_workspace.exists() or not openclaw_workspace.is_dir():
        raise SageHTTPException(
            status_code=500,
            message_key="agent.openclaw_workspace_missing",
            error_detail=str(openclaw_workspace),
        )

    llm_provider_id = await _resolve_default_llm_provider_id(user_id=user_id)
    skill_dirs, skill_sources, available_skills = await asyncio.to_thread(
        _load_openclaw_skill_sources_sync,
        openclaw_home,
    )

    agent_config = _build_openclaw_agent_config(
        llm_provider_id=llm_provider_id,
        available_skills=available_skills,
    )

    created_agent: Optional[Agent] = None
    agent_workspace: Optional[Path] = None

    try:
        created_agent = await create_agent(
            DEFAULT_OPENCLAW_AGENT_NAME, agent_config, user_id=user_id
        )

        agent_workspace = get_agent_workspace_root(
            created_agent.agent_id,
            app_mode="desktop",
            ensure_exists=True,
        )
        linked_skills, synced_skills = await asyncio.to_thread(
            _import_openclaw_workspace_assets_sync,
            openclaw_workspace,
            agent_workspace,
            skill_dirs,
            skill_sources,
        )

        logger.info(
            f"OpenClaw 导入完成: agent_id={created_agent.agent_id}, "
            f"workspace={openclaw_workspace}, skills={linked_skills}"
        )

        return {
            "agent_id": created_agent.agent_id,
            "agent_name": created_agent.name,
            "workspace_source": str(openclaw_workspace),
            "skill_source_dirs": [str(path) for path in skill_dirs],
            "linked_skills": linked_skills,
            "linked_skill_count": len(linked_skills),
            "synced_skill_count": len(synced_skills),
        }
    except Exception as e:
        if agent_workspace and agent_workspace.exists():
            await asyncio.to_thread(shutil.rmtree, agent_workspace, ignore_errors=True)

        if created_agent:
            try:
                await AgentConfigDao().delete_by_id(created_agent.agent_id)
            except Exception as cleanup_error:
                logger.warning(f"清理导入失败的 Agent 记录时出错: {cleanup_error}")

        if isinstance(e, SageHTTPException):
            raise

        logger.exception("导入 OpenClaw Agent 失败")
        raise SageHTTPException(
            status_code=500,
            message_key="agent.openclaw_import_failed",
            message_params={"message": str(e)},
            error_detail=str(e),
        )


async def get_agent_authorized_users(
    agent_id: str, user_id: str, role: str
) -> List[str]:
    dao = AgentConfigDao()
    agent = await dao.get_by_id(agent_id)
    if not agent:
        raise SageHTTPException(message_key="agent.not_found", error_detail="not found")

    if role != "admin" and agent.user_id != user_id:
        raise SageHTTPException(
            message_key="agent.auth_view_forbidden", error_detail="forbidden"
        )

    return await dao.get_authorized_users(agent_id)


async def update_agent_authorizations(
    agent_id: str,
    authorized_user_ids: List[str],
    user_id: str,
    role: str,
) -> None:
    dao = AgentConfigDao()
    agent = await dao.get_by_id(agent_id)
    if not agent:
        raise SageHTTPException(message_key="agent.not_found", error_detail="not found")

    if role != "admin" and agent.user_id != user_id:
        raise SageHTTPException(
            message_key="agent.auth_modify_forbidden", error_detail="forbidden"
        )

    if agent.user_id in authorized_user_ids:
        authorized_user_ids.remove(agent.user_id)

    await dao.update_authorizations(agent_id, authorized_user_ids)


def get_server_agent_workspace_path(agent_id: str, user_id: str) -> str:
    return str(
        get_agent_workspace_root(
            agent_id,
            user_id=user_id,
            app_mode="server",
            ensure_exists=False,
        )
    )


def get_desktop_agent_workspace_path(agent_id: str) -> Path:
    return get_agent_workspace_root(
        agent_id,
        app_mode="desktop",
        ensure_exists=False,
    )


async def get_server_file_workspace(
    agent_id: str,
    user_id: str,
    *,
    path: Optional[str] = None,
    max_depth: Optional[int] = None,
) -> Dict[str, Any]:
    return await asyncio.to_thread(
        list_workspace_files,
        get_server_agent_workspace_path(agent_id, user_id),
        agent_id,
        path,
        max_depth,
    )


async def download_server_agent_file(
    agent_id: str,
    user_id: str,
    file_path: str,
) -> Tuple[str, str, str]:
    return await asyncio.to_thread(
        prepare_workspace_download,
        get_server_agent_workspace_path(agent_id, user_id),
        file_path,
    )


async def stat_server_agent_files(
    agent_id: str,
    user_id: str,
    paths: List[str],
    *,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    sandbox_result = await _stat_live_session_sandbox_files(session_id, paths)
    if sandbox_result is not None:
        return sandbox_result

    return await asyncio.to_thread(
        stat_workspace_files,
        get_server_agent_workspace_path(agent_id, user_id),
        paths,
        True,
    )


async def delete_server_agent_file(agent_id: str, user_id: str, file_path: str) -> bool:
    return await asyncio.to_thread(
        delete_workspace_entry,
        get_server_agent_workspace_path(agent_id, user_id),
        file_path,
    )


async def delete_server_agent_workspace(agent_id: str, user_id: str) -> Dict[str, Any]:
    workspace_path = Path(get_server_agent_workspace_path(agent_id, user_id))
    return await asyncio.to_thread(
        _remove_agent_workspace_directory,
        workspace_path,
        agent_id,
        user_id,
    )


async def get_desktop_file_workspace(
    agent_id: str,
    *,
    path: Optional[str] = None,
    max_depth: Optional[int] = None,
) -> Dict[str, Any]:
    return await asyncio.to_thread(
        list_workspace_files,
        get_desktop_agent_workspace_path(agent_id),
        agent_id,
        path,
        max_depth,
    )


async def download_desktop_agent_file(
    agent_id: str, file_path: str
) -> Tuple[str, str, str]:
    return await asyncio.to_thread(
        prepare_workspace_download,
        get_desktop_agent_workspace_path(agent_id),
        file_path,
    )


async def stat_desktop_agent_files(
    agent_id: str,
    paths: List[str],
    *,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    sandbox_result = await _stat_live_session_sandbox_files(session_id, paths)
    if sandbox_result is not None:
        return sandbox_result

    return await asyncio.to_thread(
        stat_workspace_files,
        get_desktop_agent_workspace_path(agent_id),
        paths,
    )


async def delete_desktop_agent_file(agent_id: str, file_path: str) -> bool:
    return await asyncio.to_thread(
        delete_workspace_entry,
        get_desktop_agent_workspace_path(agent_id),
        file_path,
    )


async def upload_server_agent_file(
    agent_id: str,
    user_id: str,
    filename: str,
    source_file,
    target_path: str = "",
) -> Dict[str, Any]:
    return await asyncio.to_thread(
        save_workspace_upload,
        get_server_agent_workspace_path(agent_id, user_id),
        filename,
        source_file,
        target_path,
    )


async def download_url_to_server_agent_file(
    agent_id: str,
    user_id: str,
    source_url: str,
    filename: str,
    target_path: str = "",
) -> Dict[str, Any]:
    parsed = urlparse((source_url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SageHTTPException(
            status_code=400,
            message_key="agent.workspace_invalid_source_url",
            error_detail="Only http(s) source_url is supported",
        )

    try:
        import httpx
    except ImportError as exc:
        raise SageHTTPException(
            status_code=500,
            message_key="agent.workspace_download_failed",
            error_detail="httpx is required to download workspace files",
        ) from exc

    timeout = httpx.Timeout(45.0, connect=10.0)
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        try:
            response = await client.get(source_url)
            response.raise_for_status()
        except Exception as exc:
            raise SageHTTPException(
                status_code=502,
                message_key="agent.workspace_download_failed",
                error_detail=f"Failed to download source_url: {exc}",
            ) from exc

    return await upload_server_agent_file(
        agent_id,
        user_id,
        filename,
        BytesIO(response.content),
        target_path,
    )


async def upload_desktop_agent_file(
    agent_id: str,
    filename: str,
    source_file,
    target_path: str = "",
) -> Dict[str, Any]:
    return await asyncio.to_thread(
        save_workspace_upload,
        get_desktop_agent_workspace_path(agent_id),
        filename,
        source_file,
        target_path,
    )


async def generate_agent_abilities(
    agent_id: str,
    session_id: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    language: str = "zh",
    user_id: Optional[str] = None,
) -> List[AgentAbilityItem]:
    from sagents.utils.agent_abilities import generate_agent_abilities_from_config

    from common.services.chat_utils import create_model_client
    from common.services.skill_service import list_skills_for_agent

    logger.info(f"开始为 Desktop Agent 生成能力列表: {agent_id}")

    agent = await get_agent(agent_id, user_id)
    agent_config: Dict[str, Any] = agent.config or {}

    startup_cfg = config.get_startup_config()
    llm_provider_id = agent_config.get("llm_provider_id")
    llm_provider_dao = LLMProviderDao()
    provider = (
        await llm_provider_dao.get_by_id(llm_provider_id) if llm_provider_id else None
    )

    if provider:
        raw_keys = provider.api_keys
        if isinstance(raw_keys, str):
            api_key_str = raw_keys.strip()
        elif raw_keys:
            api_key_str = ",".join(str(k).strip() for k in raw_keys if k)
        else:
            api_key_str = ""
        llm_config = {
            "api_key": api_key_str,
            "base_url": provider.base_url,
            "model": provider.model,
            "supports_multimodal": provider.supports_multimodal,
            "supports_structured_output": provider.supports_structured_output,
        }
    else:
        llm_config = {
            "api_key": startup_cfg.default_llm_api_key,
            "base_url": startup_cfg.default_llm_api_base_url,
            "model": startup_cfg.default_llm_model_name,
        }

    client = create_model_client(llm_config)
    model_name = llm_config["model"]
    skills = await list_skills_for_agent(agent_config)

    raw_items: List[Dict[str, str]] = await generate_agent_abilities_from_config(
        agent_config=agent_config,
        context=context or {},
        client=client,
        model=model_name,
        language=language,
        skills=skills,
    )
    return [AgentAbilityItem(**item) for item in raw_items]


def _resolve_workspace_file_path_candidate(
    workspace_path: str | Path, file_path: str
) -> Tuple[str, str]:
    if not workspace_path or not file_path:
        raise SageHTTPException(
            message_key="agent.workspace_path_required",
            error_detail="workspace_path or file_path missing",
        )

    workspace_str = os.fspath(workspace_path)
    workspace_abs = os.path.normcase(os.path.abspath(workspace_str))
    normalized_file_path = os.fspath(file_path).strip()

    # 兼容聊天中引用的“沙箱内绝对路径”。
    # 工作空间面板传的是相对路径；消息里引用的文件有时会是绝对路径。
    # 如果这里一律 os.path.join(workspace, file_path)，绝对路径在被前端去掉首个 `/`
    # 后会变成类似 `app/agents/...`，最终被重复拼接成：
    #   <workspace>/app/agents/.../agent_xxx/file
    # 从而触发“文件不存在”。
    if os.path.isabs(normalized_file_path):
        full_file_path = normalized_file_path
    else:
        full_file_path = os.path.join(workspace_str, normalized_file_path)

    full_file_abs = os.path.normcase(os.path.abspath(full_file_path))

    try:
        in_workspace = (
            os.path.commonpath([workspace_abs, full_file_abs]) == workspace_abs
        )
    except ValueError:
        in_workspace = False

    if not in_workspace:
        raise SageHTTPException(
            message_key="agent.workspace_access_denied",
            error_detail="Access denied: file path outside workspace",
        )

    return full_file_abs, normalized_file_path


def resolve_workspace_file_path(workspace_path: str | Path, file_path: str) -> str:
    full_file_abs, normalized_file_path = _resolve_workspace_file_path_candidate(
        workspace_path, file_path
    )

    if not os.path.exists(full_file_abs):
        raise SageHTTPException(
            message_key="agent.workspace_file_not_found",
            message_params={"path": normalized_file_path},
            error_detail=f"File not found: {normalized_file_path}",
        )

    return full_file_abs


def _resolve_workspace_listing_path(
    workspace_path: str | Path,
    path: Optional[str],
) -> Tuple[str, str]:
    workspace_str = os.fspath(workspace_path)
    workspace_abs = os.path.normcase(os.path.abspath(workspace_str))
    normalized_path = os.fspath(path or "").strip()

    if os.path.isabs(normalized_path):
        raise SageHTTPException(
            message_key="agent.workspace_access_denied",
            error_detail="Access denied: file path outside workspace",
        )

    listing_path = os.path.normpath(normalized_path) if normalized_path else ""
    if listing_path == ".":
        listing_path = ""

    full_path = (
        os.path.join(workspace_str, listing_path) if listing_path else workspace_str
    )
    full_path_abs = os.path.normcase(os.path.abspath(full_path))

    try:
        in_workspace = (
            os.path.commonpath([workspace_abs, full_path_abs]) == workspace_abs
        )
    except ValueError:
        in_workspace = False

    if not in_workspace:
        raise SageHTTPException(
            message_key="agent.workspace_access_denied",
            error_detail="Access denied: file path outside workspace",
        )

    return full_path_abs, listing_path


def list_workspace_files(
    workspace_path: str | Path,
    agent_id: str,
    path: Optional[str] = None,
    max_depth: Optional[int] = None,
) -> Dict[str, Any]:
    workspace_str = os.fspath(workspace_path)
    if max_depth is not None and max_depth < 0:
        raise SageHTTPException(
            message_key="agent.workspace_max_depth_invalid",
            error_detail="max_depth must be greater than or equal to 0",
        )

    listing_root = ""
    listing_path = os.fspath(path or "").strip()
    if workspace_str:
        listing_root, listing_path = _resolve_workspace_listing_path(
            workspace_str, path
        )

    if not workspace_str or not os.path.exists(workspace_str):
        return {
            "agent_id": agent_id,
            "files": [],
            "workspace_path": workspace_str,
            "path": listing_path,
            "max_depth": max_depth,
            "truncated_by_depth": False,
            "message": t("agent.workspace_empty", get_request_locale()),
        }

    if not os.path.exists(listing_root):
        return {
            "agent_id": agent_id,
            "files": [],
            "workspace_path": workspace_str,
            "path": listing_path,
            "max_depth": max_depth,
            "truncated_by_depth": False,
            "message": t("agent.workspace_empty", get_request_locale()),
        }

    if not os.path.isdir(listing_root):
        raise SageHTTPException(
            message_key="agent.workspace_not_directory",
            message_params={"path": listing_path or "."},
            error_detail=f"Path is not a directory: {listing_path or '.'}",
        )

    workspace_abs = os.path.abspath(workspace_str)
    files: List[Dict[str, Any]] = []
    truncated_by_depth = False
    for root, dirs, filenames in os.walk(listing_root):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        filenames = [f for f in filenames if not f.startswith(".")]
        current_relative = os.path.relpath(root, listing_root)
        current_depth = (
            0 if current_relative == "." else len(Path(current_relative).parts)
        )

        for filename in filenames:
            file_path = os.path.join(root, filename)
            relative_path = os.path.relpath(file_path, workspace_abs)
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
            relative_path = os.path.relpath(dir_path, workspace_abs)
            files.append(
                {
                    "name": dirname,
                    "path": relative_path,
                    "size": 0,
                    "modified_time": os.stat(dir_path).st_mtime,
                    "is_directory": True,
                }
            )

        if max_depth is not None and current_depth >= max_depth:
            if dirs:
                truncated_by_depth = True
            dirs[:] = []

    logger.info(f"获取工作空间文件数量：{len(files)}")
    return {
        "agent_id": agent_id,
        "files": files,
        "workspace_path": workspace_str,
        "path": listing_path,
        "max_depth": max_depth,
        "truncated_by_depth": truncated_by_depth,
        "message": "获取文件列表成功",
    }


def _workspace_stat_error_item(
    path: str,
    *,
    error_code: str,
    message: str,
) -> Dict[str, Any]:
    return {
        "path": path,
        "exists": False,
        "is_directory": False,
        "error_code": error_code,
        "message": message,
    }


async def _stat_live_session_sandbox_files(
    session_id: Optional[str],
    paths: List[str],
) -> Optional[Dict[str, Any]]:
    if not session_id:
        return None

    try:
        from sagents.utils.agent_session_helper import get_live_session_context

        session_context = get_live_session_context(
            session_id,
            log_prefix="FileWorkspaceStat",
        )
    except Exception:
        return None

    sandbox = getattr(session_context, "sandbox", None) if session_context else None
    sandbox_workspace = (
        getattr(session_context, "sandbox_agent_workspace", None)
        if session_context
        else None
    )
    if not sandbox or not sandbox_workspace:
        return None

    return await stat_sandbox_workspace_files(sandbox, sandbox_workspace, paths)


def _resolve_sandbox_workspace_file_path(
    sandbox_workspace: str,
    file_path: str,
) -> Tuple[str, str]:
    if not sandbox_workspace or not file_path:
        raise SageHTTPException(
            message_key="agent.workspace_path_required",
            error_detail="workspace_path or file_path missing",
        )

    workspace_abs = posixpath.normpath(str(sandbox_workspace))
    normalized_file_path = str(file_path).strip()
    if posixpath.isabs(normalized_file_path):
        full_file_path = normalized_file_path
    else:
        full_file_path = posixpath.join(workspace_abs, normalized_file_path)

    full_file_abs = posixpath.normpath(full_file_path)
    try:
        in_workspace = (
            posixpath.commonpath([workspace_abs, full_file_abs]) == workspace_abs
        )
    except ValueError:
        in_workspace = False

    if not in_workspace:
        raise SageHTTPException(
            message_key="agent.workspace_access_denied",
            error_detail="Access denied: file path outside workspace",
        )

    return full_file_abs, normalized_file_path


async def stat_sandbox_workspace_files(
    sandbox: Any,
    sandbox_workspace: str,
    paths: List[str],
) -> Dict[str, Any]:
    files: List[Dict[str, Any]] = []

    for requested_path in paths or []:
        normalized_path = os.fspath(requested_path or "").strip()
        try:
            full_path, display_path = _resolve_sandbox_workspace_file_path(
                sandbox_workspace,
                normalized_path,
            )
        except SageHTTPException as exc:
            files.append(
                _workspace_stat_error_item(
                    normalized_path,
                    error_code=(
                        "ACCESS_DENIED"
                        if "outside workspace" in (exc.error_detail or "")
                        else "INVALID_PATH"
                    ),
                    message=str(exc.detail),
                )
            )
            continue

        parent = posixpath.dirname(full_path.rstrip("/")) or sandbox_workspace
        target = full_path.rstrip("/")
        try:
            entries = await sandbox.list_directory(parent, include_hidden=True)
        except Exception:
            files.append(
                _workspace_stat_error_item(
                    display_path,
                    error_code="FILE_NOT_FOUND",
                    message=t(
                        "agent.workspace_file_not_found",
                        get_request_locale(),
                        {"path": display_path},
                    ),
                )
            )
            continue

        matched = next(
            (entry for entry in entries if str(entry.path).rstrip("/") == target),
            None,
        )
        if matched is None:
            files.append(
                _workspace_stat_error_item(
                    display_path,
                    error_code="FILE_NOT_FOUND",
                    message=t(
                        "agent.workspace_file_not_found",
                        get_request_locale(),
                        {"path": display_path},
                    ),
                )
            )
            continue

        is_directory = bool(matched.is_dir)
        if is_directory:
            content_type = "inode/directory"
        else:
            content_type, _ = mimetypes.guess_type(full_path)
            if content_type is None:
                content_type = "application/octet-stream"

        files.append(
            {
                "path": display_path,
                "exists": True,
                "is_directory": is_directory,
                "size": int(matched.size or 0),
                "modified_time": float(matched.modified_time or 0),
                "content_type": content_type,
            }
        )

    return {"files": files}


def stat_workspace_files(
    workspace_path: str | Path,
    paths: List[str],
    include_content_hash: bool = False,
) -> Dict[str, Any]:
    files: List[Dict[str, Any]] = []

    for requested_path in paths or []:
        normalized_path = os.fspath(requested_path or "").strip()
        try:
            full_path, display_path = _resolve_workspace_file_path_candidate(
                workspace_path,
                normalized_path,
            )
        except SageHTTPException as exc:
            files.append(
                _workspace_stat_error_item(
                    normalized_path,
                    error_code=(
                        "ACCESS_DENIED"
                        if "outside workspace" in (exc.error_detail or "")
                        else "INVALID_PATH"
                    ),
                    message=str(exc.detail),
                )
            )
            continue

        try:
            file_stat = os.stat(full_path)
        except FileNotFoundError:
            files.append(
                _workspace_stat_error_item(
                    display_path,
                    error_code="FILE_NOT_FOUND",
                    message=t(
                        "agent.workspace_file_not_found",
                        get_request_locale(),
                        {"path": display_path},
                    ),
                )
            )
            continue

        is_directory = os.path.isdir(full_path)
        if is_directory:
            content_type = "inode/directory"
        else:
            content_type, _ = mimetypes.guess_type(full_path)
            if content_type is None:
                content_type = "application/octet-stream"

        item = {
            "path": display_path,
            "exists": True,
            "is_directory": is_directory,
            "size": file_stat.st_size,
            "modified_time": file_stat.st_mtime,
            "content_type": content_type,
        }
        if include_content_hash and not is_directory:
            item["content_hash"] = _hash_workspace_file(full_path)
            item["hash_algorithm"] = _WORKSPACE_FILE_HASH_ALGORITHM
        files.append(item)

    return {"files": files}


def _hash_workspace_file(file_path: str | Path) -> str:
    digest = hashlib.md5()
    with open(file_path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare_workspace_download(
    workspace_path: str | Path,
    file_path: str,
) -> Tuple[str, str, str]:
    full_path = resolve_workspace_file_path(workspace_path, file_path)

    if os.path.isdir(full_path):
        try:
            temp_dir = tempfile.gettempdir()
            zip_filename = f"{os.path.basename(full_path)}.zip"
            zip_path = os.path.join(temp_dir, zip_filename)

            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                for root, _, files in os.walk(full_path):
                    for file in files:
                        file_abs_path = os.path.join(root, file)
                        rel_path = os.path.relpath(file_abs_path, full_path)
                        zipf.write(file_abs_path, rel_path)

            return zip_path, zip_filename, "application/zip"
        except Exception as e:
            raise SageHTTPException(
                message_key="agent.workspace_zip_failed",
                message_params={"message": str(e)},
                error_detail=f"Failed to create zip file: {str(e)}",
            )

    if not os.path.isfile(full_path):
        raise SageHTTPException(
            message_key="agent.workspace_not_file",
            message_params={"path": file_path},
            error_detail=f"Path is not a file: {file_path}",
        )

    mime_type, _ = mimetypes.guess_type(full_path)
    if mime_type is None:
        mime_type = "application/octet-stream"

    return full_path, os.path.basename(full_path), mime_type


def delete_workspace_entry(workspace_path: str | Path, file_path: str) -> bool:
    full_path = resolve_workspace_file_path(workspace_path, file_path)

    try:
        if os.path.isfile(full_path):
            os.remove(full_path)
        elif os.path.isdir(full_path):
            shutil.rmtree(full_path)
        else:
            raise SageHTTPException(
                message_key="agent.workspace_path_not_found",
                message_params={"path": file_path},
                error_detail=f"Path not found: {file_path}",
            )
        return True
    except Exception as e:
        logger.error(f"删除文件失败: {e}")
        raise SageHTTPException(
            message_key="agent.workspace_delete_failed",
            message_params={"message": str(e)},
            error_detail=f"Failed to delete file: {str(e)}",
        )


def _resolve_workspace_upload_path(
    workspace_path: str | Path,
    filename: str,
    target_path: str = "",
) -> Tuple[str, str]:
    if not filename or os.path.basename(filename) != filename:
        raise SageHTTPException(
            status_code=400,
            message_key="agent.workspace_invalid_filename",
            error_detail="Invalid filename",
        )

    workspace_str = os.fspath(workspace_path)
    workspace_abs = os.path.normcase(os.path.abspath(workspace_str))
    normalized_target = os.fspath(target_path or "").strip()

    if os.path.isabs(normalized_target):
        raise SageHTTPException(
            status_code=400,
            message_key="agent.workspace_access_denied",
            error_detail="Access denied: file path outside workspace",
        )

    relative_dir = os.path.normpath(normalized_target) if normalized_target else ""
    if relative_dir == ".":
        relative_dir = ""

    target_dir = (
        os.path.join(workspace_str, relative_dir) if relative_dir else workspace_str
    )
    file_path = os.path.join(target_dir, filename)
    file_abs = os.path.normcase(os.path.abspath(file_path))

    try:
        in_workspace = os.path.commonpath([workspace_abs, file_abs]) == workspace_abs
    except ValueError:
        in_workspace = False

    if not in_workspace:
        raise SageHTTPException(
            status_code=400,
            message_key="agent.workspace_access_denied",
            error_detail="Access denied: file path outside workspace",
        )

    return file_abs, os.path.relpath(file_abs, workspace_abs)


def save_workspace_upload(
    workspace_path: str | Path,
    filename: str,
    source_file,
    target_path: str = "",
) -> Dict[str, Any]:
    file_path, relative_path = _resolve_workspace_upload_path(
        workspace_path,
        filename,
        target_path,
    )

    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(source_file, buffer)

    file_size = os.path.getsize(file_path)
    return {
        "filename": filename,
        "path": relative_path,
        "size": file_size,
    }

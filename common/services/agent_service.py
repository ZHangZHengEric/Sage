import asyncio
import mimetypes
import os
import random
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from common.core import config
from common.core.client.chat import get_chat_client
from common.core.exceptions import SageHTTPException
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
        fibre_tools = {"sys_spawn_agent", "sys_delegate_task", "sys_finish_task"}
        tools_set.update(fibre_tools)
        logger.info(f"Agent 策略为 fibre，强制添加 fibre 工具: {fibre_tools}")

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
                detail=f"Agent '{agent_id}' 缺少名称",
                error_detail=f"agent '{agent_id}' missing name",
            )
        raise SageHTTPException(
            detail="Agent 名称不能为空",
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
            detail="最大循环次数不能为空",
            error_detail="maxLoopCount is required",
        )

    try:
        normalized_value = int(value)
    except (TypeError, ValueError):
        raise SageHTTPException(
            status_code=400,
            detail="最大循环次数必须为整数",
            error_detail="maxLoopCount must be an integer",
        )

    if normalized_value < 1:
        raise SageHTTPException(
            status_code=400,
            detail="最大循环次数不能小于 1",
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
    elif raw_value in {"simple", "multi", "fibre"}:
        normalized_value = raw_value
    else:
        normalized_value = "simple"

    agent_config[mode_key] = normalized_value
    return agent_config


def _create_model_client(client_params: Dict[str, Any], *, randomize_keys: bool = False) -> Any:
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
    timeout = client_params.get("timeout", 60 * 30)
    
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
        api_key=api_key,
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
    return next((provider for provider in providers if provider.is_default), providers[0])


async def _create_server_model_client_for_user(user_id: str) -> Tuple[Any, str]:
    provider_dao = LLMProviderDao()
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
            detail=f"Agent '{agent_id}' 不存在",
            error_detail=f"Agent '{agent_id}' 不存在",
        )

    cfg = _get_cfg()
    if cfg.app_mode == "server" and user_id and existing.user_id != user_id:
        authorized_users = await dao.get_authorized_users(agent_id)
        if user_id not in authorized_users:
            raise SageHTTPException(
                detail="无权访问该Agent",
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
                detail=f"Agent '{agent_name}' 已存在",
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
            detail=f"Agent '{agent_name}' 已存在",
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
            detail="Agent 初始化默认 inherit 目录失败",
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
            detail=f"Agent '{agent_id}' 不存在",
            error_detail=f"Agent '{agent_id}' 不存在",
        )

    normalized_config = dict(agent_config)
    agent_name = _require_agent_name(agent_name, agent_id=agent_id)
    normalized_config = _normalize_max_loop_count(normalized_config)
    normalized_config = _normalize_agent_mode(normalized_config)

    if cfg.app_mode == "desktop":
        if user_id and existing_config.user_id and existing_config.user_id != user_id:
            raise SageHTTPException(
                detail="无权更新该Agent",
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
            detail="无权更新该Agent",
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
        return _remove_agent_workspace_directory(workspace_path, agent_id, user_id or "")

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
            detail=f"Agent '{agent_id}' 不存在",
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
            detail="无权删除该Agent",
            error_detail="forbidden",
        )

    owner_uid = existing_config.user_id or user_id or ""
    await dao.delete_by_id(agent_id)
    try:
        await asyncio.to_thread(delete_agent_workspace_on_host, agent_id, owner_uid)
    except Exception as e:
        logger.error(
            f"删除 Agent 工作空间失败: agent_id={agent_id}, error={e}")
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
        tool_manager_or_proxy = ToolProxy(get_tool_manager(), available_tools)
    else:
        logger.info("使用完整的工具管理器")
        tool_manager_or_proxy = get_tool_manager()

    agent_config = await auto_gen_func.generate_agent_config(
        agent_description=agent_description,
        tool_manager=tool_manager_or_proxy,
        llm_client=model_client,
        model=model_name,
        language=language,
    )
    if not agent_config:
        raise SageHTTPException(
            detail="自动生成Agent失败",
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
        detail="未找到可用模型提供商，请先完成模型配置",
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
            detail=f"源目录不存在: {source_dir}",
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


def _link_openclaw_skills(agent_workspace: Path, skill_sources: Dict[str, Path]) -> List[str]:
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


def _load_openclaw_skill_sources_sync(openclaw_home: Path) -> Tuple[List[Path], Dict[str, Path], List[str]]:
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
    exclude_names = {"skills"} if (openclaw_workspace / "skills") in skill_dirs else set()
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
            detail="未找到 OpenClaw 数据目录 ~/.openclaw",
            error_detail=str(openclaw_home),
        )

    if not openclaw_workspace.exists() or not openclaw_workspace.is_dir():
        raise SageHTTPException(
            status_code=500,
            detail="未找到 OpenClaw workspace 目录",
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
        created_agent = await create_agent(DEFAULT_OPENCLAW_AGENT_NAME, agent_config, user_id=user_id)

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
            detail=f"导入 OpenClaw 失败: {str(e)}",
            error_detail=str(e),
        )


async def get_agent_authorized_users(agent_id: str, user_id: str, role: str) -> List[str]:
    dao = AgentConfigDao()
    agent = await dao.get_by_id(agent_id)
    if not agent:
        raise SageHTTPException(detail="Agent不存在", error_detail="not found")

    if role != "admin" and agent.user_id != user_id:
        raise SageHTTPException(detail="无权查看授权用户", error_detail="forbidden")

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
        raise SageHTTPException(detail="Agent不存在", error_detail="not found")

    if role != "admin" and agent.user_id != user_id:
        raise SageHTTPException(detail="无权修改授权", error_detail="forbidden")

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


async def get_server_file_workspace(agent_id: str, user_id: str) -> Dict[str, Any]:
    return await asyncio.to_thread(
        list_workspace_files,
        get_server_agent_workspace_path(agent_id, user_id),
        agent_id,
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


async def get_desktop_file_workspace(agent_id: str) -> Dict[str, Any]:
    return await asyncio.to_thread(
        list_workspace_files,
        get_desktop_agent_workspace_path(agent_id),
        agent_id,
    )


async def download_desktop_agent_file(agent_id: str, file_path: str) -> Tuple[str, str, str]:
    return await asyncio.to_thread(
        prepare_workspace_download,
        get_desktop_agent_workspace_path(agent_id),
        file_path,
    )


async def delete_desktop_agent_file(agent_id: str, file_path: str) -> bool:
    return await asyncio.to_thread(
        delete_workspace_entry,
        get_desktop_agent_workspace_path(agent_id),
        file_path,
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
    provider = await llm_provider_dao.get_by_id(llm_provider_id) if llm_provider_id else None

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


def resolve_workspace_file_path(workspace_path: str | Path, file_path: str) -> str:
    if not workspace_path or not file_path:
        raise SageHTTPException(
            detail="缺少必要的路径参数",
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
        in_workspace = os.path.commonpath([workspace_abs, full_file_abs]) == workspace_abs
    except ValueError:
        in_workspace = False

    if not in_workspace:
        raise SageHTTPException(
            detail="访问被拒绝：文件路径超出工作空间范围",
            error_detail="Access denied: file path outside workspace",
        )

    if not os.path.exists(full_file_abs):
        raise SageHTTPException(
            detail=f"文件不存在: {normalized_file_path}",
            error_detail=f"File not found: {normalized_file_path}",
        )

    return full_file_abs


def list_workspace_files(workspace_path: str | Path, agent_id: str) -> Dict[str, Any]:
    workspace_str = os.fspath(workspace_path)
    if not workspace_str or not os.path.exists(workspace_str):
        return {
            "agent_id": agent_id,
            "files": [],
            "message": "工作空间为空",
        }

    files: List[Dict[str, Any]] = []
    for root, dirs, filenames in os.walk(workspace_str):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        filenames = [f for f in filenames if not f.startswith(".")]

        for filename in filenames:
            file_path = os.path.join(root, filename)
            relative_path = os.path.relpath(file_path, workspace_str)
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
            relative_path = os.path.relpath(dir_path, workspace_str)
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


def delete_workspace_entry(workspace_path: str | Path, file_path: str) -> bool:
    full_path = resolve_workspace_file_path(workspace_path, file_path)

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

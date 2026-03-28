"""
Agent 业务处理模块

封装 Agent 相关的业务逻辑，供路由层调用。
"""

import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
import shutil

from loguru import logger
from sagents.skill import get_skill_manager
from sagents.tool.tool_manager import get_tool_manager
from sagents.tool.tool_proxy import ToolProxy
from sagents.utils.auto_gen_agent import AutoGenAgentFunc
from sagents.utils.system_prompt_optimizer import SystemPromptOptimizer
from sagents.utils.agent_abilities import (
    AgentAbilitiesGenerationError,
    generate_agent_abilities_from_config,
)


from .. import models
from ..core import config
from ..core.client.chat import get_chat_client
from ..core.exceptions import SageHTTPException
from ..schemas.agent import AgentAbilityItem
from ..models.llm_provider import LLMProviderDao

from .chat.utils import create_model_client
from .skill import list_skills_for_agent
# ================= 工具函数 =================


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
    """生成唯一的 Agent ID"""
    return f"agent_{uuid.uuid4().hex[:8]}"


def _get_sage_home() -> Path:
    sage_home = Path.home() / ".sage"
    sage_home.mkdir(parents=True, exist_ok=True)
    return sage_home


async def _resolve_default_llm_provider_id() -> str:
    provider_dao = LLMProviderDao()
    default_provider = await provider_dao.get_default()
    if default_provider:
        return default_provider.id

    providers = await provider_dao.get_list()
    if providers:
        return providers[0].id

    raise SageHTTPException(
        status_code=500,
        detail="未找到可用模型提供商，请先完成模型配置",
        error_detail="No LLM provider configured",
    )


def _build_openclaw_agent_config(
    llm_provider_id: str, available_skills: List[str]
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
    source_dir: Path, target_dir: Path, exclude_names: Optional[set[str]] = None
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

    tm = get_skill_manager()
    if tm:
        tm.reload()

    return synced_skills


# ================= 业务函数 =================


async def list_agents() -> List[models.Agent]:
    """获取所有 Agent 的配置并转换为响应结构"""
    dao = models.AgentConfigDao()
    all_configs = await dao.get_list()
    return all_configs


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


def _validate_and_filter_tools(agent_config: Dict[str, Any]) -> Dict[str, Any]:
    """验证并过滤掉不可用的工具"""
    tm = get_tool_manager()
    if not tm:
        return agent_config

    available_tools = agent_config.get("available_tools", []) or agent_config.get("availableTools", [])
    if not available_tools:
        return agent_config

    # 获取当前可用的工具名称列表
    valid_tool_names = set(tm.list_all_tools_name())

    # 过滤掉不可用的工具
    filtered_tools = [t for t in available_tools if t in valid_tool_names]

    if len(filtered_tools) != len(available_tools):
        removed_tools = set(available_tools) - set(filtered_tools)
        logger.warning(f"以下工具不可用，已自动移除: {removed_tools}")

        # 更新配置
        if "available_tools" in agent_config:
            agent_config["available_tools"] = filtered_tools
        if "availableTools" in agent_config:
            agent_config["availableTools"] = filtered_tools

    return agent_config


async def create_agent(
    agent_name: str, agent_config: Dict[str, Any]
) -> models.Agent:
    """创建新的 Agent，返回创建的 Agent 对象"""
    # 如果配置中包含 id，使用指定的 id，否则生成随机 id
    agent_id = agent_config.pop("id", None) or generate_agent_id()
    # 检查是否指定为默认 Agent
    is_default = agent_config.pop("is_default", False)
    logger.info(f"开始创建Agent: {agent_id}, is_default={is_default}, type={type(is_default)}")
    logger.info(f"agent_config keys after pop: {list(agent_config.keys())}")

    # 强制添加必要的工具
    agent_config = _enforce_required_tools(agent_config)

    # 验证并过滤工具
    agent_config = _validate_and_filter_tools(agent_config)

    dao = models.AgentConfigDao()
    existing_config = await dao.get_by_name(agent_name)
    if existing_config:
        raise SageHTTPException(
            status_code=500,
            detail=f"Agent '{agent_name}' 已存在",
            error_detail=f"Agent '{agent_name}' 已存在",
        )

    # 检查是否已有默认 Agent
    existing_default = await dao.get_default()
    if is_default and existing_default:
        # 如果已存在默认 Agent，新 Agent 不设为默认
        logger.warning(f"已存在默认 Agent '{existing_default.agent_id}'，新 Agent 不设为默认")
        is_default = False
    elif not existing_default:
        # 如果没有默认 Agent，自动将新 Agent 设为默认
        logger.info("没有默认 Agent，自动将新 Agent 设为默认")
        is_default = True

    orm_obj = models.Agent(
        agent_id=agent_id,
        name=agent_name,
        config=agent_config,
        is_default=is_default
    )
    await dao.save(orm_obj)
    logger.info(f"Agent {agent_id} 创建成功, is_default={is_default}")
    return orm_obj


async def get_agent(agent_id: str) -> models.Agent:
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
    return existing


async def update_agent(
    agent_id: str, agent_name: str, agent_config: Dict[str, Any]
) -> models.Agent:
    """更新指定 Agent 的配置，返回 Agent 对象"""
    logger.info(f"开始更新Agent: {agent_id}")

    # 强制添加必要的工具
    agent_config = _enforce_required_tools(agent_config)

    # 验证并过滤工具
    agent_config = _validate_and_filter_tools(agent_config)
    
    dao = models.AgentConfigDao()
    existing_config = await dao.get_by_id(agent_id)
    if not existing_config:
        raise SageHTTPException(
            status_code=500,
            detail=f"Agent '{agent_id}' 不存在",
            error_detail=f"Agent '{agent_id}' 不存在",
        )
    # 从配置中提取 is_default，如果没有则保留原有值
    is_default = agent_config.get('is_default', existing_config.is_default)
    orm_obj = models.Agent(
        agent_id=agent_id, 
        name=agent_name, 
        config=agent_config,
        is_default=is_default
    )
    # 保留原始创建时间
    orm_obj.created_at = existing_config.created_at
    await dao.save(orm_obj)
    
    # 清理工作空间中不在available_skills范围内的skills
    await _cleanup_agent_workspace_skills(agent_id, agent_config)
    
    logger.info(f"Agent {agent_id} 更新成功")
    return orm_obj


async def _cleanup_agent_workspace_skills(agent_id: str, agent_config: Dict[str, Any]) -> None:
    """
    清理agent工作空间中不在available_skills范围内的skills
    Desktop端工作空间路径: ~/.sage/agents/{agent_id}/skills
    """
    try:
        from pathlib import Path
        
        user_home = Path.home()
        sage_home = user_home / ".sage"
        agent_skills_path = sage_home / "agents" / agent_id / "skills"
        
        if not agent_skills_path.exists() or not agent_skills_path.is_dir():
            return
        
        # 获取配置中的available_skills
        allowed_skills = set()
        if agent_config:
            skills_list = agent_config.get("availableSkills") or agent_config.get("available_skills") or []
            allowed_skills = set(skills_list)
        
        # 遍历工作空间中的skills目录
        removed_skills = []
        for skill_path in agent_skills_path.iterdir():
            if not skill_path.is_dir():
                continue
            
            skill_name = skill_path.name
            # 如果skill不在allowed_skills中，删除它
            if skill_name not in allowed_skills:
                try:
                    shutil.rmtree(skill_path)
                    removed_skills.append(skill_name)
                    logger.info(f"已删除agent工作空间中的skill: {skill_name}")
                except Exception as e:
                    logger.warning(f"删除skill失败 {skill_name}: {e}")
        
        if removed_skills:
            logger.bind(agent_id=agent_id).info(f"清理agent工作空间skills完成，删除: {removed_skills}")
    except Exception as e:
        logger.bind(agent_id=agent_id).warning(f"清理agent工作空间skills失败: {e}")


async def delete_agent(agent_id: str) -> models.Agent:
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
    await dao.delete_by_id(agent_id)
    logger.info(f"Agent {agent_id} 删除成功")
    return existing_config


async def import_openclaw_agent() -> Dict[str, Any]:
    """一键导入 OpenClaw workspace 和 skills 并创建对应 Agent。"""
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

    llm_provider_id = await _resolve_default_llm_provider_id()
    skill_dirs = _detect_openclaw_skill_dirs(openclaw_home)
    skill_sources = _collect_openclaw_skill_sources(skill_dirs)
    available_skills = sorted(skill_sources.keys())

    agent_config = _build_openclaw_agent_config(
        llm_provider_id=llm_provider_id,
        available_skills=available_skills,
    )

    created_agent: Optional[models.Agent] = None
    agent_workspace: Optional[Path] = None

    try:
        created_agent = await create_agent(DEFAULT_OPENCLAW_AGENT_NAME, agent_config)

        agent_workspace = _get_sage_home() / "agents" / created_agent.agent_id
        exclude_names = {"skills"} if (openclaw_workspace / "skills") in skill_dirs else set()
        _copy_directory_contents(openclaw_workspace, agent_workspace, exclude_names)

        linked_skills = _link_openclaw_skills(agent_workspace, skill_sources)
        synced_skills = _sync_agent_skills_to_global(agent_workspace)

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
            shutil.rmtree(agent_workspace, ignore_errors=True)

        if created_agent:
            try:
                await models.AgentConfigDao().delete_by_id(created_agent.agent_id)
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


async def generate_agent_abilities(
    agent_id: str,
    session_id: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    language: str = "zh",
) -> List[AgentAbilityItem]:
    """Desktop 端：基于 Agent 配置生成能力卡片列表"""
    logger.info(f"开始为 Desktop Agent 生成能力列表: {agent_id}")

    # 1. Desktop 端没有多租户，直接读取 Agent 配置
    agent = await get_agent(agent_id)
    agent_config: Dict[str, Any] = agent.config or {}

    # 能力列表始终用「当前 Agent 对应的配置」自己建 client，不依赖全局 Pool
    startup_cfg = config.get_startup_config()
    llm_provider_id = agent_config.get("llm_provider_id")
    llm_provider_dao = LLMProviderDao()
    provider = await llm_provider_dao.get_by_id(llm_provider_id) if llm_provider_id else None

    if provider:
        # api_keys 在模型中为 List[str]；若为单字符串则直接使用，避免 join 成逐字符
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
        }
    else:
        llm_config = {
            "api_key": startup_cfg.default_llm_api_key,
            "base_url": startup_cfg.default_llm_base_url,
            "model": startup_cfg.default_llm_model_name,
        }
    client = create_model_client(llm_config)
    model_name = llm_config["model"]

    skills = await list_skills_for_agent(agent_config)

    # 3. 调用通用能力生成工具
    raw_items: List[Dict[str, str]] = await generate_agent_abilities_from_config(
        agent_config=agent_config,
        context=context or {},
        client=client,
        model=model_name,
        language=language,
        skills=skills,
    )

    # 4. 转成 Pydantic 模型
    return [AgentAbilityItem(**item) for item in raw_items]

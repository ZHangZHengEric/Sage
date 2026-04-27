import asyncio
import importlib
import json
import os
import random
import re
import shutil
import string
import time
import traceback
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from loguru import logger
from sagents.context.session_context import get_session_run_lock
from sagents.sagents import SAgent
from sagents.session_runtime import get_global_session_manager
from sagents.tool import get_tool_manager
from sagents.utils.lock_manager import safe_release
from sagents.utils.user_input_optimizer import UserInputOptimizer

from common.core import config
from common.core.exceptions import SageHTTPException
from common.models.agent import AgentConfigDao
from common.models.base import get_local_now
from common.models.conversation import ConversationDao
from common.models.im_channel import IMChannelConfigDao
from common.models.kdb import KdbDao
from common.models.llm_provider import LLMProviderDao
from common.services.chat_processor import ContentProcessor
from common.services import token_usage_service
from common.services.agent_workspace import (
    get_agent_workspace_root,
    get_agent_skill_dir,
)
from common.services.chat_utils import (
    create_model_client,
    create_skill_proxy,
    create_tool_proxy,
    get_sessions_root,
)
from common.schemas.chat import CustomSubAgentConfig, StreamRequest


def _get_cfg() -> config.StartupConfig:
    cfg = config.get_startup_config()
    if not cfg:
        raise RuntimeError("Startup config not initialized")
    return cfg


def _is_desktop_mode() -> bool:
    return _get_cfg().app_mode == "desktop"


def _chat_exception(detail: str) -> SageHTTPException:
    kwargs: Dict[str, Any] = {"detail": detail}
    if _is_desktop_mode():
        kwargs["status_code"] = 500
    return SageHTTPException(**kwargs)


def _fill_if_none(request: StreamRequest, field: str, value: Any) -> None:
    if getattr(request, field) is None:
        setattr(request, field, value)


def _merge_dict(request: StreamRequest, field: str, value: Dict[str, Any]) -> None:
    current = getattr(request, field)
    if current is None:
        setattr(request, field, value)
    elif isinstance(current, dict) and isinstance(value, dict):
        merged = value.copy()
        merged.update(current)
        setattr(request, field, merged)


def _get_provider_api_key(provider: Any) -> Optional[str]:
    if _is_desktop_mode():
        api_keys = getattr(provider, "api_keys", None) or []
        return ",".join(api_keys) if api_keys else None
    return getattr(provider, "api_key", None)


def mark_request_execution(
    request: StreamRequest,
    *,
    request_source: str,
) -> None:
    request.request_source = request_source
    if request.execution_started_at is None:
        request.execution_started_at = get_local_now()


async def _resolve_input_optimization_model_client(
    session_id: str = "",
    agent_id: str = "",
    user_id: str = "",
) -> Tuple[Any, str]:
    from common.services.agent_service import _resolve_model_client, _create_model_client

    resolved_agent_id = agent_id or ""
    if not resolved_agent_id and session_id:
        conversation = await ConversationDao().get_by_session_id(session_id)
        if conversation and conversation.agent_id:
            resolved_agent_id = conversation.agent_id

    if resolved_agent_id:
        agent = await AgentConfigDao().get_by_id(resolved_agent_id)
        agent_config = agent.config if agent and agent.config else {}
        provider_id = agent_config.get("llm_provider_id") if isinstance(agent_config, dict) else None
        if provider_id:
            provider = await LLMProviderDao().get_by_id(provider_id)
            if provider:
                logger.info(
                    f"用户输入优化使用 Agent 模型配置: agent_id={resolved_agent_id}, provider_id={provider_id}, model={provider.model}"
                )
                return _create_model_client(
                    {
                        "api_key": _get_provider_api_key(provider),
                        "base_url": provider.base_url,
                        "model": provider.model,
                    }
                ), provider.model

    return await _resolve_model_client(user_id)


async def optimize_user_input(
    current_input: str,
    history_messages: List[Dict[str, str]],
    session_id: str = "",
    agent_id: str = "",
    user_id: str = "",
    language: str = "en",
) -> Dict[str, Any]:
    logger.info("开始优化用户输入")
    optimizer = UserInputOptimizer()
    max_attempts = 3 if _is_desktop_mode() else 1
    result: Dict[str, Any] = {}

    for attempt in range(max_attempts):
        model_client, model_name = await _resolve_input_optimization_model_client(
            session_id=session_id,
            agent_id=agent_id,
            user_id=user_id,
        )
        result = await optimizer.optimize_user_input(
            current_input=current_input,
            history_messages=history_messages,
            llm_client=model_client,
            model=model_name,
            language=language,
        )

        if result.get("success") is True and result.get("status") != "fallback":
            logger.info(f"用户输入优化成功，attempt={attempt + 1}")
            return result

        error_message = (result or {}).get("error_message", "") or ""
        is_invalid_api_key = "INVALID_API_KEY" in error_message or "AuthenticationError" == (result or {}).get("error_type")
        if not (_is_desktop_mode() and is_invalid_api_key and attempt < max_attempts - 1):
            break

        logger.warning(
            f"用户输入优化命中无效 API Key，准备重试下一组客户端，attempt={attempt + 1}/{max_attempts}"
        )

    optimized_input = (result or {}).get("optimized_input", "").strip()
    if not optimized_input:
        raise SageHTTPException(detail="用户输入优化失败", error_detail="优化结果为空")

    if result.get("status") == "fallback":
        logger.warning(
            f"用户输入优化降级为原文返回: error_type={result.get('error_type')}, error_message={result.get('error_message')}"
        )
    else:
        logger.info("用户输入优化成功")
    return result


async def optimize_user_input_stream(
    current_input: str,
    history_messages: List[Dict[str, str]],
    session_id: str = "",
    agent_id: str = "",
    user_id: str = "",
    language: str = "en",
) -> AsyncGenerator[Dict[str, Any], None]:
    logger.info("开始流式优化用户输入")
    optimizer = UserInputOptimizer()
    max_attempts = 3 if _is_desktop_mode() else 1
    fallback_result: Dict[str, Any] | None = None
    overall_start = time.perf_counter()

    yield {
        "type": "start",
        "timestamp": time.time(),
    }

    for attempt in range(max_attempts):
        resolve_start = time.perf_counter()
        model_client, model_name = await _resolve_input_optimization_model_client(
            session_id=session_id,
            agent_id=agent_id,
            user_id=user_id,
        )
        resolve_cost = time.perf_counter() - resolve_start
        logger.info(
            f"流式优化用户输入模型客户端准备完成: attempt={attempt + 1}, model={model_name}, resolve_cost={resolve_cost:.3f}s"
        )

        optimized_chunks: List[str] = []
        try:
            async for delta in optimizer.optimize_user_input_stream(
                current_input=current_input,
                history_messages=history_messages,
                llm_client=model_client,
                model=model_name,
                language=language,
            ):
                optimized_chunks.append(delta)
                yield {
                    "type": "delta",
                    "content": delta,
                    "timestamp": time.time(),
                }

            optimized_input = "".join(optimized_chunks).strip()
            if optimized_input:
                yield {
                    "type": "done",
                    "success": True,
                    "optimized_input": optimized_input,
                    "timestamp": time.time(),
                }
                total_cost = time.perf_counter() - overall_start
                logger.info(f"流式优化用户输入成功，attempt={attempt + 1}, total_cost={total_cost:.3f}s")
                return

            fallback_result = optimizer._fallback_result(current_input)
            break
        except Exception as exc:
            error_message = str(exc)
            error_type = type(exc).__name__
            is_invalid_api_key = "INVALID_API_KEY" in error_message or error_type == "AuthenticationError"
            if _is_desktop_mode() and is_invalid_api_key and attempt < max_attempts - 1:
                logger.warning(
                    f"流式优化用户输入命中无效 API Key，准备重试下一组客户端，attempt={attempt + 1}/{max_attempts}"
                )
                continue

            logger.error(f"流式优化用户输入失败: {exc}")
            logger.error(traceback.format_exc())
            fallback_result = optimizer._fallback_result(
                current_input,
                error_message=error_message,
                error_type=error_type,
            )
            break

    final_result = fallback_result or optimizer._fallback_result(current_input)
    yield {
        "type": "done",
        **final_result,
        "timestamp": time.time(),
    }


def _build_context_budget_config(request: StreamRequest) -> Dict[str, Any]:
    cfg = _get_cfg()
    llm_config = request.llm_model_config or {}
    return {
        "max_model_len": llm_config.get("max_model_len"),
        "history_ratio": cfg.context_history_ratio,
        "active_ratio": cfg.context_active_ratio,
        "max_new_message_ratio": cfg.context_max_new_message_ratio,
        "recent_turns": cfg.context_recent_turns,
    }


def _copy_sage_usage_docs_to_workspace(agent_workspace: str) -> None:
    try:
        sage_docs_source = Path.home() / ".sage" / "sage-usage-docs"
        if not sage_docs_source.exists():
            logger.debug(f"sage-usage-docs 目录不存在: {sage_docs_source}")
            return

        target_dir = Path(agent_workspace) / ".sage-docs"
        target_dir.mkdir(parents=True, exist_ok=True)

        if target_dir.exists() and any(target_dir.iterdir()):
            source_files = list(sage_docs_source.rglob("*"))
            target_files = list(target_dir.rglob("*"))
            if len(source_files) <= len(target_files):
                logger.debug(f"sage-usage-docs 已存在于 workspace: {target_dir}")
                return

        shutil.copytree(sage_docs_source, target_dir, dirs_exist_ok=True)
        logger.info(f"已将 sage-usage-docs 复制到 agent workspace: {target_dir}")
    except Exception as e:
        logger.warning(f"复制 sage-usage-docs 到 workspace 失败: {e}")


def _copy_docs_to_agent_workspace(agent_workspace: str) -> None:
    """
    将项目文档复制到 sage_usage_docs 下的 code_docs 文件夹中
    支持从源码目录、PyInstaller 打包目录、pip install 或 data_files 安装位置中查找 docs

    Args:
        agent_workspace: Agent 工作空间路径
    """
    try:
        docs_dir = None

        # 尝试从多个位置查找 docs 目录
        # 1. 源码目录（开发环境）
        project_root = Path(__file__).parent.parent.parent.parent
        possible_docs = project_root / "docs"
        if possible_docs.exists() and possible_docs.is_dir():
            docs_dir = possible_docs
            logger.debug(f"从源码目录找到 docs: {docs_dir}")

        # 2. PyInstaller 打包后的 _internal 目录（Desktop 生产环境）
        if docs_dir is None:
            # PyInstaller 运行时，sys._MEIPASS 指向临时解压目录
            import sys
            if hasattr(sys, '_MEIPASS'):
                possible_docs = Path(sys._MEIPASS) / "docs"
                if possible_docs.exists() and possible_docs.is_dir():
                    docs_dir = possible_docs
                    logger.debug(f"从 PyInstaller 目录找到 docs: {docs_dir}")

        # 3. 包安装目录（pip install 生产环境 - 旧方式）
        if docs_dir is None:
            import sagents
            package_dir = Path(sagents.__file__).parent.parent
            possible_docs = package_dir / "docs"
            if possible_docs.exists() and possible_docs.is_dir():
                docs_dir = possible_docs
                logger.debug(f"从包目录找到 docs: {docs_dir}")

        # 4. data_files 安装位置（pip install 生产环境 - 新方式）
        # data_files 会安装到 sys.prefix/share/sage/docs 或 /usr/local/share/sage/docs
        if docs_dir is None:
            import sys
            possible_paths = [
                Path(sys.prefix) / "share" / "sage" / "docs",
                Path("/usr") / "local" / "share" / "sage" / "docs",
                Path("/usr") / "share" / "sage" / "docs",
            ]
            for possible_docs in possible_paths:
                if possible_docs.exists() and possible_docs.is_dir():
                    docs_dir = possible_docs
                    logger.debug(f"从 data_files 目录找到 docs: {docs_dir}")
                    break

        # 5. 系统 site-packages 目录
        if docs_dir is None:
            import site
            for site_dir in site.getsitepackages():
                possible_docs = Path(site_dir) / "docs"
                if possible_docs.exists() and possible_docs.is_dir():
                    docs_dir = possible_docs
                    logger.debug(f"从 site-packages 找到 docs: {docs_dir}")
                    break

        if docs_dir is None:
            logger.debug("未找到 docs 目录")
            return

        # 目标目录：workspace/sage_usage_docs/code_docs
        target_docs_dir = Path(agent_workspace) / "sage_usage_docs" / "code_docs"

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

        logger.info(f"Docs 文档已复制到: {target_docs_dir}")
    except Exception as e:
        logger.warning(f"复制 Docs 文档失败: {e}")


def _copy_sage_usage_docs_to_agent_workspace_sync(
    agent_id: str,
    agent_workspace_base: str,
) -> None:
    try:
        sage_docs_source = Path.home() / ".sage" / "sage-usage-docs"
        if not sage_docs_source.exists():
            logger.debug(f"sage-usage-docs 目录不存在: {sage_docs_source}")
            return

        agent_workspace = Path(agent_workspace_base) / agent_id
        target_dir = agent_workspace / "sage_usage_docs"

        need_copy = False
        if not target_dir.exists():
            need_copy = True
            logger.info(f"sage_usage_docs 不存在，需要复制到: {target_dir}")
        else:
            source_files = list(sage_docs_source.rglob("*.md"))
            target_files = list(target_dir.rglob("*.md"))
            if len(source_files) > len(target_files):
                need_copy = True
                logger.info(
                    f"sage_usage_docs 文件数量不匹配，需要更新: {len(source_files)} vs {len(target_files)}"
                )

        if need_copy:
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copytree(sage_docs_source, target_dir, dirs_exist_ok=True)
            logger.info(f"已将 sage-usage-docs 复制到 agent workspace: {target_dir}")
        else:
            logger.debug(f"sage_usage_docs 已存在于 agent workspace: {target_dir}")
    except Exception as e:
        logger.warning(f"复制 sage-usage-docs 到 agent workspace 失败: {e}")


async def _copy_sage_usage_docs_to_agent_workspace(
    agent_id: str,
    agent_workspace_base: str,
) -> None:
    await asyncio.to_thread(
        _copy_sage_usage_docs_to_agent_workspace_sync,
        agent_id,
        agent_workspace_base,
    )


async def _register_extra_mcp_tools(request: StreamRequest) -> None:
    extra_mcp_config = request.extra_mcp_config or request.system_context.get(
        "extra_mcp_config", None
    )
    if not extra_mcp_config:
        return

    tm = get_tool_manager()
    if not tm:
        logger.warning("ToolManager not available, cannot register MCP servers")
        return

    logger.info(f"Registering {len(extra_mcp_config)} extra MCP servers")
    for key, value in extra_mcp_config.items():
        if not isinstance(value, dict):
            logger.warning(
                f"Invalid MCP config for {key}: expected dict, got {type(value)}"
            )
            continue

        if "disabled" not in value:
            value["disabled"] = False

        if not any(
            field in value for field in ["command", "sse_url", "url", "streamable_http_url"]
        ):
            logger.warning(f"Invalid MCP config for {key}: missing connection parameters")
            continue

        from common.utils.mcp_anytool_url import coalesce_anytool_streamable_url

        value = coalesce_anytool_streamable_url(key, value)
        registered_tools = await tm.register_mcp_server(key, value)
        if not registered_tools:
            logger.warning(f"Failed to register MCP server {key} with tools")

    if "extra_mcp_config" in request.system_context:
        del request.system_context["extra_mcp_config"]


def _inject_skill_tools(request: StreamRequest) -> None:
    if not request.available_skills:
        return

    current_skills = getattr(request, "available_skills", [])
    if current_skills is None:
        current_skills = []
        setattr(request, "available_skills", current_skills)

    current_tools = request.available_tools or []
    if _is_desktop_mode():
        need_tools = [
            "load_skill",
            "execute_python_code",
            "execute_shell_command",
            "file_write",
            "file_update",
        ]
    else:
        need_tools = [
            "file_read",
            "execute_python_code",
            "execute_javascript_code",
            "execute_shell_command",
            "file_write",
            "file_update",
            "load_skill",
        ]

    for tool in need_tools:
        if tool not in current_tools:
            current_tools.append(tool)

    request.available_tools = current_tools


def _strip_skill_tools_when_unavailable(request: StreamRequest) -> None:
    if request.available_skills:
        return

    current_tools = list(request.available_tools or [])
    filtered_tools = [tool for tool in current_tools if tool != "load_skill"]
    if len(filtered_tools) != len(current_tools):
        logger.info("当前会话无可用技能，已移除 load_skill 工具")
    request.available_tools = filtered_tools


async def _populate_custom_sub_agents(request: StreamRequest) -> None:
    if not request.available_sub_agent_ids:
        return

    deduped_ids: List[str] = []
    seen_ids = set()
    for agent_id in request.available_sub_agent_ids:
        normalized_agent_id = str(agent_id or "").strip()
        if not normalized_agent_id or normalized_agent_id in seen_ids:
            continue
        seen_ids.add(normalized_agent_id)
        deduped_ids.append(normalized_agent_id)

    if not deduped_ids:
        return

    sub_agent_dao = AgentConfigDao()
    sub_agents = await sub_agent_dao.get_by_ids(deduped_ids)
    request.custom_sub_agents = [
        CustomSubAgentConfig(
            agent_id=sub_agent.agent_id,
            name=sub_agent.name,
            description=sub_agent.config.get("description", ""),
            available_workflows=sub_agent.config.get("availableWorkflows", {}),
            system_context=sub_agent.config.get("systemContext", {}),
            available_tools=sub_agent.config.get("availableTools", []),
            available_skills=sub_agent.config.get("availableSkills", []),
        )
        for sub_agent in sub_agents
    ]


async def populate_request_from_agent_config(
    request: StreamRequest,
    *,
    require_agent_id: bool = False,
) -> None:
    agent = None
    if request.agent_id is None:
        if require_agent_id:
            raise _chat_exception("Agent ID 不能为空")
    else:
        agent = await AgentConfigDao().get_by_id(request.agent_id)
        if not agent or not agent.config:
            if require_agent_id:
                raise _chat_exception("Agent 不存在")
            logger.warning(f"Agent {request.agent_id} not found")
            agent = None
        else:
            request.agent_name = agent.name or "Sage Assistant"

    agent_config = agent.config if agent and agent.config else None

    if agent_config:
        if agent_config.get("name") is not None:
            request.agent_name = agent_config.get("name")
        if agent_config.get("availableTools") is not None:
            request.available_tools = agent_config.get("availableTools")
        if agent_config.get("availableSkills") is not None:
            request.available_skills = agent_config.get("availableSkills")
        if agent_config.get("availableWorkflows") is not None:
            request.available_workflows = agent_config.get("availableWorkflows")
        if agent_config.get("maxLoopCount") is not None and request.max_loop_count is None:
            request.max_loop_count = agent_config.get("maxLoopCount")
        if agent_config.get("agentMode") is not None and request.agent_mode is None:
            request.agent_mode = agent_config.get("agentMode")
        if agent_config.get("moreSuggest") is not None and request.more_suggest is None:
            request.more_suggest = agent_config.get("moreSuggest")
        if agent_config.get("systemContext") is not None:
            _merge_dict(request, "system_context", agent_config.get("systemContext"))
        if agent_config.get("systemPrefix") is not None:
            request.system_prefix = agent_config.get("systemPrefix")
        if agent_config.get("memoryType") is not None:
            request.memory_type = agent_config.get("memoryType")
        if agent_config.get("availableKnowledgeBases") is not None:
            request.available_knowledge_bases = agent_config.get("availableKnowledgeBases")
        if agent_config.get("availableSubAgentIds") is not None and request.available_sub_agent_ids is None:
            request.available_sub_agent_ids = agent_config.get("availableSubAgentIds")

        # auto_all: when subAgentSelectionMode is "auto_all" (or defaults to it),
        # auto-populate available_sub_agent_ids with all agents (excluding self)
        if request.agent_mode == "fibre" and not request.available_sub_agent_ids:
            selection_mode = agent_config.get("subAgentSelectionMode") or agent_config.get("sub_agent_selection_mode")
            configured_ids = agent_config.get("availableSubAgentIds")
            if selection_mode is None:
                selection_mode = "manual" if configured_ids else "auto_all"
            if selection_mode == "auto_all":
                all_agents = await AgentConfigDao().get_all()
                request.available_sub_agent_ids = [
                    a.agent_id for a in all_agents
                    if a.agent_id and a.agent_id != request.agent_id
                ]

    if request.agent_name is None:
        request.agent_name = "Sage Assistant"

    if request.llm_model_config is None:
        request.llm_model_config = {}

    provider_dao = LLMProviderDao()
    provider_id = agent_config.get("llm_provider_id") if agent_config else None
    if provider_id:
        provider = await provider_dao.get_by_id(provider_id)
        request.llm_model_config["base_url"] = provider.base_url
        request.llm_model_config["api_key"] = _get_provider_api_key(provider)
        request.llm_model_config["model"] = provider.model
        if provider.max_tokens is not None:
            request.llm_model_config["max_tokens"] = provider.max_tokens
        request.llm_model_config["temperature"] = provider.temperature
        request.llm_model_config["top_p"] = provider.top_p
        request.llm_model_config["presence_penalty"] = provider.presence_penalty
        request.llm_model_config["max_model_len"] = provider.max_model_len
        request.llm_model_config["supports_multimodal"] = provider.supports_multimodal
        request.llm_model_config["supports_structured_output"] = provider.supports_structured_output
    else:
        provider = await provider_dao.get_default()
        if request.llm_model_config.get("base_url") is None:
            request.llm_model_config["base_url"] = provider.base_url
        if request.llm_model_config.get("api_key") is None:
            request.llm_model_config["api_key"] = _get_provider_api_key(provider)
        if request.llm_model_config.get("model") is None:
            request.llm_model_config["model"] = provider.model
        if request.llm_model_config.get("max_tokens") is None and provider.max_tokens is not None:
            request.llm_model_config["max_tokens"] = provider.max_tokens
        if request.llm_model_config.get("temperature") is None:
            request.llm_model_config["temperature"] = provider.temperature
        if request.llm_model_config.get("top_p") is None:
            request.llm_model_config["top_p"] = provider.top_p
        if request.llm_model_config.get("presence_penalty") is None:
            request.llm_model_config["presence_penalty"] = provider.presence_penalty
        if request.llm_model_config.get("max_model_len") is None:
            request.llm_model_config["max_model_len"] = provider.max_model_len
        if request.llm_model_config.get("supports_multimodal") is None:
            request.llm_model_config["supports_multimodal"] = provider.supports_multimodal
        if request.llm_model_config.get("supports_structured_output") is None:
            request.llm_model_config["supports_structured_output"] = provider.supports_structured_output

    # 处理快速模型配置
    fast_provider_id = agent_config.get("fast_llm_provider_id") if agent_config else None
    if fast_provider_id:
        fast_provider = await provider_dao.get_by_id(fast_provider_id)
        if fast_provider:
            request.llm_model_config["fast_api_key"] = _get_provider_api_key(fast_provider)
            request.llm_model_config["fast_base_url"] = fast_provider.base_url
            request.llm_model_config["fast_model_name"] = fast_provider.model
            logger.info(f"Fast model configured: {fast_provider.model}")

    if request.max_loop_count is None:
        raise SageHTTPException(
            status_code=400,
            detail="max_loop_count 必须显式传入",
            error_detail="Missing required field: max_loop_count",
        )

    _fill_if_none(request, "available_tools", [])
    _fill_if_none(request, "available_skills", [])
    _merge_dict(request, "available_workflows", {})
    _fill_if_none(request, "multi_agent", False)
    _fill_if_none(request, "more_suggest", False)
    _merge_dict(request, "system_context", {})
    _fill_if_none(request, "system_prefix", "")
    _fill_if_none(request, "memory_type", "session")
    _fill_if_none(request, "available_knowledge_bases", [])
    _fill_if_none(request, "available_sub_agent_ids", [])

    # 注意：此处不再每次 prompt 都同步 skills 到 workspace。
    # skills 同步统一由"Agent 编辑页面"在 create/update agent 时触发
    # （common/services/agent_service.py 中的 sync_selected_skills_to_workspace 调用），
    # 运行时如沙箱里缺少某个 skill 目录，则由
    # SandboxSkillManager.sync_from_host 按需 copy_from_host 一次性补齐，
    # 这样避免每次会话刷新 mtime / 覆盖用户在 Agent workspace 里的手改。

    if _is_desktop_mode():
        try:
            all_im_configs = await IMChannelConfigDao().get_all_configs()
            im_enabled = any(config.get("enabled", False) for config in all_im_configs.values())
            if im_enabled and "send_message_through_im" not in request.available_tools:
                request.available_tools = list(request.available_tools) + [
                    "send_message_through_im"
                ]
                logger.info("[Chat] Added send_message_through_im tool (IM provider enabled)")
        except Exception as e:
            logger.warning(f"[Chat] Failed to check IM config: {e}")
    else:
        _merge_dict(
            request,
            "system_context",
            {"本次会话用户id": request.user_id or "default_user"},
        )

    if request.agent_id and agent:
        _merge_dict(request, "system_context", {"当前AgentId": request.agent_id})
        if _is_desktop_mode():
            sage_home = os.path.join(Path.home(), ".sage")
            agent_workspace = os.path.join(sage_home, "agents", request.agent_id)
            # 复制 sage-usage-docs
            await _copy_sage_usage_docs_to_agent_workspace(
                request.agent_id,
                os.path.join(sage_home, "agents"),
            )
            # 复制项目 docs 到 agent workspace
            await asyncio.to_thread(_copy_docs_to_agent_workspace, agent_workspace)

    if not _is_desktop_mode() and request.available_knowledge_bases:
        kdb_dao = KdbDao()
        kdbs, _ = await kdb_dao.get_kdbs_paginated(
            kdb_ids=request.available_knowledge_bases,
            data_type=None,
            query_name=None,
            page=1,
            page_size=1000,
        )
        if kdbs:
            kdb_context = {
                f"{kdb.name}数据库的index_name": kdb.get_index_name() for kdb in kdbs
            }
            _merge_dict(request, "system_context", kdb_context)
            if "retrieve_on_zavixai_db" not in request.available_tools:
                request.available_tools.append("retrieve_on_zavixai_db")

    _inject_skill_tools(request)
    _strip_skill_tools_when_unavailable(request)
    await _populate_custom_sub_agents(request)
    request.context_budget_config = _build_context_budget_config(request)
    await _register_extra_mcp_tools(request)


class SageStreamService:
    def __init__(self, request: StreamRequest):
        self.request = request
        self.cfg = _get_cfg()

        self.runtime_user_id = self.request.user_id or "default_user"
        self.runtime_agent_id = self.request.agent_id or "".join(
            random.choices(string.ascii_letters, k=8)
        )

        if _is_desktop_mode():
            self.sessions_root = Path(get_sessions_root())
            self.sessions_root.mkdir(parents=True, exist_ok=True)
            self._workspace_existed = True
            self.agent_workspace_root = get_agent_workspace_root(
                self.runtime_agent_id,
                app_mode="desktop",
                ensure_exists=True,
            )
            self.agent_workspace = str(self.agent_workspace_root)
        else:
            workspace_root = get_agent_workspace_root(
                self.runtime_agent_id,
                user_id=self.runtime_user_id,
                app_mode="server",
                ensure_exists=False,
            )
            self._workspace_existed = workspace_root.exists()
            workspace_root.mkdir(parents=True, exist_ok=True)
            self.agent_workspace_root = workspace_root
            self.agent_workspace = str(self.agent_workspace_root)

        self.tool_manager = create_tool_proxy(request.available_tools)
        self.skill_manager, self.agent_skill_manager = create_skill_proxy(
            request.available_skills,
            user_id=self.request.user_id,
            agent_workspace=self.agent_workspace,
        )
        self.model_client = create_model_client(request.llm_model_config)
        if _is_desktop_mode():
            self.sage_engine = SAgent(
                session_root_space=str(self.sessions_root),
                enable_obs=True,
                sandbox_type="local",
            )
        else:
            self.sage_engine = SAgent(
                session_root_space=self.cfg.session_dir,
                enable_obs=self.cfg.trace_jaeger_endpoint is not None,
            )

    async def initialize_workspace_assets(self) -> None:
        if _is_desktop_mode():
            return

        if (not self._workspace_existed) and self.request.agent_id:
            inherit_service = importlib.import_module("app.server.services.agent_inherit")
            await asyncio.to_thread(
                inherit_service.copy_agent_inherit_to_workspace,
                self.request.agent_id,
                self.agent_workspace,
            )

        await asyncio.to_thread(_copy_sage_usage_docs_to_workspace, self.agent_workspace)

    async def process_stream(self):
        session_id = self.request.session_id
        messages = []
        for msg in self.request.messages:
            message_dict = msg.model_dump()
            if "message_id" not in message_dict or not message_dict["message_id"]:
                message_dict["message_id"] = str(uuid.uuid4())
            messages.append(message_dict)

        await _ensure_conversation(self.request)
        try:
            from sagents.utils.sandbox.config import VolumeMount

            sandbox_agent_workspace = self.agent_workspace
            volume_mounts = [
                VolumeMount(
                    host_path=sandbox_agent_workspace,
                    mount_path=sandbox_agent_workspace,
                )
            ]

            run_kwargs: Dict[str, Any] = {
                "session_id": session_id,
                "input_messages": messages,
                "tool_manager": self.tool_manager,
                "skill_manager": self.skill_manager,
                "model": self.model_client,
                "model_config": self.request.llm_model_config,
                "system_prefix": self.request.system_prefix,
                "sandbox_agent_workspace": sandbox_agent_workspace,
                "volume_mounts": volume_mounts,
                "agent_id": self.request.agent_id,
                "max_loop_count": self.request.max_loop_count,
                "agent_mode": self.request.agent_mode,
                "system_context": self.request.system_context,
                "available_workflows": self.request.available_workflows,
                "context_budget_config": self.request.context_budget_config,
            }

            if _is_desktop_mode():
                run_kwargs.update(
                    {
                        "user_id": "default_user",
                        "more_suggest": self.request.more_suggest,
                        "force_summary": self.request.force_summary,
                        "custom_sub_agents": [
                            {
                                "agent_id": agent.agent_id,
                                "name": agent.name,
                                "description": agent.description,
                            }
                            for agent in (self.request.custom_sub_agents or [])
                        ]
                        if self.request.custom_sub_agents
                        else None,
                    }
                )
            else:
                run_kwargs.update(
                    {
                        "user_id": self.request.user_id,
                        "custom_sub_agents": [
                            agent.model_dump()
                            for agent in (self.request.custom_sub_agents or [])
                        ]
                        if self.request.custom_sub_agents
                        else None,
                    }
                )

            stream_result = self.sage_engine.run_stream(**run_kwargs)

            async for chunk in stream_result:
                if not isinstance(chunk, (list, tuple)):
                    continue
                for message in chunk:
                    result = message.to_dict()
                    result = ContentProcessor.clean_content(result)
                    yield result
        except Exception as e:
            logger.bind(session_id=session_id).error(
                f"❌ 流式处理异常: {traceback.format_exc()}"
            )
            yield {
                "type": "error",
                "content": f"处理失败: {str(e)}",
                "role": "assistant",
                "message_id": str(uuid.uuid4()),
                "session_id": session_id,
            }


async def prepare_session(request: StreamRequest) -> Tuple[SageStreamService, asyncio.Lock]:
    session_id = request.session_id or str(uuid.uuid4())
    request.session_id = session_id
    logger.bind(session_id=session_id).info(f"Chat request - 「{request.model_dump()}」")

    lock = get_session_run_lock(session_id)
    acquired = False
    if lock.locked():
        session = get_global_session_manager().get_live_session(session_id)
        if not session or not session.is_interrupted():
            raise _chat_exception("会话正在运行中，请先调用 interrupt 或使用不同的会话ID")

    try:
        lock_wait_start = time.perf_counter()
        await asyncio.wait_for(lock.acquire(), timeout=10)
        acquired = True
        lock_wait_cost = time.perf_counter() - lock_wait_start
        if lock_wait_cost > 0.2:
            logger.bind(session_id=session_id).warning(
                f"Session lock wait slow: {lock_wait_cost:.3f}s"
            )
    except asyncio.TimeoutError:
        raise _chat_exception("会话正在清理中，请稍后重试")

    try:
        stream_service = SageStreamService(request)
        await stream_service.initialize_workspace_assets()
        return stream_service, lock
    except Exception as e:
        if acquired:
            await safe_release(
                lock,
                session_id,
                f"prepare_session 构造失败，保留原始异常: {type(e).__name__}",
            )
        raise


async def execute_chat_session(
    stream_service: SageStreamService,
    mode: Optional[str] = None,
    **kwargs: Any,
):
    session_id = stream_service.request.session_id
    request = stream_service.request
    original_skills = (
        stream_service.agent_skill_manager.list_skills()
        if stream_service.agent_skill_manager
        else []
    )

    stream_counter = 0
    last_activity_time = time.time()
    token_usage_persisted = False
    token_usage_payload: Optional[Dict[str, Any]] = None
    try:
        async for result in stream_service.process_stream():
            stream_counter += 1
            current_time = time.time()
            if stream_counter % 100 == 0:
                time_since_last = current_time - last_activity_time
                last_activity_time = current_time

                logger.bind(session_id=session_id).info(
                    f"📊 流处理状态 - 计数: {stream_counter}, 间隔: {time_since_last:.3f}s"
                )

            token_usage_payload = _extract_token_usage_payload(result) or token_usage_payload

            yield_result = result.copy()
            yield_result.pop("message_type", None)
            yield_result.pop("is_final", None)
            yield_result.pop("is_chunk", None)
            yield_result.pop("chunk_id", None)
            yield json.dumps(yield_result, ensure_ascii=False) + "\n"

        token_usage_persisted = await _persist_token_usage_if_available(
            stream_service,
            token_usage_payload=token_usage_payload,
        )

        yield json.dumps(
            {
                "type": "stream_end",
                "session_id": session_id,
                "timestamp": time.time(),
                "total_stream_count": stream_counter,
            },
            ensure_ascii=False,
        ) + "\n"
    finally:
        if not token_usage_persisted:
            await _persist_token_usage_if_available(
                stream_service,
                token_usage_payload=token_usage_payload,
            )
        await _finalize_session_end(request, original_skills)


async def _finalize_session_end(
    request: StreamRequest,
    original_skills: List[str],
) -> None:
    from common.services.conversation_service import (
        persist_session_state_with_cancel_protection,
    )

    await persist_session_state_with_cancel_protection(request.session_id)

    if not _is_desktop_mode() and request.available_skills and request.agent_id:
        asyncio.create_task(_check_and_update_agent_skills(request, original_skills))


def _extract_token_usage_payload(result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(result, dict):
        return None
    message_type = result.get("message_type") or result.get("type")
    if message_type != "token_usage":
        return None
    metadata = result.get("metadata") or {}
    token_usage = metadata.get("token_usage")
    return token_usage if isinstance(token_usage, dict) else None


async def _persist_token_usage_if_available(
    stream_service: SageStreamService,
    *,
    token_usage_payload: Optional[Dict[str, Any]] = None,
) -> bool:
    request = getattr(stream_service, "request", None)
    if not request:
        return False

    try:
        if token_usage_payload:
            return await token_usage_service.record_execution_payload(
                token_usage=token_usage_payload,
                request_source=request.request_source or "",
                session_id=request.session_id or "",
                user_id=request.user_id,
                agent_id=request.agent_id,
                started_at=request.execution_started_at,
                finished_at=get_local_now(),
            )

        sage_engine = getattr(stream_service, "sage_engine", None)
        session_context = getattr(sage_engine, "session_context", None)
        if not session_context:
            return False

        return await token_usage_service.record_session_execution(
            session_context=session_context,
            request_source=request.request_source or "",
            session_id=request.session_id,
            user_id=request.user_id,
            agent_id=request.agent_id,
            started_at=request.execution_started_at,
            finished_at=get_local_now(),
        )
    except Exception as e:
        logger.bind(session_id=request.session_id or "").error(f"token_usage 落库失败: {e}")
        return False


def _load_agent_workspace_skill_names_sync(agent_skills_path: str) -> set[str]:
    actual_skills: set[str] = set()
    if os.path.exists(agent_skills_path) and os.path.isdir(agent_skills_path):
        try:
            from sagents.skill.skill_manager import SkillManager

            tm = SkillManager(skill_dirs=[agent_skills_path], isolated=True)
            for skill in tm.list_skill_info():
                actual_skills.add(skill.name)
        except Exception as e:
            logger.warning(f"加载Agent工作空间技能失败: {e}")
    return actual_skills


async def _check_and_update_agent_skills(
    request: StreamRequest,
    original_skills: List[str],
) -> None:
    try:
        cfg = _get_cfg()
        agent_skills_path = str(
            get_agent_skill_dir(
                request.agent_id,
                user_id=request.user_id or "default_user",
                app_mode=cfg.app_mode,
                ensure_exists=False,
            )
        )

        actual_skills = await asyncio.to_thread(
            _load_agent_workspace_skill_names_sync,
            agent_skills_path,
        )

        added_in_session = actual_skills - set(original_skills or [])
        if not added_in_session:
            return

        agent_dao = AgentConfigDao()
        agent = await agent_dao.get_by_id(request.agent_id)
        if agent and agent.config:
            current_skills = set(agent.config.get("availableSkills") or [])
            updated_skills = current_skills | added_in_session
            agent.config["availableSkills"] = list(updated_skills)
            await agent_dao.save(agent)
            logger.bind(session_id=request.session_id, agent_id=request.agent_id).info(
                f"Agent技能列表已更新: 新增={added_in_session}, 最终={updated_skills}"
            )
    except Exception as e:
        logger.bind(session_id=request.session_id).error(
            f"检查并更新Agent技能失败: {e}"
        )


async def _ensure_conversation(request: StreamRequest) -> None:
    conversation_dao = ConversationDao()
    existing_conversation = await conversation_dao.get_by_session_id(request.session_id)
    if existing_conversation:
        return

    await conversation_dao.save_conversation(
        user_id=request.user_id or "default_user",
        session_id=request.session_id,
        agent_id=request.agent_id or "default_agent",
        agent_name=request.agent_name or "Sage Assistant",
        title=await create_conversation_title(request),
        messages=[],
    )


def _extract_text_from_content(content: Any) -> str:
    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(str(item.get("text", "")))
        return " ".join(part for part in text_parts if part).strip()
    return str(content or "").strip()


def _sanitize_title_text(text: str) -> str:
    cleaned = str(text or "")
    cleaned = re.sub(
        r"^\s*(?:<enable_plan>\s*(?:true|false)\s*</enable_plan>\s*|<enable_deep_thinking>\s*(?:true|false)\s*</enable_deep_thinking>\s*)+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"^\s*(?:<skill>.*?</skill>\s*)+",
        "",
        cleaned,
        flags=re.IGNORECASE | re.DOTALL,
    )
    cleaned = re.sub(
        r"<(?:skills|active_skills|available_skills)>[\s\S]*?</(?:skills|active_skills|available_skills)>",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"</?[\w:-]+(?:\s[^>]*)?>", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


async def create_conversation_title(request: StreamRequest) -> str:
    if not request.messages:
        return "新会话"

    if _is_desktop_mode():
        title_source = ""
        for message in request.messages:
            if getattr(message, "role", "") != "user":
                continue
            candidate = _sanitize_title_text(
                _extract_text_from_content(getattr(message, "content", ""))
            )
            if candidate:
                title_source = candidate
                break

        if not title_source:
            title_source = _sanitize_title_text(
                _extract_text_from_content(getattr(request.messages[0], "content", ""))
            )
    else:
        title_source = _sanitize_title_text(
            _extract_text_from_content(request.messages[0].content)
        ) or "新会话"

    if not title_source:
        return "新会话"
    return title_source[:50] + "..." if len(title_source) > 50 else title_source

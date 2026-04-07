import importlib
import json
import logging
import os
import pkgutil
import sys
from contextlib import asynccontextmanager
from importlib.util import find_spec
from typing import Any, AsyncGenerator, Dict, List, Optional

from dotenv import load_dotenv

from common.core import config
from common.schemas.chat import Message, StreamRequest


DEFAULT_CLI_USER_ID = (
    os.environ.get("SAGE_CLI_USER_ID")
    or os.environ.get("SAGE_DESKTOP_USER_ID")
    or "default_user"
)


def get_default_cli_user_id() -> str:
    return DEFAULT_CLI_USER_ID


def _dependency_status() -> Dict[str, bool]:
    return {
        "dotenv": find_spec("dotenv") is not None,
        "loguru": find_spec("loguru") is not None,
        "fastapi": find_spec("fastapi") is not None,
        "uvicorn": find_spec("uvicorn") is not None,
    }


def _collect_runtime_issues(cfg: config.StartupConfig) -> Dict[str, List[str]]:
    errors: List[str] = []
    warnings: List[str] = []
    next_steps: List[str] = []

    deps = _dependency_status()
    missing_deps = [name for name, present in deps.items() if not present]
    if missing_deps:
        errors.append(f"Missing Python dependencies: {', '.join(missing_deps)}")
        next_steps.append("Install project dependencies first, for example: pip install -e .")

    if not (cfg.default_llm_api_key or "").strip():
        errors.append("Missing SAGE_DEFAULT_LLM_API_KEY")
        next_steps.append("Set SAGE_DEFAULT_LLM_API_KEY in your shell or .env before using run/chat.")

    if not (cfg.default_llm_api_base_url or "").strip():
        errors.append("Missing SAGE_DEFAULT_LLM_API_BASE_URL")
        next_steps.append("Set SAGE_DEFAULT_LLM_API_BASE_URL in your shell or .env.")

    if not (cfg.default_llm_model_name or "").strip():
        errors.append("Missing SAGE_DEFAULT_LLM_MODEL_NAME")
        next_steps.append("Set SAGE_DEFAULT_LLM_MODEL_NAME in your shell or .env.")

    if cfg.db_type == "mysql":
        warnings.append("CLI is using MySQL. For local development, file DB is usually simpler.")
        next_steps.append("If you only need local development, consider setting SAGE_DB_TYPE=file.")

    if cfg.auth_mode != "native":
        warnings.append(f"Current auth mode is {cfg.auth_mode}. CLI currently works best with native/local setups.")

    return {
        "errors": errors,
        "warnings": warnings,
        "next_steps": next_steps,
    }


def init_cli_config(*, init_logging: bool = True) -> config.StartupConfig:
    load_dotenv(".env")
    cfg = config.init_startup_config(mode="server")
    if init_logging:
        from common.utils.logging import init_logging_base

        init_logging_base(
            log_name="sage-cli",
            log_level=getattr(cfg, "log_level", "INFO"),
            log_path="./logs",
            use_safe_stdout=True,
        )
    return cfg


def configure_cli_logging(*, verbose: bool) -> config.StartupConfig:
    cfg = init_cli_config(init_logging=True)
    if verbose:
        return cfg

    quiet_level = logging.ERROR
    logging.getLogger().setLevel(quiet_level)
    logging.getLogger("TaskScheduler").setLevel(quiet_level)

    try:
        task_logger = logging.getLogger("TaskScheduler")
        for handler in task_logger.handlers:
            handler.setLevel(quiet_level)
    except Exception:
        pass

    try:
        from loguru import logger as loguru_logger

        loguru_logger.remove()
        loguru_logger.add(sys.stderr, level="ERROR", format="{message}")
    except Exception:
        pass

    try:
        from sagents.utils.logger import logger as sage_logger

        for handler in sage_logger.logger.handlers:
            if isinstance(handler, logging.StreamHandler):
                handler.setLevel(quiet_level)
    except Exception:
        pass

    return cfg


def _import_shared_model_modules() -> None:
    import common.models

    for module_info in pkgutil.iter_modules(common.models.__path__):
        name = module_info.name
        if name.startswith("_") or name == "base":
            continue
        importlib.import_module(f"common.models.{name}")


@asynccontextmanager
async def cli_runtime(*, verbose: bool = False) -> AsyncGenerator[config.StartupConfig, None]:
    from app.server.bootstrap import (
        close_db_client,
        close_skill_manager,
        close_tool_manager,
        initialize_db_connection,
        initialize_session_manager,
        initialize_skill_manager,
        initialize_tool_manager,
    )
    from sagents.tool.tool_manager import ToolManager

    cfg = configure_cli_logging(verbose=verbose)
    _import_shared_model_modules()

    original_discover_builtin = ToolManager.discover_builtin_mcp_tools_from_path

    def _skip_builtin_mcp_discovery(_self):
        return None

    ToolManager.discover_builtin_mcp_tools_from_path = _skip_builtin_mcp_discovery
    await initialize_db_connection(cfg)
    try:
        await initialize_tool_manager()
        await initialize_skill_manager(cfg)
        await initialize_session_manager(cfg)
        yield cfg
    finally:
        ToolManager.discover_builtin_mcp_tools_from_path = original_discover_builtin
        try:
            await close_skill_manager()
        finally:
            try:
                await close_tool_manager()
            finally:
                await close_db_client()


def build_run_request(
    *,
    task: str,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    agent_mode: Optional[str] = None,
) -> StreamRequest:
    return StreamRequest(
        messages=[Message(role="user", content=task)],
        session_id=session_id,
        user_id=user_id or get_default_cli_user_id(),
        agent_id=agent_id,
        agent_mode=agent_mode,
    )


async def run_request_stream(
    request: StreamRequest,
    workspace: Optional[str] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    from common.services.chat_service import (
        _copy_sage_usage_docs_to_workspace,
        execute_chat_session,
        populate_request_from_agent_config,
        prepare_session,
    )
    from common.services.chat_utils import create_skill_proxy

    await populate_request_from_agent_config(request, require_agent_id=False)
    stream_service, _lock = await prepare_session(request)
    if workspace:
        workspace_path = os.path.abspath(workspace)
        os.makedirs(workspace_path, exist_ok=True)
        stream_service.agent_workspace = workspace_path
        stream_service.skill_manager, stream_service.agent_skill_manager = create_skill_proxy(
            request.available_skills,
            user_id=request.user_id,
            agent_workspace=workspace_path,
        )
        if request.system_context is None:
            request.system_context = {}
        request.system_context["当前CLI工作目录"] = workspace_path
        _copy_sage_usage_docs_to_workspace(workspace_path)
    async for line in execute_chat_session(stream_service):
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def collect_doctor_info() -> Dict[str, Any]:
    cfg = init_cli_config(init_logging=False)
    dependency_status = _dependency_status()
    issues = _collect_runtime_issues(cfg)
    status = "ok"
    if issues["errors"]:
        status = "error"
    elif issues["warnings"]:
        status = "warning"

    return {
        "status": status,
        "python": os.environ.get("PYTHON_BIN") or os.environ.get("CONDA_PYTHON_EXE") or "python",
        "cwd": os.getcwd(),
        "cwd_writable": os.access(os.getcwd(), os.W_OK),
        "env_file": os.path.abspath(".env"),
        "env_file_exists": os.path.exists(os.path.abspath(".env")),
        "app_mode": cfg.app_mode,
        "auth_mode": cfg.auth_mode,
        "port": cfg.port,
        "db_type": cfg.db_type,
        "default_cli_user_id": get_default_cli_user_id(),
        "default_llm_model_name": cfg.default_llm_model_name,
        "agents_dir": cfg.agents_dir,
        "agents_dir_exists": os.path.exists(cfg.agents_dir),
        "session_dir": cfg.session_dir,
        "session_dir_exists": os.path.exists(cfg.session_dir),
        "logs_dir": cfg.logs_dir,
        "logs_dir_exists": os.path.exists(cfg.logs_dir),
        "dependencies": dependency_status,
        **issues,
    }


def collect_config_info() -> Dict[str, Any]:
    cfg = init_cli_config(init_logging=False)
    return {
        "env_file": os.path.abspath(".env"),
        "default_cli_user_id": get_default_cli_user_id(),
        "app_mode": cfg.app_mode,
        "auth_mode": cfg.auth_mode,
        "port": cfg.port,
        "db_type": cfg.db_type,
        "default_llm_api_base_url": cfg.default_llm_api_base_url,
        "default_llm_model_name": cfg.default_llm_model_name,
        "agents_dir": cfg.agents_dir,
        "session_dir": cfg.session_dir,
        "logs_dir": cfg.logs_dir,
        "env_sources": {
            "SAGE_CLI_USER_ID": os.environ.get("SAGE_CLI_USER_ID"),
            "SAGE_DESKTOP_USER_ID": os.environ.get("SAGE_DESKTOP_USER_ID"),
            "SAGE_DEFAULT_LLM_API_KEY": "(set)" if os.environ.get("SAGE_DEFAULT_LLM_API_KEY") else None,
            "SAGE_DEFAULT_LLM_API_BASE_URL": os.environ.get("SAGE_DEFAULT_LLM_API_BASE_URL"),
            "SAGE_DEFAULT_LLM_MODEL_NAME": os.environ.get("SAGE_DEFAULT_LLM_MODEL_NAME"),
            "SAGE_DB_TYPE": os.environ.get("SAGE_DB_TYPE"),
        },
    }


def _normalize_env_value(value: Optional[str], fallback: str) -> str:
    normalized = (value or "").strip()
    return normalized or fallback


def build_minimal_cli_env_template() -> str:
    cfg = init_cli_config(init_logging=False)
    api_base_url = _normalize_env_value(
        os.environ.get("SAGE_DEFAULT_LLM_API_BASE_URL"),
        cfg.default_llm_api_base_url or "https://api.deepseek.com/v1",
    )
    model_name = _normalize_env_value(
        os.environ.get("SAGE_DEFAULT_LLM_MODEL_NAME"),
        cfg.default_llm_model_name or "deepseek-chat",
    )
    api_key = (os.environ.get("SAGE_DEFAULT_LLM_API_KEY") or "").strip()

    lines = [
        "# Generated by `sage config init`",
        "SAGE_ENV=development",
        "SAGE_AUTH_MODE=native",
        "SAGE_DB_TYPE=file",
        "SAGE_DEFAULT_LLM_API_KEY=" + api_key,
        "SAGE_DEFAULT_LLM_API_BASE_URL=" + api_base_url,
        "SAGE_DEFAULT_LLM_MODEL_NAME=" + model_name,
        "",
    ]
    return "\n".join(lines)


def write_cli_config_file(*, path: str = ".env", force: bool = False) -> Dict[str, Any]:
    output_path = os.path.abspath(path)
    existed_before = os.path.exists(output_path)
    if existed_before and not force:
        raise RuntimeError(
            f"Config file already exists: {output_path}\n"
            "Use `sage config init --force` to overwrite it."
        )

    content = build_minimal_cli_env_template()
    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write(content)

    return {
        "path": output_path,
        "overwritten": existed_before,
        "template": "minimal-local",
        "next_steps": [
            "Set SAGE_DEFAULT_LLM_API_KEY if it is still empty.",
            "Run `sage doctor` to verify the generated config.",
        ],
    }


@asynccontextmanager
async def cli_db_runtime(*, verbose: bool = False) -> AsyncGenerator[config.StartupConfig, None]:
    from app.server.bootstrap import close_db_client, initialize_db_connection

    cfg = configure_cli_logging(verbose=verbose)
    _import_shared_model_modules()
    await initialize_db_connection(cfg)
    try:
        yield cfg
    finally:
        await close_db_client()


async def list_sessions(
    *,
    user_id: Optional[str] = None,
    limit: int = 20,
    search: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> Dict[str, Any]:
    from common.models.conversation import ConversationDao
    from common.schemas.conversation import ConversationInfo

    resolved_user_id = user_id or get_default_cli_user_id()
    dao = ConversationDao()
    conversations, total_count = await dao.get_conversations_paginated(
        page=1,
        page_size=limit,
        user_id=resolved_user_id,
        search=search,
        agent_id=agent_id,
        sort_by="date",
    )

    items: List[Dict[str, Any]] = []
    for conv in conversations:
        message_count = conv.get_message_count()
        items.append(
            ConversationInfo(
                session_id=conv.session_id,
                user_id=conv.user_id,
                agent_id=conv.agent_id,
                agent_name=conv.agent_name,
                title=conv.title,
                message_count=message_count.get("user_count", 0) + message_count.get("agent_count", 0),
                user_count=message_count.get("user_count", 0),
                agent_count=message_count.get("agent_count", 0),
                created_at=conv.created_at.isoformat() if conv.created_at else "",
                updated_at=conv.updated_at.isoformat() if conv.updated_at else "",
            ).model_dump()
        )

    return {
        "user_id": resolved_user_id,
        "limit": limit,
        "total": total_count,
        "list": items,
    }


async def get_session_summary(
    *,
    session_id: str,
    user_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    from common.models.conversation import ConversationDao

    dao = ConversationDao()
    conversation = await dao.get_by_session_id(session_id)
    if not conversation:
        return None

    if user_id and conversation.user_id and conversation.user_id != user_id:
        return None

    counts = conversation.get_message_count()
    return {
        "session_id": conversation.session_id,
        "user_id": conversation.user_id,
        "agent_id": conversation.agent_id,
        "agent_name": conversation.agent_name,
        "title": conversation.title,
        "message_count": counts.get("user_count", 0) + counts.get("agent_count", 0),
        "user_count": counts.get("user_count", 0),
        "agent_count": counts.get("agent_count", 0),
        "created_at": conversation.created_at.isoformat() if conversation.created_at else "",
        "updated_at": conversation.updated_at.isoformat() if conversation.updated_at else "",
    }


def validate_cli_runtime_requirements() -> config.StartupConfig:
    cfg = init_cli_config(init_logging=False)
    issues = _collect_runtime_issues(cfg)
    if issues["errors"]:
        detail = "\n".join(f"- {item}" for item in issues["errors"])
        next_steps = "\n".join(f"- {item}" for item in issues["next_steps"])
        raise RuntimeError(
            "CLI runtime is not ready:\n"
            f"{detail}\n"
            "Suggested next steps:\n"
            f"{next_steps}"
        )
    return cfg

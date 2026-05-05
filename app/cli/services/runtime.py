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

from app.cli.services.base import CLIError
from common.core import config
from common.schemas.chat import Message, StreamRequest
from common.services.llm_provider_probe_utils import friendly_provider_probe_error


def _load_cli_env_defaults() -> Dict[str, str]:
    local_defaults = config.get_local_storage_defaults()
    load_dotenv(local_defaults["env_file"], override=False)
    load_dotenv(".env", override=True)
    return local_defaults


def get_default_cli_user_id() -> str:
    _load_cli_env_defaults()
    return (
        os.environ.get("SAGE_CLI_USER_ID")
        or os.environ.get("SAGE_DESKTOP_USER_ID")
        or "default_user"
    )


def get_default_cli_max_loop_count() -> int:
    _load_cli_env_defaults()
    raw_value = (os.environ.get("SAGE_CLI_MAX_LOOP_COUNT") or "").strip()
    if not raw_value:
        return 50
    try:
        value = int(raw_value)
    except ValueError:
        return 50
    return value if value > 0 else 50


def dependency_status() -> Dict[str, bool]:
    return {
        "dotenv": find_spec("dotenv") is not None,
        "loguru": find_spec("loguru") is not None,
        "fastapi": find_spec("fastapi") is not None,
        "uvicorn": find_spec("uvicorn") is not None,
    }


def collect_runtime_issues(cfg: config.StartupConfig) -> Dict[str, List[str]]:
    errors: List[str] = []
    warnings: List[str] = []
    next_steps: List[str] = []

    deps = dependency_status()
    missing_deps = [name for name, present in deps.items() if not present]
    if missing_deps:
        errors.append(f"Missing Python dependencies: {', '.join(missing_deps)}")
        next_steps.append("Install project dependencies first, for example: pip install -r requirements.txt")
        next_steps.append("If only rank_bm25 is missing, install it directly with: pip install rank-bm25")

    if not (cfg.default_llm_api_key or "").strip():
        errors.append("Missing SAGE_DEFAULT_LLM_API_KEY")
        next_steps.append("Set SAGE_DEFAULT_LLM_API_KEY in your shell, ~/.sage/.sage_env, or local .env before using run/chat.")

    if not (cfg.default_llm_api_base_url or "").strip():
        errors.append("Missing SAGE_DEFAULT_LLM_API_BASE_URL")
        next_steps.append("Set SAGE_DEFAULT_LLM_API_BASE_URL in your shell, ~/.sage/.sage_env, or local .env.")

    if not (cfg.default_llm_model_name or "").strip():
        errors.append("Missing SAGE_DEFAULT_LLM_MODEL_NAME")
        next_steps.append("Set SAGE_DEFAULT_LLM_MODEL_NAME in your shell, ~/.sage/.sage_env, or local .env.")

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
    local_defaults = _load_cli_env_defaults()

    env_defaults = {
        config.ENV.LOGS_DIR: local_defaults["logs_dir"],
        config.ENV.SESSION_DIR: local_defaults["session_dir"],
        config.ENV.AGENTS_DIR: local_defaults["agents_dir"],
        config.ENV.SKILL_DIR: local_defaults["skill_dir"],
        config.ENV.USER_DIR: local_defaults["user_dir"],
        config.ENV.DB_FILE: local_defaults["db_file"],
    }
    for env_name, default_value in env_defaults.items():
        os.environ.setdefault(env_name, default_value)

    cfg = config.init_startup_config(mode="server")
    if init_logging:
        from common.utils.logging import init_logging_base

        init_logging_base(
            log_name="sage-cli",
            log_level=getattr(cfg, "log_level", "INFO"),
            log_path=cfg.logs_dir,
            use_safe_stdout=True,
        )
    return cfg


def configure_cli_logging(*, verbose: bool) -> config.StartupConfig:
    cfg = init_cli_config(init_logging=True)
    if verbose:
        return cfg

    quiet_level = logging.ERROR
    sage_stream_level = logging.WARNING
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
                handler.setLevel(sage_stream_level)
                try:
                    if getattr(handler, "stream", None) is sys.stdout:
                        handler.setStream(sys.stderr)
                except Exception:
                    pass
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


def build_run_request(
    *,
    task: str,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    agent_mode: Optional[str] = None,
    available_skills: Optional[List[str]] = None,
    max_loop_count: Optional[int] = None,
    goal: Optional[Dict[str, Any]] = None,
) -> StreamRequest:
    return StreamRequest(
        messages=[Message(role="user", content=task)],
        session_id=session_id,
        user_id=user_id or get_default_cli_user_id(),
        agent_id=agent_id,
        agent_mode=agent_mode,
        available_skills=available_skills,
        max_loop_count=max_loop_count,
        goal=goal,
    )


def validate_cli_request_options(
    *,
    workspace: Optional[str] = None,
    max_loop_count: Optional[int] = None,
) -> Optional[str]:
    if max_loop_count is None or int(max_loop_count) < 1:
        raise CLIError(
            "Invalid max loop count",
            next_steps=["Pass `--max-loop-count` with a positive integer value."],
            debug_detail=f"max_loop_count={max_loop_count!r}",
        )

    if not workspace:
        return None

    workspace_path = os.path.abspath(workspace)
    if os.path.exists(workspace_path) and not os.path.isdir(workspace_path):
        raise CLIError(
            f"Workspace path is not a directory: {workspace_path}",
            next_steps=["Choose a directory path for `--workspace`, or remove the conflicting file."],
        )

    parent_dir = workspace_path if os.path.isdir(workspace_path) else os.path.dirname(workspace_path) or os.getcwd()
    if not os.path.exists(parent_dir):
        raise CLIError(
            f"Workspace parent directory does not exist: {parent_dir}",
            next_steps=["Create the parent directory first, or choose a different `--workspace` path."],
        )

    if not os.access(parent_dir, os.W_OK):
        raise CLIError(
            f"Workspace path is not writable: {parent_dir}",
            next_steps=["Choose a writable `--workspace` path, or update directory permissions."],
        )

    return workspace_path


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


def validate_cli_runtime_requirements() -> config.StartupConfig:
    cfg = init_cli_config(init_logging=False)
    issues = collect_runtime_issues(cfg)
    if issues["errors"]:
        detail = "\n".join(f"- {item}" for item in issues["errors"])
        raise CLIError(
            "CLI runtime is not ready:\n"
            f"{detail}",
            next_steps=issues["next_steps"],
        )
    return cfg


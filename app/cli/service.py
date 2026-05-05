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
from common.services.llm_provider_probe_utils import friendly_provider_probe_error


class CLIError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        next_steps: Optional[List[str]] = None,
        debug_detail: Optional[str] = None,
        exit_code: int = 1,
    ) -> None:
        super().__init__(message)
        self.next_steps = list(next_steps or [])
        self.debug_detail = debug_detail
        self.exit_code = exit_code


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


def _safe_runtime_choice_diagnostic(
    *,
    resolve_fn,
    available_fn,
    env_name: str,
    label: str,
) -> Dict[str, Any]:
    available = list(available_fn())
    env_value = os.environ.get(env_name)
    try:
        resolved = resolve_fn()
        if resolved not in available:
            raise ValueError(
                f"Unsupported {label}: {resolved}. Supported values: {', '.join(available)}"
            )
        return {
            "status": "ok",
            "resolved": resolved,
            "available": available,
            "env": env_value,
            "error": None,
        }
    except Exception as exc:
        return {
            "status": "error",
            "resolved": None,
            "available": available,
            "env": env_value,
            "error": str(exc),
        }


def _collect_memory_runtime_diagnostics() -> Dict[str, Any]:
    from sagents.context.session_memory import (
        available_session_memory_backend_names,
        available_session_memory_strategy_names,
        resolve_session_memory_backend_name,
        resolve_session_memory_strategy,
    )
    from sagents.tool.impl.file_memory import (
        available_file_memory_backend_names,
        resolve_file_memory_backend_name,
    )

    memory_backends = {
        "session_history": _safe_runtime_choice_diagnostic(
            resolve_fn=resolve_session_memory_backend_name,
            available_fn=available_session_memory_backend_names,
            env_name="SAGE_SESSION_MEMORY_BACKEND",
            label="session memory backend",
        ),
        "file_memory": _safe_runtime_choice_diagnostic(
            resolve_fn=resolve_file_memory_backend_name,
            available_fn=available_file_memory_backend_names,
            env_name="SAGE_FILE_MEMORY_BACKEND",
            label="file memory backend",
        ),
    }
    memory_strategies = {
        "session_history": _safe_runtime_choice_diagnostic(
            resolve_fn=resolve_session_memory_strategy,
            available_fn=available_session_memory_strategy_names,
            env_name="SAGE_SESSION_MEMORY_STRATEGY",
            label="session memory strategy",
        ),
    }

    issues: List[str] = []
    for group_name, group_items in (
        ("memory_backends", memory_backends),
        ("memory_strategies", memory_strategies),
    ):
        for item_name, item in group_items.items():
            if item["status"] == "error":
                issues.append(f"Invalid {group_name}.{item_name}: {item['error']}")

    return {
        "memory_backends": memory_backends,
        "memory_strategies": memory_strategies,
        "issues": issues,
    }


def collect_doctor_info() -> Dict[str, Any]:
    cfg = init_cli_config(init_logging=False)
    local_defaults = config.get_local_storage_defaults()
    shared_env_file = local_defaults["env_file"]
    project_env_file = os.path.abspath(".env")
    effective_env_file = shared_env_file if os.path.exists(shared_env_file) else project_env_file
    env_files = [shared_env_file]
    if os.path.exists(project_env_file):
        env_files.append(project_env_file)
    session_registry_db = os.path.join(cfg.session_dir, "sessions_index.sqlite")
    dependency_status = _dependency_status()
    issues = _collect_runtime_issues(cfg)
    memory_diagnostics = _collect_memory_runtime_diagnostics()
    issues["errors"].extend(memory_diagnostics["issues"])
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
        "env_file": effective_env_file,
        "env_files": env_files,
        "env_file_exists": os.path.exists(shared_env_file) or os.path.exists(project_env_file),
        "app_mode": cfg.app_mode,
        "auth_mode": cfg.auth_mode,
        "port": cfg.port,
        "db_type": cfg.db_type,
        "default_cli_user_id": get_default_cli_user_id(),
        "default_cli_max_loop_count": get_default_cli_max_loop_count(),
        "default_llm_model_name": cfg.default_llm_model_name,
        "memory_backends": memory_diagnostics["memory_backends"],
        "memory_strategies": memory_diagnostics["memory_strategies"],
        "agents_dir": cfg.agents_dir,
        "agents_dir_exists": os.path.exists(cfg.agents_dir),
        "session_dir": cfg.session_dir,
        "session_dir_exists": os.path.exists(cfg.session_dir),
        "session_registry_db": session_registry_db,
        "session_registry_db_exists": os.path.exists(session_registry_db),
        "logs_dir": cfg.logs_dir,
        "logs_dir_exists": os.path.exists(cfg.logs_dir),
        "dependencies": dependency_status,
        **issues,
    }


async def probe_default_provider() -> Dict[str, Any]:
    from sagents.llm import probe_connection

    cfg = init_cli_config(init_logging=False)
    issues = _collect_runtime_issues(cfg)
    provider_errors = [
        item
        for item in issues["errors"]
        if item.startswith("Missing SAGE_DEFAULT_LLM_")
    ]
    if provider_errors:
        return {
            "status": "error",
            "message": "Default provider configuration is incomplete",
            "detail": "; ".join(provider_errors),
        }

    try:
        result = await probe_connection(
            cfg.default_llm_api_key,
            cfg.default_llm_api_base_url,
            cfg.default_llm_model_name,
        )
        return {
            "status": "ok" if result.get("supported") else "error",
            "message": "Default provider probe succeeded" if result.get("supported") else "Default provider probe failed",
            "response": result.get("response"),
        }
    except Exception as exc:
        return {
            "status": "error",
            "message": friendly_provider_probe_error(exc, subject="Default provider"),
            "detail": str(exc),
        }


def collect_config_info() -> Dict[str, Any]:
    cfg = init_cli_config(init_logging=False)
    local_defaults = config.get_local_storage_defaults()
    shared_env_file = local_defaults["env_file"]
    project_env_file = os.path.abspath(".env")
    effective_env_file = shared_env_file if os.path.exists(shared_env_file) else project_env_file
    env_files = [shared_env_file]
    if os.path.exists(project_env_file):
        env_files.append(project_env_file)
    session_registry_db = os.path.join(cfg.session_dir, "sessions_index.sqlite")
    memory_diagnostics = _collect_memory_runtime_diagnostics()
    return {
        "env_file": effective_env_file,
        "env_files": env_files,
        "default_cli_user_id": get_default_cli_user_id(),
        "default_cli_max_loop_count": get_default_cli_max_loop_count(),
        "app_mode": cfg.app_mode,
        "auth_mode": cfg.auth_mode,
        "port": cfg.port,
        "db_type": cfg.db_type,
        "default_llm_api_base_url": cfg.default_llm_api_base_url,
        "default_llm_model_name": cfg.default_llm_model_name,
        "memory_backends": memory_diagnostics["memory_backends"],
        "memory_strategies": memory_diagnostics["memory_strategies"],
        "agents_dir": cfg.agents_dir,
        "session_dir": cfg.session_dir,
        "session_registry_db": session_registry_db,
        "logs_dir": cfg.logs_dir,
        "env_sources": {
            "SAGE_HOME": local_defaults["sage_home"],
            "SAGE_ENV_FILE": shared_env_file,
            "SAGE_CLI_USER_ID": os.environ.get("SAGE_CLI_USER_ID"),
            "SAGE_CLI_MAX_LOOP_COUNT": os.environ.get("SAGE_CLI_MAX_LOOP_COUNT"),
            "SAGE_DESKTOP_USER_ID": os.environ.get("SAGE_DESKTOP_USER_ID"),
            "SAGE_DEFAULT_LLM_API_KEY": "(set)" if os.environ.get("SAGE_DEFAULT_LLM_API_KEY") else None,
            "SAGE_DEFAULT_LLM_API_BASE_URL": os.environ.get("SAGE_DEFAULT_LLM_API_BASE_URL"),
            "SAGE_DEFAULT_LLM_MODEL_NAME": os.environ.get("SAGE_DEFAULT_LLM_MODEL_NAME"),
            "SAGE_DB_TYPE": os.environ.get("SAGE_DB_TYPE"),
            "SAGE_SESSION_MEMORY_BACKEND": os.environ.get("SAGE_SESSION_MEMORY_BACKEND"),
            "SAGE_FILE_MEMORY_BACKEND": os.environ.get("SAGE_FILE_MEMORY_BACKEND"),
            "SAGE_SESSION_MEMORY_STRATEGY": os.environ.get("SAGE_SESSION_MEMORY_STRATEGY"),
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
        "# Optional memory-search overrides",
        "# SAGE_SESSION_MEMORY_BACKEND=bm25",
        "# SAGE_FILE_MEMORY_BACKEND=scoped_index",
        "# SAGE_SESSION_MEMORY_STRATEGY=messages",
        "",
    ]
    return "\n".join(lines)


def write_cli_config_file(*, path: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    output_target = path or config.get_local_storage_defaults()["env_file"]
    os.makedirs(os.path.dirname(os.path.abspath(output_target)), exist_ok=True)
    output_path = os.path.abspath(output_target)
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


def _trim_optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _mask_api_key(value: Optional[str]) -> Optional[str]:
    normalized = _trim_optional_text(value)
    if not normalized:
        return None
    if len(normalized) <= 8:
        return "*" * len(normalized)
    return f"{normalized[:4]}...{normalized[-4:]}"


def _sanitize_provider_record(record: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = dict(record)
    raw_api_keys = sanitized.get("api_keys") or []
    masked_api_keys = [_mask_api_key(item) for item in raw_api_keys if _mask_api_key(item)]
    sanitized["api_keys"] = masked_api_keys
    sanitized["api_key_preview"] = masked_api_keys[0] if masked_api_keys else None
    return sanitized


def _resolve_provider_create_data(
    *,
    name: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    presence_penalty: Optional[float] = None,
    max_model_len: Optional[int] = None,
    supports_multimodal: Optional[bool] = None,
    supports_structured_output: Optional[bool] = None,
    is_default: Optional[bool] = None,
) -> Dict[str, Any]:
    from common.schemas.base import LLMProviderCreate

    cfg = init_cli_config(init_logging=False)
    resolved_base_url = _trim_optional_text(base_url) or _trim_optional_text(cfg.default_llm_api_base_url)
    resolved_api_key = _trim_optional_text(api_key) or _trim_optional_text(cfg.default_llm_api_key)
    resolved_model = _trim_optional_text(model) or _trim_optional_text(cfg.default_llm_model_name)

    next_steps: List[str] = []
    if not resolved_api_key:
        next_steps.append("Pass `--api-key`, or set `SAGE_DEFAULT_LLM_API_KEY` in `~/.sage/.sage_env` or local `.env`.")
    if not resolved_base_url:
        next_steps.append("Pass `--base-url`, or set `SAGE_DEFAULT_LLM_API_BASE_URL` in `~/.sage/.sage_env` or local `.env`.")
    if not resolved_model:
        next_steps.append("Pass `--model`, or set `SAGE_DEFAULT_LLM_MODEL_NAME` in `~/.sage/.sage_env` or local `.env`.")
    if next_steps:
        raise CLIError(
            "Provider configuration is incomplete for create/verify.",
            next_steps=next_steps,
        )

    return {
        "data": LLMProviderCreate(
            name=_trim_optional_text(name),
            base_url=resolved_base_url,
            api_keys=[resolved_api_key],
            model=resolved_model,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            presence_penalty=presence_penalty,
            max_model_len=max_model_len,
            supports_multimodal=bool(supports_multimodal),
            supports_structured_output=bool(supports_structured_output),
            is_default=bool(is_default),
        ),
        "sources": {
            "base_url": "arg" if _trim_optional_text(base_url) else "default",
            "api_key": "arg" if _trim_optional_text(api_key) else "default",
            "model": "arg" if _trim_optional_text(model) else "default",
        },
    }


def _build_provider_update_data(
    *,
    name: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    presence_penalty: Optional[float] = None,
    max_model_len: Optional[int] = None,
    supports_multimodal: Optional[bool] = None,
    supports_structured_output: Optional[bool] = None,
    is_default: Optional[bool] = None,
) -> Any:
    from common.schemas.base import LLMProviderUpdate

    payload: Dict[str, Any] = {}
    if name is not None:
        payload["name"] = _trim_optional_text(name)
    if base_url is not None:
        payload["base_url"] = _trim_optional_text(base_url)
    if api_key is not None:
        normalized_api_key = _trim_optional_text(api_key)
        if not normalized_api_key:
            raise CLIError(
                "Provider API key cannot be empty.",
                next_steps=["Pass a non-empty `--api-key` value."],
            )
        payload["api_keys"] = [normalized_api_key]
    if model is not None:
        payload["model"] = _trim_optional_text(model)
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if temperature is not None:
        payload["temperature"] = temperature
    if top_p is not None:
        payload["top_p"] = top_p
    if presence_penalty is not None:
        payload["presence_penalty"] = presence_penalty
    if max_model_len is not None:
        payload["max_model_len"] = max_model_len
    if supports_multimodal is not None:
        payload["supports_multimodal"] = supports_multimodal
    if supports_structured_output is not None:
        payload["supports_structured_output"] = supports_structured_output
    if is_default is not None:
        payload["is_default"] = is_default

    if not payload:
        raise CLIError(
            "No provider fields were supplied for update.",
            next_steps=[
                "Pass at least one field such as `--model`, `--base-url`, `--api-key`, or `--name`.",
            ],
        )

    return LLMProviderUpdate(**payload)


async def list_cli_providers(*, user_id: Optional[str] = None) -> Dict[str, Any]:
    from common.services import llm_provider_service

    resolved_user_id = user_id or get_default_cli_user_id()
    providers = await llm_provider_service.list_providers(resolved_user_id)
    sanitized = [_sanitize_provider_record(item) for item in providers]
    return {
        "user_id": resolved_user_id,
        "total": len(sanitized),
        "list": sanitized,
    }


async def query_cli_providers(
    *,
    user_id: Optional[str] = None,
    default_only: bool = False,
    model: Optional[str] = None,
    name_contains: Optional[str] = None,
) -> Dict[str, Any]:
    result = await list_cli_providers(user_id=user_id)
    providers = list(result.get("list") or [])

    normalized_model = _trim_optional_text(model)
    normalized_name_query = (_trim_optional_text(name_contains) or "").lower()

    if default_only:
        providers = [item for item in providers if bool(item.get("is_default"))]
    if normalized_model:
        providers = [item for item in providers if item.get("model") == normalized_model]
    if normalized_name_query:
        providers = [
            item
            for item in providers
            if normalized_name_query in ((item.get("name") or "").lower())
        ]

    return {
        **result,
        "filters": {
            "default_only": default_only,
            "model": normalized_model,
            "name_contains": _trim_optional_text(name_contains),
        },
        "total": len(providers),
        "list": providers,
    }


async def inspect_cli_provider(*, provider_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
    from common.models.llm_provider import LLMProviderDao

    resolved_user_id = user_id or get_default_cli_user_id()
    provider = await LLMProviderDao().get_by_id(provider_id)
    if not provider:
        raise CLIError(
            f"Provider not found: {provider_id}",
            next_steps=["Run `sage provider list` to inspect visible providers."],
        )
    if provider.user_id and provider.user_id != resolved_user_id:
        raise CLIError(
            f"Provider {provider_id} is not visible to user {resolved_user_id}",
            next_steps=[f"Run `sage provider list --user-id {resolved_user_id}` to inspect visible providers."],
        )
    return {
        "user_id": resolved_user_id,
        "provider_id": provider_id,
        "provider": _sanitize_provider_record(provider.to_dict()),
    }


async def verify_cli_provider(
    *,
    name: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    presence_penalty: Optional[float] = None,
    max_model_len: Optional[int] = None,
    supports_multimodal: Optional[bool] = None,
    supports_structured_output: Optional[bool] = None,
    is_default: Optional[bool] = None,
) -> Dict[str, Any]:
    from common.services import llm_provider_service

    resolved = _resolve_provider_create_data(
        name=name,
        base_url=base_url,
        api_key=api_key,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        presence_penalty=presence_penalty,
        max_model_len=max_model_len,
        supports_multimodal=supports_multimodal,
        supports_structured_output=supports_structured_output,
        is_default=is_default,
    )
    data = resolved["data"]
    try:
        await llm_provider_service.verify_provider(data)
    except Exception as exc:
        raise CLIError(
            friendly_provider_probe_error(exc, subject="Provider"),
            next_steps=[
                "Check `--api-key`, `--base-url`, and `--model`, then run `sage provider verify` again.",
            ],
        ) from exc
    return {
        "status": "ok",
        "message": "Provider verification succeeded",
        "sources": resolved["sources"],
        "provider": _sanitize_provider_record(data.model_dump()),
    }


async def create_cli_provider(
    *,
    user_id: Optional[str] = None,
    name: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    presence_penalty: Optional[float] = None,
    max_model_len: Optional[int] = None,
    supports_multimodal: Optional[bool] = None,
    supports_structured_output: Optional[bool] = None,
    is_default: Optional[bool] = None,
) -> Dict[str, Any]:
    from common.services import llm_provider_service

    resolved_user_id = user_id or get_default_cli_user_id()
    resolved = _resolve_provider_create_data(
        name=name,
        base_url=base_url,
        api_key=api_key,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        presence_penalty=presence_penalty,
        max_model_len=max_model_len,
        supports_multimodal=supports_multimodal,
        supports_structured_output=supports_structured_output,
        is_default=is_default,
    )
    provider_id = await llm_provider_service.create_provider(resolved["data"], user_id=resolved_user_id)
    providers = await llm_provider_service.list_providers(resolved_user_id)
    provider = next((item for item in providers if item.get("id") == provider_id), None)
    return {
        "status": "ok",
        "message": "Provider saved",
        "user_id": resolved_user_id,
        "provider_id": provider_id,
        "sources": resolved["sources"],
        "provider": _sanitize_provider_record(provider or resolved["data"].model_dump()),
    }


async def update_cli_provider(
    *,
    provider_id: str,
    user_id: Optional[str] = None,
    name: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    presence_penalty: Optional[float] = None,
    max_model_len: Optional[int] = None,
    supports_multimodal: Optional[bool] = None,
    supports_structured_output: Optional[bool] = None,
    is_default: Optional[bool] = None,
) -> Dict[str, Any]:
    from common.services import llm_provider_service

    resolved_user_id = user_id or get_default_cli_user_id()
    data = _build_provider_update_data(
        name=name,
        base_url=base_url,
        api_key=api_key,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        presence_penalty=presence_penalty,
        max_model_len=max_model_len,
        supports_multimodal=supports_multimodal,
        supports_structured_output=supports_structured_output,
        is_default=is_default,
    )
    provider = await llm_provider_service.update_provider(
        provider_id,
        data,
        user_id=resolved_user_id,
        allow_system_default_update=False,
    )
    return {
        "status": "ok",
        "message": "Provider updated",
        "user_id": resolved_user_id,
        "provider_id": provider_id,
        "provider": _sanitize_provider_record(provider.to_dict()),
    }


async def delete_cli_provider(*, provider_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
    from common.services import llm_provider_service

    resolved_user_id = user_id or get_default_cli_user_id()
    await llm_provider_service.delete_provider(provider_id, user_id=resolved_user_id)
    return {
        "status": "ok",
        "message": "Provider deleted",
        "user_id": resolved_user_id,
        "provider_id": provider_id,
        "deleted": True,
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

    def _normalize_messages(raw_messages: Any) -> List[Dict[str, Any]]:
        if isinstance(raw_messages, str):
            try:
                raw_messages = json.loads(raw_messages)
            except Exception:  # noqa: BLE001
                return []
        return raw_messages if isinstance(raw_messages, list) else []

    def _build_last_message_preview(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        for message in reversed(messages):
            role = (message or {}).get("role")
            content = ((message or {}).get("content") or "").strip()
            if role and content:
                return {
                    "role": role,
                    "content": content,
                    "type": (message or {}).get("type"),
                }
        return {}

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
        messages = _normalize_messages(conv.messages)
        last_message = _build_last_message_preview(messages)
        items.append(
            {
                **ConversationInfo(
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
                ).model_dump(),
                "last_message": last_message or None,
            }
        )

    return {
        "user_id": resolved_user_id,
        "limit": limit,
        "total": total_count,
        "list": items,
    }


def _resolve_agent_mode_from_config(agent_config: Dict[str, Any]) -> str:
    raw_value = str(
        agent_config.get("agentMode")
        or agent_config.get("agent_mode")
        or ""
    ).strip().lower()
    if raw_value in {"simple", "multi", "fibre"}:
        return raw_value
    return "simple"


async def list_cli_agents(
    *,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    from common.services.agent_service import list_agents

    resolved_user_id = user_id or get_default_cli_user_id()
    agents = await list_agents(user_id=resolved_user_id)
    items: List[Dict[str, Any]] = []
    for agent in agents:
        agent_config = agent.config if isinstance(agent.config, dict) else {}
        items.append(
            {
                "agent_id": agent.agent_id,
                "name": agent.name,
                "agent_mode": _resolve_agent_mode_from_config(agent_config),
                "is_default": bool(agent.is_default),
                "updated_at": agent.updated_at.isoformat() if agent.updated_at else "",
            }
        )

    items.sort(
        key=lambda item: (
            not bool(item.get("is_default")),
            item.get("name") or "",
            item.get("agent_id") or "",
        )
    )
    return {
        "user_id": resolved_user_id,
        "total": len(items),
        "list": items,
    }


async def list_available_skills(
    *,
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    workspace: Optional[str] = None,
) -> Dict[str, Any]:
    from sagents.skill.skill_manager import SkillManager

    cfg = init_cli_config(init_logging=False)
    resolved_user_id = user_id or get_default_cli_user_id()
    if agent_id:
        from common.services import skill_service

        agent_skills = await skill_service.get_agent_available_skills(
            agent_id=agent_id,
            current_user_id=resolved_user_id,
            role="admin" if resolved_user_id == "admin" else "user",
        )
        skills = []
        source_counts: Dict[str, int] = {}
        for item in agent_skills:
            source_name = item.get("source_dimension") or item.get("dimension") or "unknown"
            source_counts[source_name] = source_counts.get(source_name, 0) + 1
            skills.append(
                {
                    "name": item.get("name"),
                    "description": item.get("description"),
                    "source": source_name,
                    "path": item.get("path"),
                    "need_update": bool(item.get("need_update")),
                    "agent_id": agent_id,
                }
            )
        skills.sort(key=lambda item: item["name"] or "")
        return {
            "user_id": resolved_user_id,
            "agent_id": agent_id,
            "workspace": None,
            "sources": [],
            "total": len(skills),
            "source_counts": source_counts,
            "list": skills,
            "errors": [],
        }

    skill_sources: List[Dict[str, Any]] = []
    skills_map: Dict[str, Dict[str, Any]] = {}

    source_defs: List[tuple[str, Optional[str]]] = [
        ("system", cfg.skill_dir if os.path.isdir(cfg.skill_dir) else None),
        (
            "user",
            os.path.join(cfg.user_dir, resolved_user_id, "skills")
            if os.path.isdir(os.path.join(cfg.user_dir, resolved_user_id, "skills"))
            else None,
        ),
        (
            "workspace",
            os.path.join(os.path.abspath(workspace), "skills")
            if workspace and os.path.isdir(os.path.join(os.path.abspath(workspace), "skills"))
            else None,
        ),
    ]

    for source_name, source_path in source_defs:
        if not source_path:
            continue
        skill_sources.append({"source": source_name, "path": source_path})
        try:
            tm = SkillManager(skill_dirs=[source_path], isolated=True)
            for skill in tm.list_skill_info():
                skills_map[skill.name] = {
                    "name": skill.name,
                    "description": skill.description,
                    "source": source_name,
                    "path": skill.path,
                }
        except Exception as exc:
            skills_map[f"__error__:{source_name}"] = {
                "name": f"[error:{source_name}]",
                "description": str(exc),
                "source": source_name,
                "path": source_path,
            }

    skills = [value for key, value in skills_map.items() if not key.startswith("__error__:")]
    skills.sort(key=lambda item: item["name"])

    errors = [value for key, value in skills_map.items() if key.startswith("__error__:")]
    source_counts: Dict[str, int] = {}
    for item in skills:
        source_name = item["source"]
        source_counts[source_name] = source_counts.get(source_name, 0) + 1

    return {
        "user_id": resolved_user_id,
        "agent_id": None,
        "workspace": os.path.abspath(workspace) if workspace else None,
        "sources": skill_sources,
        "total": len(skills),
        "source_counts": source_counts,
        "list": skills,
        "errors": errors,
    }


async def validate_requested_skills(
    *,
    requested_skills: Optional[List[str]],
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    workspace: Optional[str] = None,
) -> List[str]:
    normalized = [skill.strip() for skill in (requested_skills or []) if skill and skill.strip()]
    if not normalized:
        return []

    result = await list_available_skills(user_id=user_id, agent_id=agent_id, workspace=workspace)
    available_names = {item["name"] for item in result.get("list", [])}
    missing = [skill for skill in normalized if skill not in available_names]
    if missing:
        available_display = ", ".join(sorted(available_names)) if available_names else "(none)"
        next_steps = ["Run `sage skills` to inspect currently visible skills."]
        if agent_id:
            next_steps[0] = f"Run `sage skills --agent-id {agent_id}` to inspect the skills currently available to that agent."
        if workspace:
            next_steps.append(
                f"Run `sage skills --workspace {os.path.abspath(workspace)}` to inspect workspace skills."
            )
        raise CLIError(
            "Unknown CLI skill(s): "
            f"{', '.join(missing)}\n"
            f"Available skills: {available_display}",
            next_steps=next_steps,
        )
    return normalized


async def get_session_summary(
    *,
    session_id: str,
    user_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    from common.models.conversation import ConversationDao
    from common.services.conversation_service import (
        _load_session_goal,
        _load_session_goal_transition,
    )

    dao = ConversationDao()
    conversation = await dao.get_by_session_id(session_id)
    if not conversation:
        return None

    if user_id and conversation.user_id and conversation.user_id != user_id:
        return None

    counts = conversation.get_message_count()
    goal = _load_session_goal(session_id)
    goal_transition = _load_session_goal_transition(session_id)
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
        "goal": goal.model_dump(mode="json") if goal else None,
        "goal_transition": goal_transition.model_dump(mode="json") if goal_transition else None,
    }


async def inspect_session(
    *,
    session_id: str,
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    message_limit: int = 5,
) -> Dict[str, Any]:
    from common.models.conversation import ConversationDao

    def _normalize_messages(raw_messages: Any) -> List[Dict[str, Any]]:
        if isinstance(raw_messages, str):
            try:
                raw_messages = json.loads(raw_messages)
            except Exception:  # noqa: BLE001
                return []
        return raw_messages if isinstance(raw_messages, list) else []

    def _find_last_message(messages: List[Dict[str, Any]], *, role: Optional[str] = None) -> Optional[Dict[str, Any]]:
        for message in reversed(messages):
            message_role = (message or {}).get("role")
            content = ((message or {}).get("content") or "").strip()
            if role and message_role != role:
                continue
            if content:
                return {
                    "role": message_role,
                    "type": (message or {}).get("type"),
                    "content": content,
                    "message_id": (message or {}).get("message_id"),
                }
        return None

    dao = ConversationDao()
    resolved_user_id = user_id or get_default_cli_user_id()

    if session_id == "latest":
        recent = await dao.get_recent_conversations(
            user_id=resolved_user_id,
            agent_id=agent_id,
        )
        conversation = recent[0] if recent else None
    else:
        conversation = await dao.get_by_session_id(session_id)

    if not conversation:
        if session_id == "latest":
            scope_suffix = f" for user {resolved_user_id}"
            if agent_id:
                scope_suffix += f" and agent {agent_id}"
            raise CLIError(
                f"No recent session found{scope_suffix}",
                next_steps=["Run `sage sessions` to inspect visible sessions."],
            )
        raise CLIError(
            f"Session not found: {session_id}",
            next_steps=["Run `sage sessions` to inspect visible sessions."],
        )

    if resolved_user_id and conversation.user_id and conversation.user_id != resolved_user_id:
        raise CLIError(
            f"Session {conversation.session_id} is not visible to user {resolved_user_id}",
            next_steps=["Check `--user-id`, or run `sage sessions --user-id <user>` to inspect visible sessions."],
        )
    if agent_id and conversation.agent_id and conversation.agent_id != agent_id:
        raise CLIError(
            f"Session {conversation.session_id} is not visible to agent {agent_id}",
            next_steps=[f"Run `sage sessions --agent-id {agent_id}` to inspect sessions for that agent."],
        )

    counts = conversation.get_message_count()
    messages = _normalize_messages(conversation.messages or [])

    normalized_limit = max(0, int(message_limit))
    preview_messages = []
    start_index = max(0, len(messages) - normalized_limit)
    for index, message in enumerate(messages[start_index:], start=start_index):
        preview_messages.append(
            {
                "index": index,
                "role": (message or {}).get("role"),
                "type": (message or {}).get("type"),
                "content": (message or {}).get("content"),
                "message_id": (message or {}).get("message_id"),
            }
        )

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
        "last_user_message": _find_last_message(messages, role="user"),
        "last_assistant_message": _find_last_message(messages, role="assistant")
        or _find_last_message(messages, role="agent"),
        "recent_messages": preview_messages,
        "message_preview_limit": normalized_limit,
    }


def validate_cli_runtime_requirements() -> config.StartupConfig:
    cfg = init_cli_config(init_logging=False)
    issues = _collect_runtime_issues(cfg)
    if issues["errors"]:
        detail = "\n".join(f"- {item}" for item in issues["errors"])
        raise CLIError(
            "CLI runtime is not ready:\n"
            f"{detail}",
            next_steps=issues["next_steps"],
        )
    return cfg

import os
from typing import Any, Dict, Optional

from common.core import config

from app.cli.services.base import CLIError
from app.cli.services.base import mask_api_key as _mask_api_key
from app.cli.services.base import sanitize_provider_record as _sanitize_provider_record
from app.cli.services.base import trim_optional_text as _trim_optional_text
from app.cli.services.doctor import _collect_memory_runtime_diagnostics
from app.cli.services.doctor import (
    build_minimal_cli_env_template,
    collect_config_info,
    collect_doctor_info,
    probe_default_provider,
    write_cli_config_file,
)
from app.cli.services.provider import (
    _build_provider_update_data,
    _resolve_provider_create_data,
    create_cli_provider,
    delete_cli_provider,
    inspect_cli_provider,
    list_cli_providers,
    query_cli_providers,
    update_cli_provider,
    verify_cli_provider,
)
from app.cli.services.runtime import (
    collect_runtime_issues as _collect_runtime_issues,
    cli_db_runtime,
    cli_runtime,
    configure_cli_logging,
    dependency_status as _dependency_status,
    get_default_cli_max_loop_count,
    get_default_cli_user_id,
    init_cli_config,
    run_request_stream,
    validate_cli_request_options,
    validate_cli_runtime_requirements,
    build_run_request,
)
from app.cli.services.session_query import (
    get_session_summary,
    inspect_session,
    list_available_skills,
    list_cli_agents,
    list_sessions,
    validate_requested_skills,
)


def _resolve_provider_create_data_compat(**kwargs):
    from common.schemas.base import LLMProviderCreate

    cfg = init_cli_config(init_logging=False)
    resolved_base_url = _trim_optional_text(kwargs.get("base_url")) or _trim_optional_text(cfg.default_llm_api_base_url)
    resolved_api_key = _trim_optional_text(kwargs.get("api_key")) or _trim_optional_text(cfg.default_llm_api_key)
    resolved_model = _trim_optional_text(kwargs.get("model")) or _trim_optional_text(cfg.default_llm_model_name)

    next_steps = []
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
            name=_trim_optional_text(kwargs.get("name")),
            base_url=resolved_base_url,
            api_keys=[resolved_api_key],
            model=resolved_model,
            max_tokens=kwargs.get("max_tokens"),
            temperature=kwargs.get("temperature"),
            top_p=kwargs.get("top_p"),
            presence_penalty=kwargs.get("presence_penalty"),
            max_model_len=kwargs.get("max_model_len"),
            supports_multimodal=bool(kwargs.get("supports_multimodal")),
            supports_structured_output=bool(kwargs.get("supports_structured_output")),
            is_default=bool(kwargs.get("is_default")),
        ),
        "sources": {
            "base_url": "arg" if _trim_optional_text(kwargs.get("base_url")) else "default",
            "api_key": "arg" if _trim_optional_text(kwargs.get("api_key")) else "default",
            "model": "arg" if _trim_optional_text(kwargs.get("model")) else "default",
        },
    }


_resolve_provider_create_data = _resolve_provider_create_data_compat


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
    dep_status = _dependency_status()
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
        "dependencies": dep_status,
        **issues,
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


def build_minimal_cli_env_template() -> str:
    cfg = init_cli_config(init_logging=False)
    api_base_url = (os.environ.get("SAGE_DEFAULT_LLM_API_BASE_URL") or "").strip() or (
        cfg.default_llm_api_base_url or "https://api.deepseek.com/v1"
    )
    model_name = (os.environ.get("SAGE_DEFAULT_LLM_MODEL_NAME") or "").strip() or (
        cfg.default_llm_model_name or "deepseek-chat"
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

__all__ = [
    "CLIError",
    "build_minimal_cli_env_template",
    "build_run_request",
    "cli_db_runtime",
    "cli_runtime",
    "collect_config_info",
    "collect_doctor_info",
    "configure_cli_logging",
    "create_cli_provider",
    "delete_cli_provider",
    "get_default_cli_max_loop_count",
    "get_default_cli_user_id",
    "get_session_summary",
    "init_cli_config",
    "inspect_cli_provider",
    "inspect_session",
    "list_available_skills",
    "list_cli_agents",
    "list_cli_providers",
    "list_sessions",
    "probe_default_provider",
    "query_cli_providers",
    "run_request_stream",
    "update_cli_provider",
    "validate_cli_request_options",
    "validate_cli_runtime_requirements",
    "validate_requested_skills",
    "verify_cli_provider",
    "write_cli_config_file",
    "_build_provider_update_data",
    "_collect_runtime_issues",
    "_dependency_status",
    "_mask_api_key",
    "_resolve_provider_create_data",
    "_sanitize_provider_record",
    "config",
]

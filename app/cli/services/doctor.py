import os
from typing import Any, Dict, List, Optional

from app.cli.services.runtime import (
    collect_runtime_issues,
    dependency_status,
    get_default_cli_max_loop_count,
    get_default_cli_user_id,
    init_cli_config,
)
from common.core import config
from common.services.llm_provider_probe_utils import friendly_provider_probe_error


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
    dep_status = dependency_status()
    issues = collect_runtime_issues(cfg)
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


async def probe_default_provider() -> Dict[str, Any]:
    from sagents.llm import probe_connection

    cfg = init_cli_config(init_logging=False)
    issues = collect_runtime_issues(cfg)
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


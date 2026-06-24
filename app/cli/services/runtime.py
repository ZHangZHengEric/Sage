import importlib
import json
import logging
import os
import pkgutil
import sys
from contextlib import asynccontextmanager
from importlib.util import find_spec
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

from dotenv import load_dotenv

from app.cli.services.base import CLIError
from common.core import config
from common.schemas.chat import Message, StreamRequest
from sagents.utils.sandbox.policy import (
    SUPPORTED_APPROVAL_MODES,
    normalize_approval_mode,
)

AGENT_CONFIG_PRESETS = {
    "coding": "examples/coding_agent_config.json",
}
SUPPORTED_SANDBOX_TYPES = {"local", "remote", "passthrough"}
DEFAULT_WORKSPACE_GUIDANCE_MAX_BYTES = 32 * 1024
WORKSPACE_GUIDANCE_CONTEXT_KEY = "workspace_guidance"
WORKSPACE_GUIDANCE_FILES_CONTEXT_KEY = "workspace_guidance_files"
WORKSPACE_GUIDANCE_ROOT_CONTEXT_KEY = "workspace_guidance_root"

BUNDLED_CODING_AGENT_CONFIG_PATH = (
    Path(__file__).resolve().parents[3] / AGENT_CONFIG_PRESETS["coding"]
).resolve()


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


def is_bundled_coding_agent_config(agent_config: Optional[str]) -> bool:
    if not agent_config:
        return False
    normalized = agent_config.strip()
    if normalized == "coding":
        return True
    try:
        return (
            Path(normalized).expanduser().resolve() == BUNDLED_CODING_AGENT_CONFIG_PATH
        )
    except OSError:
        return False


def validate_agent_config_workspace(
    *,
    agent_config: Optional[str],
    workspace: Optional[str],
) -> None:
    if not is_bundled_coding_agent_config(agent_config):
        return
    if workspace and workspace.strip():
        return
    raise CLIError(
        "The bundled `coding` agent config requires `--workspace`.",
        next_steps=[
            "Run with `--workspace /path/to/repo` so coding tools operate on the intended project.",
            "Use a custom JSON agent config path if you intentionally do not need a repo workspace.",
        ],
    )


def validate_agent_config_workspace_guidance(
    *,
    agent_config: Optional[Dict[str, Any]],
    workspace: Optional[str],
) -> None:
    if not agent_config:
        return
    guidance = _workspace_guidance_config(
        _agent_config_value(agent_config, "workspaceGuidance", "workspace_guidance")
    )
    if not guidance["enabled"]:
        return
    if not workspace or not workspace.strip():
        raise CLIError(
            "Agent config `workspaceGuidance` requires `--workspace`.",
            next_steps=[
                "Pass `--workspace /path/to/project`, or disable `workspaceGuidance` in the agent config."
            ],
        )
    if not guidance["files"]:
        raise CLIError(
            "Agent config `workspaceGuidance.files` must list at least one file when enabled.",
            next_steps=[
                "Add workspace-root file names such as `AGENT.md` or `AGENTS.md`."
            ],
        )
    for file_name in guidance["files"]:
        _validate_workspace_guidance_file_name(file_name)


def _agent_config_value(agent_config: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in agent_config:
            return agent_config.get(key)
    return None


def _compact_agent_config_dict(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    compacted = {
        key: item
        for key, item in value.items()
        if item is not None and not (isinstance(item, str) and not item.strip())
    }
    return compacted or None


def _agent_config_dict(value: Any, field_name: str) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    raise CLIError(
        f"Agent config `{field_name}` must be a JSON object.",
        next_steps=["Fix the agent config JSON, then run the command again."],
        debug_detail=f"{field_name}={value!r}",
    )


def _agent_config_dict_list(
    value: Any, field_name: str
) -> Optional[List[Dict[str, Any]]]:
    if value is None:
        return None
    if not isinstance(value, list):
        raise CLIError(
            f"Agent config `{field_name}` must be a list of JSON objects.",
            next_steps=["Fix the agent config JSON, then run the command again."],
        )

    normalized_items = []
    for item in value:
        if not isinstance(item, dict):
            raise CLIError(
                f"Agent config `{field_name}` must contain only JSON objects.",
                next_steps=["Fix the agent config JSON, then run the command again."],
                debug_detail=f"{field_name} contains {type(item).__name__}",
            )
        normalized_items.append(item)
    return normalized_items


def _agent_config_list(value: Any, field_name: str) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        normalized = value.strip()
        return [normalized] if normalized else []
    if not isinstance(value, list):
        raise CLIError(
            f"Agent config `{field_name}` must be a string or list of strings.",
            next_steps=["Fix the agent config JSON, then run the command again."],
        )

    normalized_items = []
    for item in value:
        if not isinstance(item, str):
            raise CLIError(
                f"Agent config `{field_name}` must contain only strings.",
                next_steps=["Fix the agent config JSON, then run the command again."],
                debug_detail=f"{field_name} contains {type(item).__name__}",
            )
        normalized = item.strip()
        if normalized:
            normalized_items.append(normalized)
    return normalized_items


def _agent_config_string(value: Any, field_name: str) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    raise CLIError(
        f"Agent config `{field_name}` must be a string.",
        next_steps=["Fix the agent config JSON, then run the command again."],
        debug_detail=f"{field_name}={value!r}",
    )


def _agent_config_bool(value: Any, field_name: str) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    raise CLIError(
        f"Agent config `{field_name}` must be a JSON boolean.",
        next_steps=["Fix the agent config JSON, then run the command again."],
        debug_detail=f"{field_name}={value!r}",
    )


def _agent_config_positive_int(value: Any, field_name: str) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise CLIError(
            f"Agent config `{field_name}` must be a positive integer.",
            next_steps=["Fix the agent config JSON, then run the command again."],
            debug_detail=f"{field_name}={value!r}",
        )
    return value


def _workspace_guidance_config(value: Any) -> Dict[str, Any]:
    if value is None:
        return {"enabled": False}
    if not isinstance(value, dict):
        raise CLIError(
            "Agent config `workspaceGuidance` must be a JSON object.",
            next_steps=["Fix the agent config JSON, then run the command again."],
            debug_detail=f"workspaceGuidance={value!r}",
        )

    enabled = _agent_config_bool(value.get("enabled"), "workspaceGuidance.enabled")
    if enabled is None:
        enabled = False
    if not enabled:
        return {"enabled": False}

    files = list(
        dict.fromkeys(_agent_config_list(value.get("files"), "workspaceGuidance.files"))
    )
    max_bytes = _agent_config_positive_int(
        value.get("maxBytes") if "maxBytes" in value else value.get("max_bytes"),
        "workspaceGuidance.maxBytes",
    )
    if max_bytes is None:
        max_bytes = DEFAULT_WORKSPACE_GUIDANCE_MAX_BYTES

    inject_as = _agent_config_string(
        value.get("injectAs") if "injectAs" in value else value.get("inject_as"),
        "workspaceGuidance.injectAs",
    )
    if inject_as is None:
        inject_as = "systemContext"
    if inject_as != "systemContext":
        raise CLIError(
            "Agent config `workspaceGuidance.injectAs` currently supports only `systemContext`.",
            next_steps=["Set `workspaceGuidance.injectAs` to `systemContext`."],
            debug_detail=f"workspaceGuidance.injectAs={inject_as!r}",
        )

    return {
        "enabled": enabled,
        "files": files,
        "max_bytes": max_bytes,
    }


def _validate_workspace_guidance_file_name(file_name: str) -> None:
    if file_name != Path(file_name).name:
        raise CLIError(
            "Agent config `workspaceGuidance.files` currently supports workspace-root file names only.",
            next_steps=[
                "Use file names such as `AGENT.md` or `AGENTS.md`, without directories."
            ],
            debug_detail=f"workspaceGuidance file={file_name!r}",
        )
    if file_name in {".", ".."}:
        raise CLIError(
            "Agent config `workspaceGuidance.files` contains an invalid file name.",
            next_steps=["Use a normal workspace-root file name."],
            debug_detail=f"workspaceGuidance file={file_name!r}",
        )


def _read_workspace_guidance_file(path: Path, *, max_bytes: int) -> tuple[str, int]:
    with path.open("rb") as handle:
        content = handle.read(max_bytes + 1)
    truncated = len(content) > max_bytes
    if truncated:
        content = content[:max_bytes]
    bytes_read = len(content)
    text = content.decode("utf-8", errors="replace").strip()
    if truncated:
        text = f"{text}\n\n[truncated at {max_bytes} bytes]"
    return text, bytes_read


def load_workspace_guidance(
    *,
    agent_config: Dict[str, Any],
    workspace: Optional[str],
) -> Optional[Dict[str, Any]]:
    guidance = _workspace_guidance_config(
        _agent_config_value(agent_config, "workspaceGuidance", "workspace_guidance")
    )
    if not guidance["enabled"]:
        return None

    if not workspace or not workspace.strip():
        raise CLIError(
            "Agent config `workspaceGuidance` requires `--workspace`.",
            next_steps=[
                "Pass `--workspace /path/to/project`, or disable `workspaceGuidance` in the agent config."
            ],
        )

    files = guidance["files"]
    if not files:
        raise CLIError(
            "Agent config `workspaceGuidance.files` must list at least one file when enabled.",
            next_steps=[
                "Add workspace-root file names such as `AGENT.md` or `AGENTS.md`."
            ],
        )

    workspace_path = Path(workspace).expanduser().resolve()
    remaining_bytes = guidance["max_bytes"]
    sections = []
    loaded_files = []
    for file_name in files:
        if remaining_bytes == 0:
            break
        _validate_workspace_guidance_file_name(file_name)
        path = workspace_path / file_name
        if not path.exists():
            continue
        if not path.is_file():
            continue
        resolved_path = path.resolve()
        if not resolved_path.is_relative_to(workspace_path):
            raise CLIError(
                f"Workspace guidance file must stay inside the workspace: {path}",
                next_steps=[
                    "Replace the symlink with a regular workspace file, or remove it from `workspaceGuidance.files`."
                ],
                debug_detail=f"resolved_path={resolved_path}",
            )
        try:
            content, bytes_read = _read_workspace_guidance_file(
                resolved_path,
                max_bytes=remaining_bytes,
            )
        except OSError as exc:
            raise CLIError(
                f"Failed to read workspace guidance file: {path}",
                next_steps=[
                    "Check file permissions, or remove the file from `workspaceGuidance.files`."
                ],
                debug_detail=str(exc),
            ) from exc
        if not content:
            continue
        loaded_files.append(file_name)
        sections.append(f"## {file_name}\n{content}")
        remaining_bytes = max(0, remaining_bytes - bytes_read)

    if not sections:
        return None

    return {
        "content": "\n\n".join(sections),
        "files": loaded_files,
        "workspace": str(workspace_path),
    }


def apply_workspace_guidance_to_system_context(
    system_context: Dict[str, Any],
    *,
    agent_config: Dict[str, Any],
    workspace: Optional[str],
) -> None:
    guidance = load_workspace_guidance(agent_config=agent_config, workspace=workspace)
    if guidance is None:
        return
    system_context[WORKSPACE_GUIDANCE_CONTEXT_KEY] = guidance["content"]
    system_context[WORKSPACE_GUIDANCE_FILES_CONTEXT_KEY] = guidance["files"]
    system_context[WORKSPACE_GUIDANCE_ROOT_CONTEXT_KEY] = guidance["workspace"]


def _cli_positive_int(value: Any, *, next_steps: List[str]) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise CLIError(
            "Invalid max loop count",
            next_steps=next_steps,
            debug_detail=f"max_loop_count={value!r}",
        )
    return value


def _agent_config_agent_mode(value: Any) -> Optional[str]:
    agent_mode = _agent_config_string(value, "agentMode")
    if agent_mode is None:
        return None
    agent_mode = agent_mode.lower()
    if agent_mode not in {"simple", "multi", "fibre"}:
        raise CLIError(
            "Agent config `agentMode` must be one of: simple, multi, fibre.",
            next_steps=["Fix the agent config JSON, then run the command again."],
            debug_detail=f"agentMode={agent_mode!r}",
        )
    return agent_mode


def _cli_agent_mode(value: Any) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise CLIError(
            "Invalid agent mode",
            next_steps=["Use one of: simple, multi, fibre."],
            debug_detail=f"agent_mode={value!r}",
        )
    agent_mode = value.strip().lower()
    if agent_mode not in {"simple", "multi", "fibre"}:
        raise CLIError(
            "Invalid agent mode",
            next_steps=["Use one of: simple, multi, fibre."],
            debug_detail=f"agent_mode={value!r}",
        )
    return agent_mode


def _agent_config_string_list_dict(
    value: Any,
    field_name: str,
) -> Optional[Dict[str, List[str]]]:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise CLIError(
            f"Agent config `{field_name}` must be a JSON object.",
            next_steps=["Fix the agent config JSON, then run the command again."],
            debug_detail=f"{field_name}={value!r}",
        )

    normalized: Dict[str, List[str]] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise CLIError(
                f"Agent config `{field_name}` keys must be strings.",
                next_steps=["Fix the agent config JSON, then run the command again."],
                debug_detail=f"{field_name} key={key!r}",
            )
        normalized_items = _agent_config_list(item, f"{field_name}.{key}")
        if normalized_items:
            normalized[key] = normalized_items
    return normalized


def _agent_config_dict_dict(
    value: Any,
    field_name: str,
) -> Optional[Dict[str, Dict[str, Any]]]:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise CLIError(
            f"Agent config `{field_name}` must be a JSON object.",
            next_steps=["Fix the agent config JSON, then run the command again."],
            debug_detail=f"{field_name}={value!r}",
        )

    normalized: Dict[str, Dict[str, Any]] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise CLIError(
                f"Agent config `{field_name}` keys must be strings.",
                next_steps=["Fix the agent config JSON, then run the command again."],
                debug_detail=f"{field_name} key={key!r}",
            )
        if not isinstance(item, dict):
            raise CLIError(
                f"Agent config `{field_name}.{key}` must be a JSON object.",
                next_steps=["Fix the agent config JSON, then run the command again."],
                debug_detail=f"{field_name}.{key}={item!r}",
            )
        normalized[key] = item
    return normalized


def _agent_config_custom_sub_agents(
    value: Any,
    field_name: str,
) -> Optional[List[Dict[str, Any]]]:
    items = _agent_config_dict_list(value, field_name)
    if items is None:
        return None

    key_aliases = {
        "agentId": "agent_id",
        "systemPrompt": "system_prompt",
        "availableTools": "available_tools",
        "availableSkills": "available_skills",
        "availableWorkflows": "available_workflows",
        "systemContext": "system_context",
    }
    normalized_agents: List[Dict[str, Any]] = []
    for index, item in enumerate(items):
        normalized = {
            key_aliases.get(key, key): item_value for key, item_value in item.items()
        }
        field_prefix = f"{field_name}[{index}]"
        name = _agent_config_string(normalized.get("name"), f"{field_prefix}.name")
        if name is None:
            raise CLIError(
                f"Agent config `{field_prefix}.name` must be a non-empty string.",
                next_steps=["Fix the agent config JSON, then run the command again."],
            )

        agent: Dict[str, Any] = {"name": name}
        for string_key in ("agent_id", "system_prompt", "description"):
            string_value = _agent_config_string(
                normalized.get(string_key),
                f"{field_prefix}.{string_key}",
            )
            if string_value is not None:
                agent[string_key] = string_value

        for list_key in ("available_tools", "available_skills"):
            list_value = _agent_config_list(
                normalized.get(list_key),
                f"{field_prefix}.{list_key}",
            )
            if list_value:
                agent[list_key] = list_value

        available_workflows = _agent_config_string_list_dict(
            normalized.get("available_workflows"),
            f"{field_prefix}.available_workflows",
        )
        if available_workflows is not None:
            agent["available_workflows"] = available_workflows

        system_context = _agent_config_dict(
            normalized.get("system_context"),
            f"{field_prefix}.system_context",
        )
        if system_context is not None:
            agent["system_context"] = system_context

        normalized_agents.append(agent)
    return normalized_agents


def _normalize_llm_config(value: Any) -> Optional[Dict[str, Any]]:
    if value is not None and not isinstance(value, dict):
        raise CLIError(
            "Agent config `llmConfig` must be a JSON object.",
            next_steps=["Fix the agent config JSON, then run the command again."],
            debug_detail=f"llmConfig={value!r}",
        )

    config_dict = _compact_agent_config_dict(value)
    if not config_dict:
        return None

    key_aliases = {
        "apiKey": "api_key",
        "baseUrl": "base_url",
        "baseURL": "base_url",
        "maxTokens": "max_tokens",
        "maxModelLen": "max_model_len",
        "topP": "top_p",
        "presencePenalty": "presence_penalty",
        "supportsMultimodal": "supports_multimodal",
        "supportsStructuredOutput": "supports_structured_output",
        "fastApiKey": "fast_api_key",
        "fastBaseUrl": "fast_base_url",
        "fastBaseURL": "fast_base_url",
        "fastModelName": "fast_model_name",
    }
    normalized: Dict[str, Any] = {}
    for key, item in config_dict.items():
        normalized[key_aliases.get(key, key)] = item
    return normalized or None


def resolve_agent_config_path(path: Optional[str]) -> Optional[str]:
    if path is None:
        return None

    normalized_path = path.strip()
    if not normalized_path:
        return None
    preset_path = AGENT_CONFIG_PRESETS.get(normalized_path)
    if preset_path:
        return str(Path(__file__).resolve().parents[3] / preset_path)
    return os.path.abspath(os.path.expanduser(normalized_path))


def load_agent_config_file(path: Optional[str]) -> Dict[str, Any]:
    if path is None:
        return {}

    normalized_path = path.strip()
    if not normalized_path:
        raise CLIError(
            "Agent config path is empty.",
            next_steps=["Pass a JSON file path or preset name to `--agent-config`."],
        )

    config_path = resolve_agent_config_path(normalized_path) or ""
    if not os.path.exists(config_path):
        preset_hint = ""
        if normalized_path in AGENT_CONFIG_PRESETS:
            preset_hint = " The built-in preset file is missing from this checkout."
        raise CLIError(
            f"Agent config file does not exist: {config_path}",
            next_steps=[
                "Pass an existing JSON file to `--agent-config`.",
                "Use `--agent-config coding` for the bundled coding preset in a source checkout.",
            ],
            debug_detail=preset_hint.strip() or None,
        )
    if not os.path.isfile(config_path):
        raise CLIError(
            f"Agent config path is not a file: {config_path}",
            next_steps=["Pass a JSON file path to `--agent-config`."],
        )

    try:
        with open(config_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except OSError as exc:
        raise CLIError(
            f"Failed to read agent config file: {config_path}",
            next_steps=[
                "Check that the file exists and is readable, then run the command again."
            ],
            debug_detail=str(exc),
        ) from exc
    except json.JSONDecodeError as exc:
        raise CLIError(
            f"Agent config is not valid JSON: {config_path}",
            next_steps=["Fix the JSON syntax, then run the command again."],
            debug_detail=str(exc),
        ) from exc

    if not isinstance(data, dict):
        raise CLIError(
            f"Agent config must be a JSON object: {config_path}",
            next_steps=["Use a Sage agent config JSON object."],
        )
    return data


def validate_agent_selection_options(
    *,
    agent_id: Optional[str] = None,
    agent_config: Optional[str] = None,
) -> None:
    normalized_agent_id = (agent_id or "").strip()
    normalized_agent_config = agent_config.strip() if agent_config is not None else ""
    if agent_id is not None and not normalized_agent_id:
        raise CLIError(
            "Agent id is empty.",
            next_steps=["Pass a non-empty saved Sage agent id to `--agent-id`."],
        )
    if normalized_agent_id and normalized_agent_config:
        raise CLIError(
            "Use either `--agent-id` or `--agent-config`, not both.",
            next_steps=[
                "Use `--agent-config` for a JSON/preset-driven one-off agent.",
                "Use `--agent-id` for a saved Sage agent.",
            ],
        )


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
        next_steps.append(
            "Install project dependencies first, for example: pip install -r requirements.txt"
        )
        next_steps.append(
            "If only rank_bm25 is missing, install it directly with: pip install rank-bm25"
        )

    if not (cfg.default_llm_api_key or "").strip():
        errors.append("Missing SAGE_DEFAULT_LLM_API_KEY")
        next_steps.append(
            "Set SAGE_DEFAULT_LLM_API_KEY in your shell, ~/.sage/.sage_env, or local .env before using run/chat."
        )

    if not (cfg.default_llm_api_base_url or "").strip():
        errors.append("Missing SAGE_DEFAULT_LLM_API_BASE_URL")
        next_steps.append(
            "Set SAGE_DEFAULT_LLM_API_BASE_URL in your shell, ~/.sage/.sage_env, or local .env."
        )

    if not (cfg.default_llm_model_name or "").strip():
        errors.append("Missing SAGE_DEFAULT_LLM_MODEL_NAME")
        next_steps.append(
            "Set SAGE_DEFAULT_LLM_MODEL_NAME in your shell, ~/.sage/.sage_env, or local .env."
        )

    if cfg.db_type == "mysql":
        warnings.append(
            "CLI is using MySQL. For local development, file DB is usually simpler."
        )
        next_steps.append(
            "If you only need local development, consider setting SAGE_DB_TYPE=file."
        )

    if cfg.auth_mode != "native":
        warnings.append(
            f"Current auth mode is {cfg.auth_mode}. CLI currently works best with native/local setups."
        )

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
async def cli_runtime(
    *, verbose: bool = False
) -> AsyncGenerator[config.StartupConfig, None]:
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

    ToolManager.discover_builtin_mcp_tools_from_path = _skip_builtin_mcp_discovery  # pyright: ignore[reportAttributeAccessIssue]
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
async def cli_db_runtime(
    *, verbose: bool = False
) -> AsyncGenerator[config.StartupConfig, None]:
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
    agent_config: Optional[Dict[str, Any]] = None,
    workspace: Optional[str] = None,
    sandbox_approval_mode: Optional[str] = None,
) -> StreamRequest:
    if agent_config is None:
        agent_config = {}
    elif not isinstance(agent_config, dict):
        raise CLIError(
            "Agent config must be a JSON object.",
            next_steps=["Fix the agent config JSON, then run the command again."],
            debug_detail=f"agent_config={agent_config!r}",
        )

    normalized_agent_id = None
    if agent_id is not None:
        normalized_agent_id = agent_id.strip()
        if not normalized_agent_id:
            raise CLIError(
                "Agent id is empty.",
                next_steps=["Pass a non-empty saved Sage agent id to `--agent-id`."],
            )
    if normalized_agent_id and agent_config:
        raise CLIError(
            "Use either `--agent-id` or `--agent-config`, not both.",
            next_steps=[
                "Use `--agent-config` for a JSON/preset-driven one-off agent.",
                "Use `--agent-id` for a saved Sage agent.",
            ],
        )

    config_loop_count = _agent_config_value(
        agent_config,
        "maxLoopCount",
        "max_loop_count",
    )
    config_loop_count = _agent_config_positive_int(config_loop_count, "maxLoopCount")
    effective_max_loop_count = max_loop_count
    if effective_max_loop_count is None:
        effective_max_loop_count = config_loop_count
    if effective_max_loop_count is None:
        effective_max_loop_count = get_default_cli_max_loop_count()
    effective_max_loop_count = _cli_positive_int(
        effective_max_loop_count,
        next_steps=[
            "Use a positive integer in `--max-loop-count` or agent config `maxLoopCount`."
        ],
    )

    config_skills = _agent_config_list(
        _agent_config_value(agent_config, "availableSkills", "available_skills"),
        "availableSkills",
    )
    merged_skills = []
    for skill in config_skills + list(available_skills or []):
        if skill and skill not in merged_skills:
            merged_skills.append(skill)

    config_deep_thinking = _agent_config_value(
        agent_config,
        "deepThinking",
        "deep_thinking",
    )
    config_deep_thinking = _agent_config_bool(config_deep_thinking, "deepThinking")
    if config_deep_thinking is True and not task.lstrip().startswith(
        "<enable_deep_thinking>"
    ):
        task = "<enable_deep_thinking>true</enable_deep_thinking>\n" + task

    config_system_context = (
        _agent_config_dict(
            _agent_config_value(agent_config, "systemContext", "system_context"),
            "systemContext",
        )
        or {}
    )
    system_context = dict(config_system_context)
    if not system_context:
        system_context["response_language"] = "zh-CN"
    config_approval_mode = _agent_config_string(
        _agent_config_value(
            agent_config,
            "sandboxApprovalMode",
            "sandbox_approval_mode",
        ),
        "sandboxApprovalMode",
    )
    normalized_approval_mode = normalize_sandbox_approval_mode(
        sandbox_approval_mode or config_approval_mode
    )
    if normalized_approval_mode:
        system_context["sandbox_approval_mode"] = normalized_approval_mode
    apply_workspace_guidance_to_system_context(
        system_context,
        agent_config=agent_config,
        workspace=workspace,
    )
    if isinstance(goal, dict) and not goal.get("clear"):
        objective = str(goal.get("objective") or "").strip()
        status = str(goal.get("status") or "active").strip() or "active"
        if objective:
            system_context.update(
                {
                    "goal_mode": "true",
                    "active_goal": objective,
                    "goal_status": status,
                }
            )
    return StreamRequest(
        messages=[Message(role="user", content=task)],
        session_id=session_id,
        user_id=user_id or get_default_cli_user_id(),
        agent_id=normalized_agent_id,
        agent_name=_agent_config_string(
            _agent_config_value(agent_config, "name", "agent_name"),
            "name",
        ),
        agent_mode=(
            _cli_agent_mode(agent_mode)
            or _agent_config_agent_mode(
                _agent_config_value(agent_config, "agentMode", "agent_mode")
            )
            or "simple"
        ),
        available_workflows=_agent_config_string_list_dict(
            _agent_config_value(
                agent_config,
                "availableWorkflows",
                "available_workflows",
            ),
            "availableWorkflows",
        ),
        llm_model_config=_normalize_llm_config(
            _agent_config_value(agent_config, "llmConfig", "llm_model_config")
        ),
        system_prefix=_agent_config_string(
            _agent_config_value(agent_config, "systemPrefix", "system_prefix"),
            "systemPrefix",
        ),
        available_tools=_agent_config_list(
            _agent_config_value(agent_config, "availableTools", "available_tools"),
            "availableTools",
        )
        or None,
        available_skills=merged_skills or None,
        available_knowledge_bases=_agent_config_list(
            _agent_config_value(
                agent_config,
                "availableKnowledgeBases",
                "available_knowledge_bases",
            ),
            "availableKnowledgeBases",
        )
        or None,
        available_sub_agent_ids=_agent_config_list(
            _agent_config_value(
                agent_config,
                "availableSubAgentIds",
                "available_sub_agent_ids",
            ),
            "availableSubAgentIds",
        )
        or None,
        more_suggest=_agent_config_bool(
            _agent_config_value(agent_config, "moreSuggest", "more_suggest"),
            "moreSuggest",
        ),
        force_summary=(
            _agent_config_bool(
                _agent_config_value(agent_config, "forceSummary", "force_summary"),
                "forceSummary",
            )
            or False
        ),
        multi_agent=_agent_config_bool(
            _agent_config_value(agent_config, "multiAgent", "multi_agent"),
            "multiAgent",
        ),
        custom_sub_agents=_agent_config_custom_sub_agents(
            _agent_config_value(agent_config, "customSubAgents", "custom_sub_agents"),
            "customSubAgents",
        ),
        context_budget_config=_agent_config_dict(
            _agent_config_value(
                agent_config,
                "contextBudgetConfig",
                "context_budget_config",
            ),
            "contextBudgetConfig",
        ),
        extra_mcp_config=_agent_config_dict_dict(
            _agent_config_value(agent_config, "extraMcpConfig", "extra_mcp_config"),
            "extraMcpConfig",
        ),
        memory_type=_agent_config_string(
            _agent_config_value(agent_config, "memoryType", "memory_type"),
            "memoryType",
        )
        or "session",
        max_loop_count=effective_max_loop_count,
        system_context=system_context,
        sandbox_approval_mode=normalized_approval_mode,
    )


def validate_cli_request_options(
    *,
    workspace: Optional[str] = None,
    max_loop_count: Optional[int] = None,
    sandbox_type: Optional[str] = None,
    sandbox_approval_mode: Optional[str] = None,
) -> Optional[str]:
    if max_loop_count is not None:
        _cli_positive_int(
            max_loop_count,
            next_steps=["Pass `--max-loop-count` with a positive integer value."],
        )

    if sandbox_type is not None:
        normalize_sandbox_type(sandbox_type)
    if sandbox_approval_mode is not None:
        normalize_sandbox_approval_mode(sandbox_approval_mode)

    if not workspace:
        return None

    workspace_path = Path(workspace).expanduser().resolve()
    if workspace_path.exists() and not workspace_path.is_dir():
        raise CLIError(
            f"Workspace path is not a directory: {workspace_path}",
            next_steps=[
                "Choose a directory path for `--workspace`, or remove the conflicting file."
            ],
        )

    parent_dir = (
        workspace_path
        if workspace_path.is_dir()
        else workspace_path.parent or Path.cwd()
    )
    if not parent_dir.exists():
        raise CLIError(
            f"Workspace parent directory does not exist: {parent_dir}",
            next_steps=[
                "Create the parent directory first, or choose a different `--workspace` path."
            ],
        )

    if not os.access(parent_dir, os.W_OK):
        raise CLIError(
            f"Workspace path is not writable: {parent_dir}",
            next_steps=[
                "Choose a writable `--workspace` path, or update directory permissions."
            ],
        )

    return str(workspace_path)


async def run_request_stream(
    request: StreamRequest,
    workspace: Optional[str] = None,
    sandbox_type: Optional[str] = None,
    sandbox_approval_mode: Optional[str] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    from common.services.chat_service import (
        _copy_sage_usage_docs_to_workspace,
        execute_chat_session,
        populate_request_from_agent_config,
        prepare_session,
    )
    from common.services.chat_utils import create_skill_proxy

    sandbox_type = normalize_sandbox_type(sandbox_type)
    normalized_approval_mode = normalize_sandbox_approval_mode(
        sandbox_approval_mode or request.sandbox_approval_mode
    )
    if normalized_approval_mode:
        request.sandbox_approval_mode = normalized_approval_mode
        if request.system_context is None:
            request.system_context = {}
        request.system_context["sandbox_approval_mode"] = normalized_approval_mode
    previous_sandbox_mode = os.environ.get("SAGE_SANDBOX_MODE")
    if sandbox_type:
        os.environ["SAGE_SANDBOX_MODE"] = sandbox_type
    try:
        await populate_request_from_agent_config(request, require_agent_id=False)
        stream_service, _lock = await prepare_session(request)
        if workspace:
            workspace_path = os.path.abspath(workspace)
            os.makedirs(workspace_path, exist_ok=True)
            stream_service.agent_workspace = workspace_path
            stream_service.skill_manager, stream_service.agent_skill_manager = (
                create_skill_proxy(
                    request.available_skills,  # pyright: ignore[reportArgumentType]
                    user_id=request.user_id,
                    agent_workspace=workspace_path,
                )
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
    finally:
        if sandbox_type:
            if previous_sandbox_mode is None:
                os.environ.pop("SAGE_SANDBOX_MODE", None)
            else:
                os.environ["SAGE_SANDBOX_MODE"] = previous_sandbox_mode


def normalize_sandbox_type(sandbox_type: Optional[str]) -> Optional[str]:
    if sandbox_type is None:
        return None
    normalized = sandbox_type.strip().lower()
    if not normalized:
        return None
    if normalized not in SUPPORTED_SANDBOX_TYPES:
        raise CLIError(
            f"Unsupported sandbox type: {sandbox_type}",
            next_steps=[
                "Use `local`, `remote`, or `passthrough`.",
            ],
        )
    return normalized


def normalize_sandbox_approval_mode(
    sandbox_approval_mode: Optional[str],
) -> Optional[str]:
    if sandbox_approval_mode is None:
        return None
    mode = normalize_approval_mode(sandbox_approval_mode)
    if mode is None:
        raise CLIError(
            f"Unsupported sandbox approval mode: {sandbox_approval_mode}",
            next_steps=[
                "Use `untrusted`, `on-request`, or `never`.",
            ],
            debug_detail=f"supported={', '.join(SUPPORTED_APPROVAL_MODES)}",
        )
    return mode


def validate_cli_runtime_requirements() -> config.StartupConfig:
    cfg = init_cli_config(init_logging=False)
    issues = collect_runtime_issues(cfg)
    if issues["errors"]:
        detail = "\n".join(f"- {item}" for item in issues["errors"])
        raise CLIError(
            f"CLI runtime is not ready:\n{detail}",
            next_steps=issues["next_steps"],
        )
    return cfg

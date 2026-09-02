from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.desktop_v2.backend.package import (
    DESKTOP_COMPONENT_DEFAULTS as _DESKTOP_COMPONENT_DEFAULTS,
    stable_component_id as _stable_component_id,
)
from app.desktop_v2.backend.run_context import _virtual_workspace_root
from app.desktop_v2.backend.schemas import DesktopV2Settings
from sagents.v2.runtime.execution.sandbox import FileSystemMode
from sagents.v2.tool import ToolSelectionConfig


_TOOL_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_SKILL_NAME = re.compile(r"^[^\\/\x00]{1,192}$")
_AGENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,191}$")

_PLAN_BLOCKED_TOOLS = frozenset(
    {
        "apply_patch",
        "await_shell",
        "execute_shell_command",
        "file_update",
        "file_write",
        "kill_shell",
    }
)
_REASONING_DISABLE_EXTRAS: dict[str, dict[str, Any]] = {
    "omit": {},
    "reasoning_effort_none": {"reasoning_effort": "none"},
    "thinking_type_disabled": {"thinking": {"type": "disabled"}},
    "enable_thinking_false": {"enable_thinking": False},
    "thinking_false": {"thinking": False},
    "chat_template_enable_thinking_false": {
        "chat_template_kwargs": {"enable_thinking": False}
    },
}
def _agent_memory_enabled(
    agent: Any, memory_plugin_id: str, session_memory_plugin_id: str
) -> bool:
    """Use Tool assignment as the per-Agent Memory feature switch."""

    has_provider = (
        memory_plugin_id != "sage.memory.noop"
        or session_memory_plugin_id != "sage.session-memory.noop"
    )
    return has_provider and "search_memory" in set(
        agent.config.get("availableTools") or ()
    )


_CONTINUATION_COMPONENT_CHOICES = (
    "sage.agent.continuation.explicit-status",
    "sage.agent.continuation.llm-judge",
    "sage.agent.continuation.deterministic",
)


def _continuation_component_config(plugin_id: str) -> dict[str, Any]:
    shared = {
        "repeat_threshold": 3,
        "status_source": "turn_status",
        "explicit_statuses": [
            "task_done",
            "need_user_input",
            "blocked",
            "continue_work",
            "failed",
        ],
        "flow_boundaries": ["complete_node", "continue_node"],
        "uses_finish_reason": False,
    }
    if plugin_id == "sage.agent.continuation.llm-judge":
        return {
            **shared,
            "mode": "llm_judge",
            "model_binding": "fast",
            "prompt_contract": "v1",
            "decisions": [
                "continue",
                "completed",
                "need_user_input",
                "blocked",
            ],
            "uses_confidence": False,
            "status_source": "none",
            "explicit_statuses": [],
            "uses_llm_judge": True,
            "timeout_seconds": 6.0,
            "judge_failure": "propagate_error",
        }
    if plugin_id == "sage.agent.continuation.hybrid":
        return {
            **shared,
            "mode": "hybrid",
            "model_binding": "fast",
            "prompt_contract": "v1",
            "uses_confidence": False,
            "uses_llm_judge": True,
            "judge_failure": "deterministic_fallback",
        }
    if plugin_id == "sage.agent.continuation.explicit-status":
        return {
            **shared,
            "mode": "explicit_status",
            "requires_explicit_status": True,
            "uses_llm_judge": False,
        }
    return {
        **shared,
        "mode": "deterministic",
        "completion_reason": "text.final",
        "uses_llm_judge": False,
    }


def _tool_selection_component_config(
    plugin_id: str, raw_config: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Normalize official configs while preserving plugin-defined parameters."""

    if plugin_id == "sage.tool-selection.direct":
        return {}
    if plugin_id in {
        "sage.tool-selection.llm",
        "sage.tool-selection.lexical",
        "sage.tool-selection.recent",
    }:
        return ToolSelectionConfig.model_validate(raw_config or {}).model_dump(
            mode="json"
        )
    return dict(raw_config or {})


def _continuation_agent_instructions(plugin_id: str) -> str:
    if plugin_id == "sage.agent.continuation.explicit-status":
        return (
            "\n\nRuntime completion policy: explicit turn status is required. "
            "Before ending every response, call turn_status with task_done, "
            "continue_work, need_user_input, blocked, or failed. Ordinary final "
            "text without turn_status does not finish the Run."
        )
    return ""


_SANDBOX_DEFAULTS = {
    "sage.sandbox.local-workspace": {
        "workspace_root": "/workspace",
        "workspace_path_mode": "virtual",
        "workspace_mapping": "active_workspace",
        "filesystem_mode": "workspace",
    },
    "sage.sandbox.ephemeral": {
        "workspace_root": "/workspace",
        "workspace_path_mode": "virtual",
        "workspace_mapping": "isolated",
        "filesystem_mode": "workspace",
    },
}


def _resolved_sandbox_config(
    settings: DesktopV2Settings,
) -> tuple[str, dict[str, Any]]:
    plugin_id = _stable_component_id(
        "execution.sandbox",
        settings.component_selections.get(
            "execution.sandbox",
            _DESKTOP_COMPONENT_DEFAULTS["execution.sandbox"],
        ),
    )
    config = dict(_SANDBOX_DEFAULTS.get(plugin_id, {}))
    config.update(settings.component_configs.get("execution.sandbox", {}))
    config["workspace_root"] = _virtual_workspace_root(config.get("workspace_root"))
    path_mode = str(config.get("workspace_path_mode", "virtual"))
    if path_mode not in {"virtual", "host"}:
        raise ValueError("sandbox workspace_path_mode must be virtual or host")
    mapping = str(config.get("workspace_mapping", "isolated"))
    if mapping not in {"active_workspace", "isolated"}:
        raise ValueError(
            "sandbox workspace_mapping must be active_workspace or isolated"
        )
    if plugin_id == "sage.sandbox.local-workspace" and mapping != "active_workspace":
        raise ValueError("local-workspace sandbox requires active_workspace mapping")
    if plugin_id == "sage.sandbox.ephemeral" and mapping != "isolated":
        raise ValueError("ephemeral sandbox cannot map the active workspace")
    if mapping == "isolated" and path_mode != "virtual":
        raise ValueError("isolated sandbox requires a fixed virtual workspace path")
    config["workspace_path_mode"] = path_mode
    config["workspace_mapping"] = mapping
    try:
        config["filesystem_mode"] = FileSystemMode(
            str(config.get("filesystem_mode", "workspace"))
        ).value
    except ValueError as exc:
        raise ValueError("sandbox filesystem_mode is invalid") from exc
    return plugin_id, config


def _sandbox_workspace_root(
    config: dict[str, Any], host_workspace: Path | None = None
) -> str:
    if config.get("workspace_path_mode") != "host":
        return str(config["workspace_root"])
    if config.get("workspace_mapping") != "active_workspace":
        raise ValueError("host workspace path mode requires active workspace mapping")
    if host_workspace is None:
        raise ValueError("host workspace path mode requires the active workspace")
    return _virtual_workspace_root(host_workspace.expanduser().resolve().as_posix())

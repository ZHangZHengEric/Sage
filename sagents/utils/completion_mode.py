"""Completion-mode selection for SimpleAgent style execution.

The new primary configuration is ``SAGE_TASK_COMPLETION_MODE``.  Older boolean
environment variables are still accepted as compatibility fallbacks when the new
enum is not set.
"""

from __future__ import annotations

import os
from enum import Enum

from sagents.utils.logger import logger


class TaskCompletionMode(str, Enum):
    TURN_STATUS = "turn_status"
    LLM_JUDGE = "llm_judge"
    NO_TOOL_CALL = "no_tool_call"


_MODE_ALIASES = {
    "turn_status": TaskCompletionMode.TURN_STATUS,
    "status": TaskCompletionMode.TURN_STATUS,
    "status_protocol": TaskCompletionMode.TURN_STATUS,
    "protocol": TaskCompletionMode.TURN_STATUS,
    "llm_judge": TaskCompletionMode.LLM_JUDGE,
    "judge": TaskCompletionMode.LLM_JUDGE,
    "legacy": TaskCompletionMode.LLM_JUDGE,
    "no_tool_call": TaskCompletionMode.NO_TOOL_CALL,
    "no_tool": TaskCompletionMode.NO_TOOL_CALL,
    "no_tools": TaskCompletionMode.NO_TOOL_CALL,
    "text_final": TaskCompletionMode.NO_TOOL_CALL,
}


def _env_true(name: str) -> bool:
    return os.environ.get(name, "false").strip().lower() == "true"


def _env_false(name: str) -> bool:
    return os.environ.get(name, "true").strip().lower() == "false"


def get_task_completion_mode() -> TaskCompletionMode:
    """Return the active task completion mode.

    Precedence:
    1. ``SAGE_TASK_COMPLETION_MODE`` enum when set.
    2. Back-compat fallback: ``SAGE_COMPLETE_ON_NO_TOOL_CALL=true``.
    3. Back-compat fallback: ``SAGE_AGENT_STATUS_PROTOCOL_ENABLED=false``.
    4. Default ``turn_status`` protocol.
    """

    raw_mode = os.environ.get("SAGE_TASK_COMPLETION_MODE")
    if raw_mode is not None:
        mode = _MODE_ALIASES.get(raw_mode.strip().lower())
        if mode is not None:
            return mode
        logger.warning(
            "Invalid SAGE_TASK_COMPLETION_MODE=%r; falling back to legacy envs/default",
            raw_mode,
        )

    if _env_true("SAGE_COMPLETE_ON_NO_TOOL_CALL"):
        return TaskCompletionMode.NO_TOOL_CALL
    if _env_false("SAGE_AGENT_STATUS_PROTOCOL_ENABLED"):
        return TaskCompletionMode.LLM_JUDGE
    return TaskCompletionMode.TURN_STATUS


def is_turn_status_mode() -> bool:
    return get_task_completion_mode() == TaskCompletionMode.TURN_STATUS


def is_llm_judge_mode() -> bool:
    return get_task_completion_mode() == TaskCompletionMode.LLM_JUDGE


def is_no_tool_call_mode() -> bool:
    return get_task_completion_mode() == TaskCompletionMode.NO_TOOL_CALL

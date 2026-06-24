"""Completion-mode selection for SimpleAgent style execution."""

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


def get_task_completion_mode() -> TaskCompletionMode:
    """Return the active task completion mode.

    Precedence:
    1. ``SAGE_TASK_COMPLETION_MODE`` enum when valid.
    2. Default ``turn_status`` protocol.
    """

    raw_mode = os.environ.get("SAGE_TASK_COMPLETION_MODE")
    if raw_mode is not None:
        mode = _MODE_ALIASES.get(raw_mode.strip().lower())
        if mode is not None:
            return mode
        logger.warning(
            "Invalid SAGE_TASK_COMPLETION_MODE=%r; falling back to default",
            raw_mode,
        )

    return TaskCompletionMode.TURN_STATUS


def is_turn_status_mode() -> bool:
    return get_task_completion_mode() == TaskCompletionMode.TURN_STATUS


def is_llm_judge_mode() -> bool:
    return get_task_completion_mode() == TaskCompletionMode.LLM_JUDGE


def is_no_tool_call_mode() -> bool:
    return get_task_completion_mode() == TaskCompletionMode.NO_TOOL_CALL

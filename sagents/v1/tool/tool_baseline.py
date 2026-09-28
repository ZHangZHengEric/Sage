"""Shared baseline tool selection helpers."""

from __future__ import annotations

from typing import Iterable, List, Set


BASELINE_EXECUTION_TOOLS = (
    "todo_write",
    "todo_read",
    "search_memory",
    "turn_status",
    "file_read",
    "file_write",
    "file_update",
    "glob",
    "list_dir",
    "execute_shell_command",
    "await_shell",
    "kill_shell",
)


def augment_with_baseline_tools(
    suggested_tools: Iterable[str],
    available_tool_names: Iterable[str],
) -> List[str]:
    """Return suggested tools plus baseline execution tools that actually exist."""

    available: Set[str] = {name for name in available_tool_names if name}
    selected: List[str] = []
    seen: Set[str] = set()

    for name in list(suggested_tools or []) + list(BASELINE_EXECUTION_TOOLS):
        if not name or name in seen or name not in available:
            continue
        selected.append(name)
        seen.add(name)

    return selected

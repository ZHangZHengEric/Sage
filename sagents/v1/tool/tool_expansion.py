"""Shared helpers for runtime tool expansion."""

from __future__ import annotations

from typing import Iterable, List, Set


TOOL_EXPAND_TOOLS = "tool_expand_tools"


def should_expose_tool_expansion(
    suggested_tools: Iterable[str],
    selected_tool_names: Iterable[str],
    allowed_tool_names: Iterable[str],
) -> bool:
    """Return whether the expansion tool should be exposed to the model.

    Expansion only makes sense when the execution layer narrowed the current
    request tools below the agent's allowed tool boundary.
    """

    suggested: List[str] = [name for name in (suggested_tools or []) if name]
    if not suggested:
        return False

    allowed: Set[str] = {name for name in (allowed_tool_names or []) if name}
    if TOOL_EXPAND_TOOLS not in allowed:
        return False

    selected: Set[str] = {name for name in (selected_tool_names or []) if name}
    allowed_actions = allowed - {TOOL_EXPAND_TOOLS}
    selected_actions = selected - {TOOL_EXPAND_TOOLS}
    return len(selected_actions) < len(allowed_actions)

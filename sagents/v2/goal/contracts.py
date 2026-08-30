"""Typed goal-mode state derived from canonical Run events."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from sagents.v2.contracts.common import Identifier, StrictModel


class GoalState(StrictModel):
    """The single goal submitted by a Plan or Goal Run."""

    content: str = Field(min_length=1)
    created_tool_call_id: Identifier
    source: Literal["direct", "plan"] = "direct"
    completed: bool = False
    completion_summary: str | None = None
    completed_tool_call_id: Identifier | None = None

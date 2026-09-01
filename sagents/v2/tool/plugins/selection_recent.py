"""Official Tool-selection plugin: prefer recently called Tools."""

from __future__ import annotations

from sagents.v2.tool.selection import (
    BaseToolSelectionPolicy,
    ToolSelectionRequest,
    ToolSelectionResult,
    _recent_tool_names,
)


class RecentToolSelectionPolicy(BaseToolSelectionPolicy):
    """Put recently called Tools first, then fill the remaining count."""

    plugin_id = "sage.tool-selection.recent"

    def select(self, request: ToolSelectionRequest) -> ToolSelectionResult:
        self._remember_catalog(request.run_id, request.tools)
        selected = self._bounded(
            request,
            _recent_tool_names(request.messages),
            preferred_first=True,
        )
        return self._result(request, selected, "recent")

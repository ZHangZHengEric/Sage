"""Official Tool-selection plugin: expose every policy-allowed Tool."""

from __future__ import annotations

from sagents.v2.tool.selection import (
    BaseToolSelectionPolicy,
    ToolSelectionRequest,
    ToolSelectionResult,
)


class DirectToolSelectionPolicy(BaseToolSelectionPolicy):
    """Expose every policy-allowed Tool; the count limit is not applicable."""

    plugin_id = "sage.tool-selection.direct"

    def __init__(self, config: dict | None = None) -> None:
        super().__init__({})

    def select(self, request: ToolSelectionRequest) -> ToolSelectionResult:
        self._remember_catalog(request.run_id, request.tools)
        return self._result(request, request.tools, "direct")

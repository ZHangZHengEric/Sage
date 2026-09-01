"""Official Tool-selection plugin: local BM25-style ranking."""

from __future__ import annotations

from sagents.v2.tool.selection import (
    BaseToolSelectionPolicy,
    ToolSelectionRequest,
    ToolSelectionResult,
    _bm25_ranked_names,
    _recent_text,
)


class LexicalToolSelectionPolicy(BaseToolSelectionPolicy):
    """Local BM25-style ranking over Tool names, descriptions, and schemas."""

    plugin_id = "sage.tool-selection.lexical"

    def select(self, request: ToolSelectionRequest) -> ToolSelectionResult:
        self._remember_catalog(request.run_id, request.tools)
        selected = self._bounded(
            request, _bm25_ranked_names(request.tools, _recent_text(request.messages))
        )
        return self._result(request, selected, "lexical.bm25")

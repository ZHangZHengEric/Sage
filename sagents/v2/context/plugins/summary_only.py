"""Persistent history summaries without tool-result reference projection."""

from __future__ import annotations

from sagents.v2.context.plugins._shared.persistent_summary import PersistentSummaryReducerBase


class SummaryOnlyContextReducer(PersistentSummaryReducerBase):
    plugin_id = "sage.context.reducer.summary-only"
    name = "Summary-only context reducer"
    description = "Persists history summaries under context pressure without replacing tool results with references."

    async def reduce(self, messages, budget=None, *, scope=None):
        if scope is not None:
            scope = scope.model_copy(update={"allow_reference_compaction": False})
        return await super().reduce(messages, budget, scope=scope)

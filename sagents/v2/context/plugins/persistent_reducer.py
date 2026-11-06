"""Persistent summaries with optional history reference compaction."""

from sagents.v2.context.plugins._shared.persistent_summary import PersistentSummaryReducerBase


class PersistentSummaryContextReducer(PersistentSummaryReducerBase):
    plugin_id = "sage.context.reducer.persistent-summary"
    name = "Persistent summary context reducer"
    description = "Summarizes complete history only after API rejection or reported usage reaches a configured limit."

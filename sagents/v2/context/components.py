"""Host-injected component bundle used by the standard composition root."""

from __future__ import annotations

from dataclasses import dataclass, field

from sagents.v2.context import (
    ConversationSummarizer,
    ConversationSummaryStore,
    ExtractiveConversationSummarizer,
    InMemoryConversationSummaryStore,
    JsonHeuristicTokenEstimator,
    PersistentSummaryContextReducer,
    ContextReducer,
    TokenEstimator,
    WindowContextReducer,
)


@dataclass
class ContextComponentBundle:
    """Replaceable context components shared across all loops in one host.

    A host should keep one bundle for its process/tenant lifecycle.  In-memory
    defaults are safe for embedded use; production hosts normally inject a
    durable `ConversationSummaryStore` and a model-backed summarizer.
    """

    token_estimator: TokenEstimator = field(default_factory=JsonHeuristicTokenEstimator)
    summary_store: ConversationSummaryStore = field(
        default_factory=InMemoryConversationSummaryStore
    )
    summarizer: ConversationSummarizer = field(
        default_factory=ExtractiveConversationSummarizer
    )
    summary_target_tokens: int = 1_024
    protected_recent_units: int = 4
    max_summary_source_tokens: int = 24_000
    reducer_id: str = "persistent-summary"
    reducer: ContextReducer | None = None

    def create_reducer(self):
        """Create the selected reducer while sharing its host-owned components."""

        if self.reducer is not None:
            return self.reducer

        if self.reducer_id == "window":
            return WindowContextReducer(self.token_estimator)
        if self.reducer_id != "persistent-summary":
            raise ValueError(f"unknown context reducer {self.reducer_id!r}")

        return PersistentSummaryContextReducer(
            self.summary_store,
            summarizer=self.summarizer,
            estimator=self.token_estimator,
            summary_target_tokens=self.summary_target_tokens,
            protected_recent_units=self.protected_recent_units,
            max_summary_source_tokens=self.max_summary_source_tokens,
        )

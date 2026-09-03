"""Context contracts and lazily loaded implementations."""

from sagents.v2._lazy import exported_names, resolve_export


_EXPORTS = {
    "CallableTokenEstimator": (
        "sagents.v2.context.token_estimator",
        "CallableTokenEstimator",
    ),
    "ContextAssembler": ("sagents.v2.context.assembler", "ContextAssembler"),
    "ContextBudget": ("sagents.v2.context.contracts", "ContextBudget"),
    "ContextPlacement": ("sagents.v2.context.contracts", "ContextPlacement"),
    "ContextProjection": ("sagents.v2.context.contracts", "ContextProjection"),
    "ContextProjectionObserver": (
        "sagents.v2.context.contracts",
        "ContextProjectionObserver",
    ),
    "ContextReducer": ("sagents.v2.context.contracts", "ContextReducer"),
    "ContextReductionScope": ("sagents.v2.context.contracts", "ContextReductionScope"),
    "ContextRequestReservation": (
        "sagents.v2.context.contracts",
        "ContextRequestReservation",
    ),
    "ContextSegment": ("sagents.v2.context.contracts", "ContextSegment"),
    "ContextSegmentProvider": (
        "sagents.v2.context.contracts",
        "ContextSegmentProvider",
    ),
    "ContextStability": ("sagents.v2.context.contracts", "ContextStability"),
    "ContextUnitCompactor": ("sagents.v2.context.contracts", "ContextUnitCompactor"),
    "ConversationSummarizer": ("sagents.v2.context.summary", "ConversationSummarizer"),
    "ConversationSummary": ("sagents.v2.context.summary", "ConversationSummary"),
    "ConversationSummaryStore": (
        "sagents.v2.context.summary",
        "ConversationSummaryStore",
    ),
    "DefaultContextAssembler": (
        "sagents.v2.context.assembler",
        "DefaultContextAssembler",
    ),
    "ExtractiveConversationSummarizer": (
        "sagents.v2.context.plugins.summarizer_extractive",
        "ExtractiveConversationSummarizer",
    ),
    "HeuristicTokenEstimator": ("sagents.v2.context.budget", "HeuristicTokenEstimator"),
    "InMemoryConversationSummaryStore": (
        "sagents.v2.context.plugins.summary_ephemeral",
        "InMemoryConversationSummaryStore",
    ),
    "JsonHeuristicTokenEstimator": (
        "sagents.v2.context.plugins.estimator_json",
        "JsonHeuristicTokenEstimator",
    ),
    "ModelConversationSummarizer": (
        "sagents.v2.context.plugins.summarizer_model",
        "ModelConversationSummarizer",
    ),
    "PersistentSummaryContextReducer": (
        "sagents.v2.context.plugins.persistent_reducer",
        "PersistentSummaryContextReducer",
    ),
    "ReferenceContextUnitCompactor": (
        "sagents.v2.context.plugins.reference",
        "ReferenceContextUnitCompactor",
    ),
    "RunMetadataContextProvider": (
        "sagents.v2.context.runtime_metadata",
        "RunMetadataContextProvider",
    ),
    "SessionDerivedConversationSummaryStore": (
        "sagents.v2.context.plugins.summary_session",
        "SessionDerivedConversationSummaryStore",
    ),
    "SessionEventModelProjector": (
        "sagents.v2.context.session_history",
        "SessionEventModelProjector",
    ),
    "SessionHistoryLedgerBuilder": (
        "sagents.v2.context.session_history",
        "SessionHistoryLedgerBuilder",
    ),
    "SessionHistoryReader": (
        "sagents.v2.context.session_history",
        "SessionHistoryReader",
    ),
    "StaticContextProvider": ("sagents.v2.context.assembler", "StaticContextProvider"),
    "SummarizationRequest": ("sagents.v2.context.summary", "SummarizationRequest"),
    "TiktokenTokenEstimator": (
        "sagents.v2.context.plugins.estimator_tiktoken",
        "TiktokenTokenEstimator",
    ),
    "TokenEstimator": ("sagents.v2.context.token_estimator", "TokenEstimator"),
    "UnicodeHeuristicTokenEstimator": (
        "sagents.v2.context.plugins.estimator_unicode",
        "UnicodeHeuristicTokenEstimator",
    ),
    "WindowContextReducer": (
        "sagents.v2.context.plugins.window",
        "WindowContextReducer",
    ),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    return resolve_export(name, _EXPORTS, globals())


def __dir__() -> list[str]:
    return exported_names(_EXPORTS, globals())

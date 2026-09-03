"""Official context plugins, exposed without eager sibling imports."""

from sagents.v2._lazy import exported_names, resolve_export


_EXPORTS = {
    "ExtractiveConversationSummarizer": (
        "sagents.v2.context.plugins.summarizer_extractive",
        "ExtractiveConversationSummarizer",
    ),
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
    "SessionDerivedConversationSummaryStore": (
        "sagents.v2.context.plugins.summary_session",
        "SessionDerivedConversationSummaryStore",
    ),
    "TiktokenTokenEstimator": (
        "sagents.v2.context.plugins.estimator_tiktoken",
        "TiktokenTokenEstimator",
    ),
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

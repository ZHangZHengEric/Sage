"""Official context plugins, exposed without eager sibling imports."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sagents.v2.context.plugins.summarizer_extractive import ExtractiveConversationSummarizer as ExtractiveConversationSummarizer
    from sagents.v2.context.plugins.summary_ephemeral import InMemoryConversationSummaryStore as InMemoryConversationSummaryStore
    from sagents.v2.context.plugins.summarizer_model import ModelConversationSummarizer as ModelConversationSummarizer
    from sagents.v2.context.plugins.persistent_reducer import PersistentSummaryContextReducer as PersistentSummaryContextReducer
    from sagents.v2.context.plugins.summary_session import SessionDerivedConversationSummaryStore as SessionDerivedConversationSummaryStore
    from sagents.v2.context.plugins.window import WindowContextReducer as WindowContextReducer


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
    "ModelConversationSummarizer": (
        "sagents.v2.context.plugins.summarizer_model",
        "ModelConversationSummarizer",
    ),
    "PersistentSummaryContextReducer": (
        "sagents.v2.context.plugins.persistent_reducer",
        "PersistentSummaryContextReducer",
    ),
    "SessionDerivedConversationSummaryStore": (
        "sagents.v2.context.plugins.summary_session",
        "SessionDerivedConversationSummaryStore",
    ),
    "WindowContextReducer": (
        "sagents.v2.context.plugins.window",
        "WindowContextReducer",
    ),
}

__all__ = [
    "ExtractiveConversationSummarizer",
    "InMemoryConversationSummaryStore",
    "ModelConversationSummarizer",
    "PersistentSummaryContextReducer",
    "SessionDerivedConversationSummaryStore",
    "WindowContextReducer",
]


def __getattr__(name: str):
    return resolve_export(name, _EXPORTS, globals())


def __dir__() -> list[str]:
    return exported_names(_EXPORTS, globals())

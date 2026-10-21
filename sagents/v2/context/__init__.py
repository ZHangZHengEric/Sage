"""Context contracts and lazily loaded implementations."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sagents.v2.context.assembler import ContextAssembler as ContextAssembler
    from sagents.v2.context.contracts import ContextBudget as ContextBudget
    from sagents.v2.context.contracts import ContextPlacement as ContextPlacement
    from sagents.v2.context.contracts import ContextProjection as ContextProjection
    from sagents.v2.context.contracts import ContextProjectionObserver as ContextProjectionObserver
    from sagents.v2.context.contracts import ContextReducer as ContextReducer
    from sagents.v2.context.contracts import ContextReductionScope as ContextReductionScope
    from sagents.v2.context.contracts import ContextRequestReservation as ContextRequestReservation
    from sagents.v2.context.contracts import ContextSegment as ContextSegment
    from sagents.v2.context.contracts import ContextSegmentProvider as ContextSegmentProvider
    from sagents.v2.context.contracts import ContextStability as ContextStability
    from sagents.v2.context.summary import ConversationSummarizer as ConversationSummarizer
    from sagents.v2.context.summary import ConversationSummary as ConversationSummary
    from sagents.v2.context.summary import ConversationSummaryStore as ConversationSummaryStore
    from sagents.v2.context.assembler import DefaultContextAssembler as DefaultContextAssembler
    from sagents.v2.context.plugins.summarizer_extractive import ExtractiveConversationSummarizer as ExtractiveConversationSummarizer
    from sagents.v2.context.plugins.summary_ephemeral import InMemoryConversationSummaryStore as InMemoryConversationSummaryStore
    from sagents.v2.context.plugins.summarizer_model import ModelConversationSummarizer as ModelConversationSummarizer
    from sagents.v2.context.plugins.persistent_reducer import PersistentSummaryContextReducer as PersistentSummaryContextReducer
    from sagents.v2.context.runtime_metadata import RunMetadataContextProvider as RunMetadataContextProvider
    from sagents.v2.context.plugins.summary_session import SessionDerivedConversationSummaryStore as SessionDerivedConversationSummaryStore
    from sagents.v2.context.session_history import SessionEventModelProjector as SessionEventModelProjector
    from sagents.v2.context.session_history import SessionHistoryLedgerBuilder as SessionHistoryLedgerBuilder
    from sagents.v2.context.session_history import SessionHistoryReader as SessionHistoryReader
    from sagents.v2.context.assembler import StaticContextProvider as StaticContextProvider
    from sagents.v2.context.summary import SummarizationRequest as SummarizationRequest
    from sagents.v2.context.plugins.window import WindowContextReducer as WindowContextReducer


from sagents.v2._lazy import exported_names, resolve_export


_EXPORTS = {
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
    "WindowContextReducer": (
        "sagents.v2.context.plugins.window",
        "WindowContextReducer",
    ),
}

__all__ = [
    "ContextAssembler",
    "ContextBudget",
    "ContextPlacement",
    "ContextProjection",
    "ContextProjectionObserver",
    "ContextReducer",
    "ContextReductionScope",
    "ContextRequestReservation",
    "ContextSegment",
    "ContextSegmentProvider",
    "ContextStability",
    "ConversationSummarizer",
    "ConversationSummary",
    "ConversationSummaryStore",
    "DefaultContextAssembler",
    "ExtractiveConversationSummarizer",
    "InMemoryConversationSummaryStore",
    "ModelConversationSummarizer",
    "PersistentSummaryContextReducer",
    "RunMetadataContextProvider",
    "SessionDerivedConversationSummaryStore",
    "SessionEventModelProjector",
    "SessionHistoryLedgerBuilder",
    "SessionHistoryReader",
    "StaticContextProvider",
    "SummarizationRequest",
    "WindowContextReducer",
]


def __getattr__(name: str):
    return resolve_export(name, _EXPORTS, globals())


def __dir__() -> list[str]:
    return exported_names(_EXPORTS, globals())

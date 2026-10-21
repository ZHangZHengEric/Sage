"""Independent long-term Memory contracts and lazy implementations."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sagents.v2.memory.service import CanonicalMessageMemoryExtractor as CanonicalMessageMemoryExtractor
    from sagents.v2.memory.service import CompletedRunMemoryPolicy as CompletedRunMemoryPolicy
    from sagents.v2.memory.plugins.recall_direct import DirectMemoryRecallQueryGenerator as DirectMemoryRecallQueryGenerator
    from sagents.v2.memory.plugins.filesystem_bm25 import FilesystemBm25MemoryProvider as FilesystemBm25MemoryProvider
    from sagents.v2.memory.plugins.recall_llm import LLMMemoryRecallQueryGenerator as LLMMemoryRecallQueryGenerator
    from sagents.v2.memory.contracts import MemoryCapabilities as MemoryCapabilities
    from sagents.v2.memory.context import MemoryContextSource as MemoryContextSource
    from sagents.v2.memory.contracts import MemoryDeleteResult as MemoryDeleteResult
    from sagents.v2.memory.service import MemoryExtractor as MemoryExtractor
    from sagents.v2.memory.contracts import MemoryHit as MemoryHit
    from sagents.v2.memory.service import MemoryIngestionPolicy as MemoryIngestionPolicy
    from sagents.v2.memory.contracts import MemoryProvider as MemoryProvider
    from sagents.v2.memory.contracts import MemoryQuery as MemoryQuery
    from sagents.v2.memory.query import MemoryRecallQueryGenerator as MemoryRecallQueryGenerator
    from sagents.v2.memory.contracts import MemoryRecord as MemoryRecord
    from sagents.v2.memory.contracts import MemoryScope as MemoryScope
    from sagents.v2.memory.service import MemoryService as MemoryService
    from sagents.v2.memory.contracts import MemoryWriteResult as MemoryWriteResult
    from sagents.v2.memory.plugins.noop import NoopMemoryProvider as NoopMemoryProvider


from sagents.v2._lazy import exported_names, resolve_export


_EXPORTS = {
    "CanonicalMessageMemoryExtractor": (
        "sagents.v2.memory.service",
        "CanonicalMessageMemoryExtractor",
    ),
    "CompletedRunMemoryPolicy": (
        "sagents.v2.memory.service",
        "CompletedRunMemoryPolicy",
    ),
    "DirectMemoryRecallQueryGenerator": (
        "sagents.v2.memory.plugins.recall_direct",
        "DirectMemoryRecallQueryGenerator",
    ),
    "FilesystemBm25MemoryProvider": (
        "sagents.v2.memory.plugins.filesystem_bm25",
        "FilesystemBm25MemoryProvider",
    ),
    "LLMMemoryRecallQueryGenerator": (
        "sagents.v2.memory.plugins.recall_llm",
        "LLMMemoryRecallQueryGenerator",
    ),
    "MemoryCapabilities": ("sagents.v2.memory.contracts", "MemoryCapabilities"),
    "MemoryContextSource": ("sagents.v2.memory.context", "MemoryContextSource"),
    "MemoryDeleteResult": ("sagents.v2.memory.contracts", "MemoryDeleteResult"),
    "MemoryExtractor": ("sagents.v2.memory.service", "MemoryExtractor"),
    "MemoryHit": ("sagents.v2.memory.contracts", "MemoryHit"),
    "MemoryIngestionPolicy": ("sagents.v2.memory.service", "MemoryIngestionPolicy"),
    "MemoryProvider": ("sagents.v2.memory.contracts", "MemoryProvider"),
    "MemoryQuery": ("sagents.v2.memory.contracts", "MemoryQuery"),
    "MemoryRecallQueryGenerator": (
        "sagents.v2.memory.query",
        "MemoryRecallQueryGenerator",
    ),
    "MemoryRecord": ("sagents.v2.memory.contracts", "MemoryRecord"),
    "MemoryScope": ("sagents.v2.memory.contracts", "MemoryScope"),
    "MemoryService": ("sagents.v2.memory.service", "MemoryService"),
    "MemoryWriteResult": ("sagents.v2.memory.contracts", "MemoryWriteResult"),
    "NoopMemoryProvider": ("sagents.v2.memory.plugins.noop", "NoopMemoryProvider"),
}

__all__ = [
    "CanonicalMessageMemoryExtractor",
    "CompletedRunMemoryPolicy",
    "DirectMemoryRecallQueryGenerator",
    "FilesystemBm25MemoryProvider",
    "LLMMemoryRecallQueryGenerator",
    "MemoryCapabilities",
    "MemoryContextSource",
    "MemoryDeleteResult",
    "MemoryExtractor",
    "MemoryHit",
    "MemoryIngestionPolicy",
    "MemoryProvider",
    "MemoryQuery",
    "MemoryRecallQueryGenerator",
    "MemoryRecord",
    "MemoryScope",
    "MemoryService",
    "MemoryWriteResult",
    "NoopMemoryProvider",
]


def __getattr__(name: str):
    return resolve_export(name, _EXPORTS, globals())


def __dir__() -> list[str]:
    return exported_names(_EXPORTS, globals())

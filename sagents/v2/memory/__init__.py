"""Independent long-term Memory component for SAgents v2."""

from sagents.v2.memory.context import MemoryContextSource
from sagents.v2.memory.query import (
    DirectMemoryRecallQueryGenerator,
    LLMMemoryRecallQueryGenerator,
    MemoryRecallQueryGenerator,
)
from sagents.v2.memory.contracts import (
    MemoryCapabilities,
    MemoryDeleteResult,
    MemoryHit,
    MemoryProvider,
    MemoryQuery,
    MemoryRecord,
    MemoryScope,
    MemoryWriteResult,
)
from sagents.v2.memory.plugins.noop import NoopMemoryProvider
from sagents.v2.memory.plugins.filesystem_bm25 import FilesystemBm25MemoryProvider
from sagents.v2.memory.service import (
    CanonicalMessageMemoryExtractor,
    CompletedRunMemoryPolicy,
    MemoryExtractor,
    MemoryIngestionPolicy,
    MemoryService,
)

__all__ = [
    "CanonicalMessageMemoryExtractor",
    "CompletedRunMemoryPolicy",
    "FilesystemBm25MemoryProvider",
    "MemoryCapabilities",
    "MemoryContextSource",
    "MemoryRecallQueryGenerator",
    "DirectMemoryRecallQueryGenerator",
    "LLMMemoryRecallQueryGenerator",
    "MemoryDeleteResult",
    "MemoryExtractor",
    "MemoryHit",
    "MemoryIngestionPolicy",
    "MemoryProvider",
    "MemoryQuery",
    "MemoryRecord",
    "MemoryScope",
    "MemoryService",
    "MemoryWriteResult",
    "NoopMemoryProvider",
]

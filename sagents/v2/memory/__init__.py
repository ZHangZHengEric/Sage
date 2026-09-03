"""Independent long-term Memory contracts and lazy implementations."""

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

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    return resolve_export(name, _EXPORTS, globals())


def __dir__() -> list[str]:
    return exported_names(_EXPORTS, globals())

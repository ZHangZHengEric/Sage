"""Official Memory plugins, exposed without eager sibling imports."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sagents.v2.memory.plugins.recall_direct import DirectMemoryRecallQueryGenerator as DirectMemoryRecallQueryGenerator
    from sagents.v2.memory.plugins.filesystem_bm25 import FilesystemBm25MemoryProvider as FilesystemBm25MemoryProvider
    from sagents.v2.memory.plugins.recall_llm import LLMMemoryRecallQueryGenerator as LLMMemoryRecallQueryGenerator
    from sagents.v2.memory.plugins.noop import NoopMemoryProvider as NoopMemoryProvider


from sagents.v2._lazy import exported_names, resolve_export


_EXPORTS = {
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
    "NoopMemoryProvider": ("sagents.v2.memory.plugins.noop", "NoopMemoryProvider"),
}

__all__ = [
    "DirectMemoryRecallQueryGenerator",
    "FilesystemBm25MemoryProvider",
    "LLMMemoryRecallQueryGenerator",
    "NoopMemoryProvider",
]


def __getattr__(name: str):
    return resolve_export(name, _EXPORTS, globals())


def __dir__() -> list[str]:
    return exported_names(_EXPORTS, globals())

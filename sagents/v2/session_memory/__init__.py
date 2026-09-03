"""Searchable, derived Session history separate from long-term Memory."""

from sagents.v2._lazy import exported_names, resolve_export

from sagents.v2.session_memory.contracts import (
    SessionMemoryCapabilities,
    SessionMemoryHit,
    SessionMemoryProvider,
    SessionMemoryQuery,
    SessionMemoryRecord,
)
from sagents.v2.session_memory.service import SessionMemoryService

_LAZY_EXPORTS = {
    "NoopSessionMemoryProvider": (
        "sagents.v2.session_memory.plugins.noop",
        "NoopSessionMemoryProvider",
    ),
    "SqliteBm25SessionMemoryProvider": (
        "sagents.v2.session_memory.plugins.sqlite_bm25",
        "SqliteBm25SessionMemoryProvider",
    ),
}

__all__ = [
    "NoopSessionMemoryProvider",
    "SessionMemoryCapabilities",
    "SessionMemoryHit",
    "SessionMemoryProvider",
    "SessionMemoryQuery",
    "SessionMemoryRecord",
    "SessionMemoryService",
    "SqliteBm25SessionMemoryProvider",
]


def __getattr__(name: str):
    return resolve_export(name, _LAZY_EXPORTS, globals())


def __dir__() -> list[str]:
    return exported_names(_LAZY_EXPORTS, globals())

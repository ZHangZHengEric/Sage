"""Session-memory plugins exposed without eager sibling imports."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sagents.v2.session_memory.plugins.noop import NoopSessionMemoryProvider as NoopSessionMemoryProvider
    from sagents.v2.session_memory.plugins.sqlite_bm25 import SqliteBm25SessionMemoryProvider as SqliteBm25SessionMemoryProvider


from sagents.v2._lazy import exported_names, resolve_export


_EXPORTS = {
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
    "SqliteBm25SessionMemoryProvider",
]


def __getattr__(name: str):
    return resolve_export(name, _EXPORTS, globals())


def __dir__() -> list[str]:
    return exported_names(_EXPORTS, globals())

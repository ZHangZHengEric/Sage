"""Official SessionStore backends exposed without eager sibling imports."""

from sagents.v2._lazy import exported_names, resolve_export


_EXPORTS = {
    "EphemeralSessionStore": (
        "sagents.v2.runtime.session.plugins.ephemeral",
        "EphemeralSessionStore",
    ),
    "FilesystemSessionStore": (
        "sagents.v2.runtime.session.plugins.filesystem",
        "FilesystemSessionStore",
    ),
    "MysqlSessionStore": (
        "sagents.v2.runtime.session.plugins.mysql",
        "MysqlSessionStore",
    ),
    "PostgresSessionStore": (
        "sagents.v2.runtime.session.plugins.postgres",
        "PostgresSessionStore",
    ),
    "SessionStoreCorruptionError": (
        "sagents.v2.runtime.session.plugins.filesystem",
        "SessionStoreCorruptionError",
    ),
    "StoreInUseError": (
        "sagents.v2.runtime.session.plugins.filesystem",
        "StoreInUseError",
    ),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    return resolve_export(name, _EXPORTS, globals())


def __dir__() -> list[str]:
    return exported_names(_EXPORTS, globals())

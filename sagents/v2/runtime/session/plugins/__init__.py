"""Session storage plugins and their shared capability publication interface."""

from sagents.v2._lazy import exported_names, resolve_export


_EXPORTS = {
    "SESSION_STORAGE_CAPABILITIES": (
        "sagents.v2.runtime.session.plugins._shared.storage", "SESSION_STORAGE_CAPABILITIES",
    ),
    "session_storage_providers": (
        "sagents.v2.runtime.session.plugins._shared.storage", "session_storage_providers",
    ),
    "RedisMysqlSessionStore": (
        "sagents.v2.runtime.session.plugins.mysql.redis", "RedisMysqlSessionStore",
    ),
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

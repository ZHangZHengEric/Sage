"""Session storage plugins and their shared capability publication interface."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sagents.v2.runtime.session.plugins._shared.storage import SESSION_STORAGE_CAPABILITIES as SESSION_STORAGE_CAPABILITIES
    from sagents.v2.runtime.session.plugins._shared.storage import session_storage_providers as session_storage_providers
    from sagents.v2.runtime.session.plugins.mysql.redis import RedisMysqlSessionStore as RedisMysqlSessionStore
    from sagents.v2.runtime.session.plugins.ephemeral import EphemeralSessionStore as EphemeralSessionStore
    from sagents.v2.runtime.session.plugins.filesystem import FilesystemSessionStore as FilesystemSessionStore
    from sagents.v2.runtime.session.plugins.mysql import MysqlSessionStore as MysqlSessionStore
    from sagents.v2.runtime.session.plugins.filesystem import SessionStoreCorruptionError as SessionStoreCorruptionError
    from sagents.v2.runtime.session.plugins.filesystem import StoreInUseError as StoreInUseError


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

__all__ = [
    "SESSION_STORAGE_CAPABILITIES",
    "session_storage_providers",
    "RedisMysqlSessionStore",
    "EphemeralSessionStore",
    "FilesystemSessionStore",
    "MysqlSessionStore",
    "SessionStoreCorruptionError",
    "StoreInUseError",
]


def __getattr__(name: str):
    return resolve_export(name, _EXPORTS, globals())


def __dir__() -> list[str]:
    return exported_names(_EXPORTS, globals())

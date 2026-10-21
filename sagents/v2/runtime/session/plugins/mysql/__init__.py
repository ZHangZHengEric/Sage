"""MySQL-backed SessionStore plugins and their private storage implementation.

SQL queries, aggregate caching and the archive shared with Redis stores live
inside this package. Session contracts and shared state rules remain in session.
"""

from .state import (
    _MysqlSessionState,
    SessionStoreCorruptionError,
    parse_mysql_dsn,
)


class _MysqlSessionStoreMeta(type):
    def __getattr__(cls, name):
        return getattr(_MysqlSessionState, name)


class MysqlSessionStore(metaclass=_MysqlSessionStoreMeta):
    """Composed durable MySQL SessionStore facade."""

    plugin_id = "sage.session.mysql"
    name = "MySQL SessionStore"
    description = "Durable per-Session MySQL store with appended Run events. No global Session index."

    def __init__(self, *args, **kwargs):
        object.__setattr__(self, "_coordinator", _MysqlSessionState(*args, **kwargs))

    async def start(self, context, dependencies):
        await self._coordinator._ensure_ready()
        from sagents.v2.runtime.session.plugins import session_storage_providers
        return session_storage_providers(self)

    def __getattr__(self, name):
        return getattr(self._coordinator, name)

    def __setattr__(self, name, value):
        if name == "_coordinator":
            object.__setattr__(self, name, value)
        else:
            setattr(self._coordinator, name, value)


__all__ = ["MysqlSessionStore", "SessionStoreCorruptionError", "parse_mysql_dsn"]

"""Optional PostgreSQL SessionStore with atomic Session CAS and event appends."""

from .._shared.facade import CoordinatorFacade
from .._shared.aggregate import SessionStoreCorruptionError
from .state import _PostgresSessionState, parse_postgres_dsn


class PostgresSessionStore(CoordinatorFacade):
    plugin_id = "sage.session.postgres"
    name = "PostgreSQL SessionStore"
    description = "Durable per-Session PostgreSQL store with appended Run events. Single-process execution."

    def __init__(self, dsn, **kwargs):
        object.__setattr__(self, "_coordinator", _PostgresSessionState(dsn, **kwargs))

    async def start(self, context, dependencies):
        await self._coordinator._ensure_ready()
        from .._shared.storage import session_storage_providers

        return session_storage_providers(self)


__all__ = ["PostgresSessionStore", "SessionStoreCorruptionError", "parse_postgres_dsn"]

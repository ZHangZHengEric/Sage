"""Redis/PostgreSQL SessionStore with the same multi-instance protocol as MySQL."""

from .._shared.facade import CoordinatorFacade
from .._shared.redis_persistence import RedisSessionPersistence
from .._shared.redis_session import RedisSessionCoordination
from .distributed_archive import DistributedPostgresSessionArchive
from .identity import postgres_storage_identity
from .state import _PostgresSessionState


class _RedisPostgresPersistence(RedisSessionPersistence, _PostgresSessionState):
    redis_plugin_id = "sage.session.redis-postgres"
    format_version = "sage.session.redis-postgres/v2"
    archive_backend = "postgres"
    _archive_type = DistributedPostgresSessionArchive
    _archive_identity = staticmethod(postgres_storage_identity)


class _RedisPostgresSessionState(RedisSessionCoordination, _RedisPostgresPersistence):
    pass


class RedisPostgresSessionStore(CoordinatorFacade):
    plugin_id = "sage.session.redis-postgres"
    name = "Redis + PostgreSQL SessionStore"
    description = "Multi-instance Session state, subscriptions and PostgreSQL archival."

    def __init__(self, *args, **kwargs):
        object.__setattr__(
            self, "_coordinator", _RedisPostgresSessionState(*args, **kwargs)
        )

    async def start(self, context, dependencies):
        await self._coordinator._ensure_ready()
        await self._coordinator.list_dispatchable_runs()
        from .._shared.storage import session_storage_providers

        return session_storage_providers(self)

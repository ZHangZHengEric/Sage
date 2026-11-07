"""Redis/MySQL SessionStore for one or multiple Sage instances."""
from .._shared.facade import CoordinatorFacade
from .._shared.redis_session import RedisSessionCoordination
from ._redis_persistence import _RedisMysqlPersistence


class _RedisMysqlSessionState(RedisSessionCoordination, _RedisMysqlPersistence):
    pass


class RedisMysqlSessionStore(CoordinatorFacade):
    plugin_id = "sage.session.redis-mysql"
    name = "Redis + MySQL SessionStore"
    description = "Multi-instance Session state, subscriptions and MySQL archival."

    def __init__(self, *args, **kwargs):
        object.__setattr__(self, "_coordinator", _RedisMysqlSessionState(*args, **kwargs))

    async def start(self, context, dependencies):
        await self._coordinator._ensure_ready()
        await self._coordinator.list_dispatchable_runs()
        from sagents.v2.runtime.session.plugins import session_storage_providers
        return session_storage_providers(self)

"""MySQL archive selection for the shared Redis persistence protocol."""
from .._shared.redis_persistence import RedisSessionPersistence
from .distributed_archive import DistributedMysqlSessionArchive
from .state import _MysqlSessionState, parse_mysql_dsn


class _RedisMysqlPersistence(RedisSessionPersistence, _MysqlSessionState):
    redis_plugin_id = "sage.session.redis-mysql"
    format_version = "sage.session.redis-mysql/v2"
    archive_backend = "mysql"
    _archive_type = DistributedMysqlSessionArchive

    @staticmethod
    def _archive_identity(dsn):
        identity = parse_mysql_dsn(dsn)
        identity.pop("password")
        return identity

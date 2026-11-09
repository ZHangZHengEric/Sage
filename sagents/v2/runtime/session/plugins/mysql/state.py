"""Shared MySQL persistence and lazy Session loading implementation.

The coordinator still owns sequencing, idempotency, and legal transitions.
This adapter persists one Session tree at a time and appends Run events.
There is no global Session index or cross-process subscribe.
"""

from __future__ import annotations

import asyncio
import re
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import unquote, urlparse

from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)
from sagents.v2.runtime.session.state import SessionStoreCoordinator
from .._shared.sql import SqlSessionPersistence
from .._shared.loading import DurableSessionLoading
from .._shared.aggregate import (
    SessionStoreCorruptionError as SessionStoreCorruptionError,
    _principal_lookup_key as _principal_lookup_key,
    _LOCATION_KINDS as _LOCATION_KINDS,
    _json as _json,
    _decode_json as _decode_json,
)
from .history import MysqlHistoryQueries
from .workspace import MysqlWorkspaceQueries
from .child_heads import MysqlManagedSessionHeads
from .run_metadata import MysqlRunMetadataQueries
from .read_views import MysqlSessionReadQueries
from .connections import MysqlConnectionBudget, finish_connection_cleanup
from sagents.v2.runtime.observability.logs import get_logger


_PREFIX = re.compile(r"^[a-z][a-z0-9_]{0,32}$")
_SCHEMA_TABLES = (
    "sessions",
    "session_mutations",
    "run_events",
    "locations",
    "start_idempotency",
    "derived_state",
    "attachments",
)
LOGGER = get_logger(__name__)

def _require_aiomysql():
    try:
        import aiomysql
    except ImportError as exc:
        raise SageV2Error(
            RuntimeErrorInfo(
                code="session_store.mysql_unavailable",
                category=ErrorCategory.RESOURCE_LOST,
                message="sage.session.mysql requires the optional aiomysql package",
                safe_to_resume=True,
            )
        ) from exc
    return aiomysql

def _datetime(value: str) -> str:
    return value.replace("T", " ").replace("Z", "")

def parse_mysql_dsn(dsn: str) -> dict[str, Any]:
    parsed = urlparse(dsn)
    database = unquote((parsed.path or "").lstrip("/").split("/", 1)[0])
    if parsed.scheme not in {"mysql", "mysql+aiomysql"} or not database:
        raise ValueError(
            "sage.session.mysql requires a mysql:// DSN that includes a database"
        )
    return {
        "host": parsed.hostname or "127.0.0.1",
        "port": parsed.port or 3306,
        "user": unquote(parsed.username or "root"),
        "password": unquote(parsed.password or ""),
        "db": database,
        "charset": "utf8mb4",
        "autocommit": False,
    }

class _MysqlSessionState(MysqlManagedSessionHeads, MysqlRunMetadataQueries, MysqlSessionReadQueries, MysqlWorkspaceQueries, MysqlHistoryQueries, SqlSessionPersistence, DurableSessionLoading, SessionStoreCoordinator):
    """Single-process MySQL adapter around the shared state coordinator."""

    format_version = "sage.session.mysql/v2"
    snapshot_interval = 256

    async def _sync_start_idempotency(self, cursor, session_id, current):
        try:
            await super()._sync_start_idempotency(cursor, session_id, current)
        except _require_aiomysql().IntegrityError as exc:
            if exc.args and exc.args[0] == 1062:
                # Keep the insert strict: restoring an old backup must never
                # take ownership of a key now belonging to another Session.
                # The shared commit path rolls back before exposing this error.
                raise self._conflict(
                    "session.revision_conflict",
                    "MySQL Session start key already exists; retry the operation",
                ) from exc
            raise

    def __init__(
        self,
        dsn: str,
        *,
        table_prefix: str | None = None,
        max_cached_sessions: int = 256,
        max_cached_bytes: int = 256 * 1024**2,
        cache_idle_seconds: float = 300,
        max_connections: int = 16,
        max_pending_connections: int = 64,
        connection_acquire_timeout_seconds: float = 10,
        **kwargs: Any,
    ) -> None:
        resolved = dsn.strip()
        if not resolved:
            raise ValueError(
                "sage.session.mysql requires dsn in the plugin declaration"
            )
        if table_prefix is None:
            prefix = "sagent"
        else:
            prefix = table_prefix.strip()
        if prefix and not _PREFIX.fullmatch(prefix):
            raise ValueError("mysql SessionStore table_prefix is invalid")
        self.dsn = resolved
        self.table_prefix = prefix
        self._connect_kwargs = parse_mysql_dsn(resolved)
        self._pool = None
        self._connection_budget = MysqlConnectionBudget(
            max_connections=max_connections, max_pending_connections=max_pending_connections,
            connection_acquire_timeout_seconds=connection_acquire_timeout_seconds,
        )
        self._init_lock = asyncio.Lock()
        self._closed = False
        super().__init__(max_cached_sessions=max_cached_sessions, max_cached_bytes=max_cached_bytes,
                         cache_idle_seconds=cache_idle_seconds, **kwargs)

    @property
    def capabilities(self) -> dict[str, bool | str]:
        return {
            **super().capabilities,
            "durable_across_process_restart": True,
            "storage_format_version": self.format_version,
            "multi_process_writes": False,
            "global_session_index": False,
            "derived_state_authoritative": False,
            "cross_process_subscribe": False,
        }

    def composition_identity(self) -> dict[str, str]:
        return {
            "plugin": "sage.session.mysql",
            "table_prefix": self.table_prefix,
            "format": self.format_version,
        }

    def _physical_table(self, name: str) -> str:
        return f"{self.table_prefix}_{name}" if self.table_prefix else name

    def _table(self, name: str) -> str:
        return f"`{self._physical_table(name)}`"

    def _constraint(self, name: str) -> str:
        return f"{self.table_prefix}_{name}" if self.table_prefix else name

    async def _ensure_ready(self) -> None:
        if self._pool is not None:
            return
        async with self._init_lock:
            if self._pool is not None:
                return
            if self._closed:
                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="session_store.closed",
                        category=ErrorCategory.RESOURCE_LOST,
                        message="mysql SessionStore is closed",
                        safe_to_resume=True,
                    )
                )
            aiomysql = _require_aiomysql()
            pool = await aiomysql.create_pool(
                minsize=0,
                maxsize=self._connection_budget.max_connections,
                **self._connect_kwargs,
            )
            try:
                async with pool.acquire() as connection:
                    created = await self._bootstrap(connection)
                LOGGER.info(
                    "session.mysql.ready",
                    "mysql session store ready",
                    prefix=self.table_prefix,
                    created=created,
                )
            except BaseException:
                pool.close()
                await finish_connection_cleanup(pool.wait_closed())
                raise
            self._pool = pool

    @asynccontextmanager
    async def _writer_connection(self):
        async with self._connection_budget.connection(self._ready_pool, reader=False) as connection:
            yield connection

    async def _ready_pool(self):
        await self._ensure_ready()
        assert self._pool is not None
        return self._pool

    @asynccontextmanager
    async def _reader_connection(self):
        async with self._connection_budget.connection(self._ready_pool, reader=True) as connection:
            yield connection

    async def _existing_tables(self, connection) -> set[str]:
        names = tuple(self._physical_table(name) for name in _SCHEMA_TABLES)
        placeholders = ", ".join(["%s"] * len(names))
        async with connection.cursor() as cursor:
            await cursor.execute(
                f"""
                SELECT TABLE_NAME FROM information_schema.TABLES
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME IN ({placeholders})
                """,
                names,
            )
            rows = await cursor.fetchall()
        return {str(row[0]) for row in rows}

    async def _bootstrap(self, connection) -> tuple[str, ...]:
        existing = await self._existing_tables(connection)
        statements = (
            (
                "sessions",
                f"""
            CREATE TABLE IF NOT EXISTS {self._table("sessions")} (
                session_id VARCHAR(128) NOT NULL,
                parent_session_id VARCHAR(128) NULL,
                revision BIGINT NOT NULL,
                last_sequence BIGINT NOT NULL,
                created_at DATETIME(6) NOT NULL,
                updated_at DATETIME(6) NOT NULL,
                compact_state JSON NOT NULL,
                PRIMARY KEY (session_id),
                KEY sessions_parent_id (parent_session_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            ),
            (
                "session_mutations",
                f"""
            CREATE TABLE IF NOT EXISTS {self._table("session_mutations")} (
                session_id VARCHAR(128) NOT NULL,
                revision BIGINT NOT NULL,
                mutation JSON NOT NULL,
                PRIMARY KEY (session_id, revision),
                CONSTRAINT {self._constraint("session_mutations_session")}
                    FOREIGN KEY (session_id)
                    REFERENCES {self._table("sessions")} (session_id)
                    ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            ),
            (
                "run_events",
                f"""
            CREATE TABLE IF NOT EXISTS {self._table("run_events")} (
                session_id VARCHAR(128) NOT NULL,
                run_id VARCHAR(128) NOT NULL,
                run_sequence BIGINT NOT NULL,
                session_sequence BIGINT NULL,
                event JSON NOT NULL,
                PRIMARY KEY (run_id, run_sequence),
                KEY run_events_session_seq (session_id, session_sequence),
                CONSTRAINT {self._constraint("run_events_session")}
                    FOREIGN KEY (session_id)
                    REFERENCES {self._table("sessions")} (session_id)
                    ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            ),
            (
                "locations",
                f"""
            CREATE TABLE IF NOT EXISTS {self._table("locations")} (
                kind VARCHAR(64) NOT NULL,
                identity VARCHAR(128) NOT NULL,
                session_id VARCHAR(128) NOT NULL,
                PRIMARY KEY (kind, identity),
                CONSTRAINT {self._constraint("locations_session")}
                    FOREIGN KEY (session_id)
                    REFERENCES {self._table("sessions")} (session_id)
                    ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            ),
            (
                "start_idempotency",
                f"""
            CREATE TABLE IF NOT EXISTS {self._table("start_idempotency")} (
                tenant_id VARCHAR(128) NOT NULL DEFAULT '',
                principal_id VARCHAR(128) NOT NULL,
                idempotency_key VARCHAR(128) NOT NULL,
                session_id VARCHAR(128) NOT NULL,
                run_id VARCHAR(128) NOT NULL,
                request_digest VARCHAR(128) NOT NULL,
                PRIMARY KEY (tenant_id, principal_id, idempotency_key),
                CONSTRAINT {self._constraint("start_idempotency_session")}
                    FOREIGN KEY (session_id)
                    REFERENCES {self._table("sessions")} (session_id)
                    ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            ),
            (
                "derived_state",
                f"""
            CREATE TABLE IF NOT EXISTS {self._table("derived_state")} (
                session_id VARCHAR(128) NOT NULL,
                namespace VARCHAR(128) NOT NULL,
                `key` VARCHAR(128) NOT NULL,
                value JSON NOT NULL,
                PRIMARY KEY (session_id, namespace, `key`),
                CONSTRAINT {self._constraint("derived_state_session")}
                    FOREIGN KEY (session_id)
                    REFERENCES {self._table("sessions")} (session_id)
                    ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            ),
            (
                "attachments",
                f"""
            CREATE TABLE IF NOT EXISTS {self._table("attachments")} (
                session_id VARCHAR(128) NOT NULL,
                artifact_id VARCHAR(128) NOT NULL,
                payload LONGBLOB NOT NULL,
                PRIMARY KEY (session_id, artifact_id),
                CONSTRAINT {self._constraint("attachments_session")}
                    FOREIGN KEY (session_id) REFERENCES {self._table("sessions")} (session_id)
                    ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            ),
        )
        created: list[str] = []
        async with connection.cursor() as cursor:
            for name, statement in statements:
                physical = self._physical_table(name)
                if physical in existing:
                    continue
                await cursor.execute(statement)
                created.append(physical)
        await connection.commit()
        return tuple(created)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        pool = self._pool
        self._pool = None
        if pool is not None:
            pool.close()
            await finish_connection_cleanup(pool.wait_closed())


















































    async def filter_suspended_session_ids(self, session_ids):
        """Project current Run states without installing any Session history."""
        selected = set()
        ids = tuple(session_ids)
        for start in range(0, len(ids), 128):
            batch = ids[start:start + 128]
            marks = ",".join(["%s"] * len(batch))
            # A compact base can be older than its journal. Rank only the tiny
            # state projections, never fetch checkpoint/event JSON into Python.
            statement = f"""
                WITH states AS (
                    SELECT s.session_id, r.run_id, r.state,
                        CAST(JSON_UNQUOTE(JSON_EXTRACT(s.compact_state, '$.sessions[0].revision')) AS UNSIGNED) AS revision
                    FROM {self._table('sessions')} s,
                        JSON_TABLE(s.compact_state, '$.runs[*]' COLUMNS (
                            run_id VARCHAR(128) PATH '$.run_id', state VARCHAR(32) PATH '$.state')) r
                    WHERE s.session_id IN ({marks})
                    UNION ALL
                    SELECT m.session_id, r.run_id, r.state, m.revision
                    FROM {self._table('session_mutations')} m,
                        JSON_TABLE(m.mutation, '$.upserts.runs[*]' COLUMNS (
                            run_id VARCHAR(128) PATH '$.run_id', state VARCHAR(32) PATH '$.state')) r
                    WHERE m.session_id IN ({marks})
                    UNION ALL
                    SELECT m.session_id, r.run_id, r.state, m.revision
                    FROM {self._table('session_mutations')} m,
                        JSON_TABLE(m.mutation, '$.patches.runs[*]' COLUMNS (
                            run_id VARCHAR(128) PATH '$.run_id', state VARCHAR(32) PATH '$.state')) r
                    WHERE m.session_id IN ({marks}) AND r.state IS NOT NULL
                ), latest AS (
                    SELECT session_id, state,
                        ROW_NUMBER() OVER (PARTITION BY session_id, run_id ORDER BY revision DESC) AS position
                    FROM states
                ) SELECT DISTINCT session_id FROM latest WHERE position = 1 AND state = 'suspended'
            """
            async with self._reader_connection() as connection:
                async with connection.cursor() as cursor:
                    await cursor.execute(statement, batch * 3)
                    selected.update(str(row[0]) for row in await cursor.fetchall())
        return selected







    backend = "mysql"
    json_type = "JSON"
    key_column = "`key`"
    _storage_datetime = staticmethod(_datetime)

    @property
    def _storage_logger(self):
        return LOGGER

    async def _insert_attachments(self, cursor, session_id):
        for artifact_id, payload in self._pending_attachments(session_id):
            await cursor.execute(
                f"INSERT INTO {self._table('attachments')} (session_id, artifact_id, payload) VALUES (%s, %s, UNHEX(%s))",
                (session_id, artifact_id, payload.hex()),
            )

    async def _write_workspace_projection(self, cursor, session_id, revision, states):
        from .workspace_probe import write_projection
        await write_projection(cursor, self._table, session_id, revision, states)

    def _derived_upsert_sql(self):
        return f"""INSERT INTO {self._table('derived_state')} (session_id, namespace, `key`, value)
            VALUES (%s, %s, %s, CAST(%s AS JSON)) AS incoming
            ON DUPLICATE KEY UPDATE value = incoming.value"""

    async def _begin_snapshot(self, connection):
        async with connection.cursor() as cursor:
            await cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        await connection.begin()

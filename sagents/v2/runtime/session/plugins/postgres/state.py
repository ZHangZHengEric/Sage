"""PostgreSQL SQL dialect and lifecycle around the shared Session coordinator."""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
import re
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.runtime.observability.logs import get_logger
from sagents.v2.runtime.session.state import SessionStoreCoordinator
from .._shared.loading import DurableSessionLoading
from .._shared.sql import SqlSessionPersistence
from .connections import PostgresConnectionBudget, finish_cleanup
from .queries import PostgresSessionQueries
from .schema import bootstrap

LOGGER = get_logger(__name__)
_PREFIX = re.compile(r"^[a-z][a-z0-9_]{0,32}$")


def parse_postgres_dsn(dsn: str) -> str:
    """Normalize URL schemes without discarding libpq SSL and connection options."""
    value = dsn.strip()
    parsed = urlsplit(value)
    database = unquote(parsed.path.lstrip("/"))
    if (
        parsed.scheme not in {"postgres", "postgresql", "postgresql+psycopg"}
        or not database
        or "/" in database
        or parsed.fragment
    ):
        raise ValueError(
            "sage.session.postgres requires a postgresql:// DSN that includes a database"
        )
    if parsed.port is not None and not 0 < parsed.port < 65536:
        raise ValueError("invalid PostgreSQL port")
    query = urlencode(parse_qsl(parsed.query, keep_blank_values=True), quote_via=quote)
    return urlunsplit(("postgresql", parsed.netloc, parsed.path, query, ""))


class _PostgresSessionState(
    PostgresSessionQueries,
    SqlSessionPersistence,
    DurableSessionLoading,
    SessionStoreCoordinator,
):
    backend = "postgres"
    format_version = "sage.session.postgres/v2"
    snapshot_interval = 256
    _decode_derived_value = staticmethod(lambda value: value)
    json_type = "JSONB"
    key_column = '"key"'

    def __init__(
        self,
        dsn,
        *,
        table_prefix=None,
        max_connections=16,
        max_pending_connections=64,
        connection_acquire_timeout_seconds=10,
        **kwargs,
    ):
        self.dsn = parse_postgres_dsn(dsn)
        self.table_prefix = "sagent" if table_prefix is None else table_prefix.strip()
        if self.table_prefix and not _PREFIX.fullmatch(self.table_prefix):
            raise ValueError("postgres SessionStore table_prefix is invalid")
        self._connection_budget = PostgresConnectionBudget(
            max_connections=max_connections,
            max_pending_connections=max_pending_connections,
            connection_acquire_timeout_seconds=connection_acquire_timeout_seconds,
        )
        self._pool = None
        self._init_lock = asyncio.Lock()
        self._closed = False
        self._stale_session_ids = set()
        super().__init__(**kwargs)

    @property
    def capabilities(self):
        return {
            **super().capabilities,
            "durable_across_process_restart": True,
            "storage_format_version": self.format_version,
            "multi_process_writes": False,
            "global_session_index": False,
            "derived_state_authoritative": False,
            "cross_process_subscribe": False,
        }

    def composition_identity(self):
        return {
            "plugin": "sage.session.postgres",
            "table_prefix": self.table_prefix,
            "format": self.format_version,
        }

    def _physical_table(self, name):
        return f"{self.table_prefix}_{name}" if self.table_prefix else name

    def _table(self, name):
        return '"' + self._physical_table(name) + '"'

    @property
    def _storage_logger(self):
        return LOGGER

    @staticmethod
    def _storage_datetime(value):
        return datetime.fromisoformat(value)

    async def _ensure_ready(self):
        if self._closed:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="session_store.closed",
                    category=ErrorCategory.RESOURCE_LOST,
                    message="PostgreSQL SessionStore is closed",
                    safe_to_resume=True,
                )
            )
        if self._pool is not None:
            return
        async with self._init_lock:
            if self._pool is not None:
                return
            try:
                from psycopg import IsolationLevel
                from psycopg_pool import AsyncConnectionPool
            except ImportError as exc:
                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="session_store.postgres_unavailable",
                        category=ErrorCategory.RESOURCE_LOST,
                        message="sage.session.postgres requires the optional psycopg and psycopg_pool packages",
                        safe_to_resume=True,
                    )
                ) from exc

            async def configure(connection):
                await connection.set_isolation_level(IsolationLevel.REPEATABLE_READ)

            # Explicit open and rollback before putconn follow psycopg's pool API.
            # https://www.psycopg.org/psycopg3/docs/advanced/pool.html
            pool = AsyncConnectionPool(
                self.dsn,
                min_size=0,
                max_size=self._connection_budget.max_connections,
                max_waiting=self._connection_budget.max_pending_connections,
                timeout=self._connection_budget.timeout,
                open=False,
                configure=configure,
                kwargs={}
                if "connect_timeout" in dict(parse_qsl(urlsplit(self.dsn).query))
                else {"connect_timeout": max(1, int(self._connection_budget.timeout))},
            )
            try:
                await pool.open()
                async with pool.connection() as connection:
                    # Bootstrap must see DDL committed while its advisory lock
                    # was waiting. Ordinary reads retain repeatable snapshots.
                    await connection.set_isolation_level(IsolationLevel.READ_COMMITTED)
                    created = await bootstrap(self, connection)
                    await connection.set_isolation_level(IsolationLevel.REPEATABLE_READ)
                if self._closed:
                    raise RuntimeError("PostgreSQL SessionStore closed during startup")
            except BaseException:
                await finish_cleanup(pool.close())
                raise
            self._pool = pool
            LOGGER.info(
                "session.postgres.ready",
                "PostgreSQL session store ready",
                prefix=self.table_prefix,
                created=created,
            )

    async def _ready_pool(self):
        await self._ensure_ready()
        return self._pool

    @asynccontextmanager
    async def _writer_connection(self):
        async with self._connection_budget.connection(
            self._ready_pool, reader=False
        ) as connection:
            yield connection

    @asynccontextmanager
    async def _reader_connection(self):
        async with self._connection_budget.connection(
            self._ready_pool, reader=True
        ) as connection:
            yield connection

    async def _begin_snapshot(self, connection):
        # Every pooled connection already starts transactions in REPEATABLE READ.
        pass

    async def close(self):
        self._closed = True
        async with self._init_lock:
            pool, self._pool = self._pool, None
            if pool is not None:
                await finish_cleanup(pool.close())

    async def _insert_attachments(self, cursor, session_id):
        for artifact_id, payload in self._pending_attachments(session_id):
            await cursor.execute(
                f"INSERT INTO {self._table('attachments')} (session_id, artifact_id, payload) VALUES (%s, %s, %s)",
                (session_id, artifact_id, payload),
            )

    async def _write_workspace_projection(self, cursor, session_id, revision, states):
        # PostgreSQL's metadata query projects Run states directly from JSONB.
        pass

    def _derived_upsert_sql(self):
        return f"""INSERT INTO {self._table("derived_state")} (session_id, namespace, "key", value)
            VALUES (%s, %s, %s, CAST(%s AS JSONB))
            ON CONFLICT (session_id, namespace, "key") DO UPDATE SET value = EXCLUDED.value"""

    async def _commit_storage_locked(self, session_id):
        try:
            await super()._commit_storage_locked(session_id)
        except Exception as exc:
            # Coordinator undo runs after the failed storage call. Refresh under
            # the next operation's lock so undo cannot reintroduce a stale head.
            self._stale_session_ids.add(session_id)
            if getattr(exc, "sqlstate", None) in {"40001", "40P01", "23505"}:
                raise self._conflict(
                    "session.revision_conflict",
                    "PostgreSQL Session changed; retry the operation",
                ) from exc
            raise

    async def _prepare_session_access(self, session_id):
        await self._ensure_ready()
        if session_id in self._stale_session_ids:
            await self._reload_session_from_storage_locked(session_id)
            self._stale_session_ids.discard(session_id)

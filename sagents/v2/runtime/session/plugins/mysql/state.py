"""Shared MySQL persistence and lazy Session loading implementation.

The coordinator still owns sequencing, idempotency, and legal transitions.
This adapter persists one Session tree at a time and appends Run events.
There is no global Session index or cross-process subscribe.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from contextlib import AsyncExitStack, asynccontextmanager, aclosing
from copy import deepcopy
from typing import Any
from urllib.parse import unquote, urlparse
from weakref import WeakValueDictionary

from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)
from sagents.v2.runtime.session.aggregate import SessionAggregate
from sagents.v2.runtime.session.journal import (
    SessionAggregateSnapshotV2,
    SessionRowSnapshot,
    SessionStateDeltaMutation,
)
from sagents.v2.runtime.session.state import SessionStoreCoordinator
from .history import MysqlHistoryQueries
from .workspace import MysqlWorkspaceQueries
from .child_heads import MysqlManagedSessionHeads
from .run_metadata import MysqlRunMetadataQueries
from .read_views import MysqlSessionReadQueries
from .cache import IdleSessionCache, cached_session_operation
from .connections import MysqlConnectionBudget, finish_connection_cleanup
from sagents.v2.runtime.observability.logs import get_logger


def _principal_lookup_key(principal_type: str, principal_id: str) -> str:
    identity = f"{principal_type}\0{principal_id}".encode("utf-8")
    return f"typed:{hashlib.sha256(identity).hexdigest()}"


class SessionStoreCorruptionError(SageV2Error):
    """Raised when a stored Session aggregate cannot be trusted."""


_PREFIX = re.compile(r"^[a-z][a-z0-9_]{0,32}$")
_COMPACT_LISTS = (
    "sessions",
    "runs",
    "start_idempotency",
    "command_results",
    "execution_resources",
    "execution_resource_command_results",
    "checkpoints",
    "suspensions",
    "interactions",
    "interaction_resolutions",
    "session_commit_proposals",
    "session_commit_command_results",
)
_COMPACT_MAPS = ("fork_base_events", "steer_inbox")
_LOCATION_KINDS = (
    ("runs", "run_id"),
    ("checkpoints", "checkpoint_id"),
    ("suspensions", "suspension_id"),
    ("interactions", "interaction_id"),
    ("session_commit_proposals", "proposal_id"),
)
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


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _decode_json(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        return json.loads(value)
    return value


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


class _MysqlSessionState(MysqlManagedSessionHeads, MysqlRunMetadataQueries, MysqlSessionReadQueries, MysqlWorkspaceQueries, MysqlHistoryQueries, SessionStoreCoordinator):
    """Single-process MySQL adapter around the shared state coordinator."""

    format_version = "sage.session.mysql/v2"
    snapshot_interval = 256

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
        self._load_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()
        self._loaded_session_ids: set[str] = set()
        self._persisted_run_sequences: dict[str, int] = {}
        self._persisted_session_runs: dict[str, set[str]] = {}
        self._persisted_session_revisions: dict[str, int] = {}
        self._persisted_mutation_counts: dict[str, int] = {}
        self._persisted_locations: dict[str, set[tuple[str, str, str]]] = {}
        self._persisted_start_keys: dict[str, set[tuple[str, ...]]] = {}
        self._closed = False
        super().__init__(**kwargs)
        self._session_cache = IdleSessionCache(self, max_sessions=max_cached_sessions,
            max_bytes=max_cached_bytes, idle_seconds=cache_idle_seconds)

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

    async def _commit_storage_locked(self, session_id: str) -> None:
        started_at = time.perf_counter()
        await self._ensure_ready()
        mutation = self._session_mutation_locked(session_id).model_dump(
            mode="json", exclude={"kind"}
        )
        location_rows = self._location_rows_after_mutation(session_id, mutation)
        start_rows = self._start_rows_after_mutation(session_id, mutation)
        appended = mutation["appends"].pop("run_events", {})
        replaced = mutation["replacements"].pop("run_events", {})
        mutation["map_deletes"].pop("run_events", None)
        run_ids = self._session_run_ids_locked(session_id)
        event_totals = {run_id: len(self._run_events[run_id]) for run_id in run_ids}
        events = {
            run_id: list(replaced.get(run_id, appended.get(run_id, ())))
            for run_id in run_ids
        }
        expected_revision = self._persisted_session_revisions.get(session_id)
        should_snapshot = (
            expected_revision is None
            or self._persisted_mutation_counts.get(session_id, 0) + 1
            >= self.snapshot_interval
        )
        compact = (
            self._compact_state(
                self._dump_session_state_locked(session_id, event_offsets=event_totals)
            )
            if should_snapshot
            else None
        )
        session_row = mutation["upserts"]["sessions"][0]
        new_revision = int(session_row["revision"])
        if not should_snapshot:
            session_row["revision_sequences"] = {
                str(new_revision): int(session_row["last_sequence"])
            }
        encoded_compact = _json(compact) if should_snapshot else None
        encoded_mutation = _json(mutation) if not should_snapshot else None
        next_run_sequences: dict[str, int] = {}
        failure: Exception | None = None
        prepared_at = time.perf_counter()
        written_at = committed_at = prepared_at
        async with self._writer_connection() as connection:
            acquired_at = time.perf_counter()
            try:
                async with connection.cursor() as cursor:
                    if expected_revision is None:
                        await cursor.execute(
                            f"""
                        INSERT INTO {self._table("sessions")} (
                            session_id, parent_session_id, revision,
                            last_sequence, created_at, updated_at, compact_state
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, CAST(%s AS JSON))
                        """,
                            (
                                session_id,
                                session_row.get("parent_session_id"),
                                new_revision,
                                int(session_row["last_sequence"]),
                                _datetime(session_row["created_at"]),
                                _datetime(session_row["updated_at"]),
                                encoded_compact,
                            ),
                        )
                    else:
                        if should_snapshot:
                            await cursor.execute(
                                f"""
                            UPDATE {self._table("sessions")} SET
                                parent_session_id = %s, revision = %s,
                                last_sequence = %s, updated_at = %s,
                                compact_state = CAST(%s AS JSON)
                            WHERE session_id = %s AND revision = %s
                            """,
                                (
                                    session_row.get("parent_session_id"),
                                    new_revision,
                                    int(session_row["last_sequence"]),
                                    _datetime(session_row["updated_at"]),
                                    encoded_compact,
                                    session_id,
                                    expected_revision,
                                ),
                            )
                        else:
                            await cursor.execute(
                                f"""
                                UPDATE {self._table("sessions")} SET
                                    parent_session_id = %s, revision = %s,
                                    last_sequence = %s, updated_at = %s
                                WHERE session_id = %s AND revision = %s
                                """,
                                (
                                    session_row.get("parent_session_id"),
                                    new_revision,
                                    int(session_row["last_sequence"]),
                                    _datetime(session_row["updated_at"]),
                                    session_id,
                                    expected_revision,
                                ),
                            )
                        if cursor.rowcount != 1:
                            raise self._conflict(
                                "session.revision_conflict",
                                f"expected session revision {expected_revision} for {session_id}",
                            )
                    for artifact_id, payload in self._pending_attachments(session_id):
                        # aiomysql calls PyMySQL's removed bytes escaper on some
                        # dependency combinations. Bind ASCII hex instead;
                        # UNHEX restores the exact bytes in the LONGBLOB column.
                        await cursor.execute(
                            f"INSERT INTO {self._table('attachments')} (session_id, artifact_id, payload) VALUES (%s, %s, UNHEX(%s))",
                            (session_id, artifact_id, payload.hex()),
                        )
                    next_run_sequences = await self._persist_events(
                        cursor, session_id, events, event_totals=event_totals
                    )
                    if should_snapshot:
                        await cursor.execute(
                            f"DELETE FROM {self._table('session_mutations')} WHERE session_id = %s",
                            (session_id,),
                        )
                    else:
                        await cursor.execute(
                            f"""
                            INSERT INTO {self._table("session_mutations")}
                                (session_id, revision, mutation)
                            VALUES (%s, %s, CAST(%s AS JSON))
                            """,
                            (session_id, new_revision, encoded_mutation),
                        )
                    await self._sync_locations(cursor, session_id, location_rows)
                    await self._sync_start_idempotency(cursor, session_id, start_rows)
                written_at = time.perf_counter()
                await connection.commit()
                committed_at = time.perf_counter()
            except Exception as exc:
                try:
                    await connection.rollback()
                except Exception as rollback_error:
                    LOGGER.exception(
                        "session.mysql.rollback_failed",
                        "mysql session rollback failed",
                        rollback_error,
                    )
                failure = exc
        if failure is not None:
            LOGGER.debug("session.mysql.commit_failed", "MySQL 会话提交失败",
                session_id=session_id, revision=new_revision,
                duration_ms=round((time.perf_counter() - started_at) * 1000, 3))
            try:
                await self._reload_session_from_storage_locked(session_id)
            except Exception as recovery_error:
                # Preserve the write failure even when recovery itself fails.
                raise recovery_error from failure
            raise failure
        self._forget_attachment_bytes(session_id)
        self._remember_persisted_session(
            session_id,
            new_revision,
            next_run_sequences,
            location_rows,
            start_rows,
            0
            if should_snapshot
            else self._persisted_mutation_counts.get(session_id, 0) + 1,
        )
        # Conservatively account for retained Python objects using serialized
        # bytes. Repeated mutations overestimate rather than hide memory growth.
        self._session_cache.touch(session_id, charge=4 * (
            len((encoded_compact or encoded_mutation or "").encode())
            + sum(len(_json(event).encode()) for rows in events.values() for event in rows)))
        LOGGER.debug(
            "session.mysql.commit",
            "MySQL 会话提交完成",
            session_id=session_id,
            revision=new_revision,
            snapshot=should_snapshot,
            payload_bytes=len(
                (encoded_compact or encoded_mutation or "").encode("utf-8")
            ),
            event_count=sum(len(rows) for rows in events.values()),
            duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
            preparation_ms=round((prepared_at - started_at) * 1000, 3),
            connection_wait_ms=round((acquired_at - prepared_at) * 1000, 3),
            write_ms=round((written_at - acquired_at) * 1000, 3),
            commit_ms=round((committed_at - written_at) * 1000, 3),
        )

    async def _persist_events(
        self, cursor, session_id, events, *, event_totals=None
    ) -> dict[str, int]:
        next_sequences = {
            run_id: self._persisted_run_sequences[run_id]
            for run_id in events
            if run_id in self._persisted_run_sequences
        }
        removed = self._persisted_session_runs.get(session_id, set()) - set(events)
        for run_id in removed:
            await cursor.execute(
                f"DELETE FROM {self._table('run_events')} WHERE run_id = %s",
                (run_id,),
            )
        for run_id, rows in events.items():
            persisted = next_sequences.get(run_id, 0)
            total = len(rows) if event_totals is None else event_totals[run_id]
            if persisted > total:
                await cursor.execute(
                    f"DELETE FROM {self._table('run_events')} WHERE run_id = %s",
                    (run_id,),
                )
                persisted = 0
            appended = rows[persisted:] if event_totals is None else rows
            if appended:
                await cursor.executemany(
                    f"""
                    INSERT INTO {self._table("run_events")} (
                        session_id, run_id, run_sequence, session_sequence, event
                    )
                    VALUES (%s, %s, %s, %s, CAST(%s AS JSON))
                    """,
                    [
                        (
                            session_id,
                            run_id,
                            int(event["run_sequence"]),
                            event.get("session_sequence"),
                            _json(event),
                        )
                        for event in appended
                    ],
                )
            next_sequences[run_id] = total
        return next_sequences

    @staticmethod
    def _location_rows(session_id, compact) -> set[tuple[str, str, str]]:
        return {
            (key, str(value.get(key)), session_id)
            for collection, key in _LOCATION_KINDS
            for value in compact.get(collection, ())
            if value.get(key)
        }

    def _location_rows_after_mutation(self, session_id, mutation):
        current = {
            (kind, identity): (kind, identity, session_id)
            for kind, identity, _ in self._persisted_locations.get(session_id, set())
        }
        for collection, key in _LOCATION_KINDS:
            for identity in mutation["deletes"].get(collection, ()):
                current.pop((key, str(identity[0])), None)
            for row in mutation["upserts"].get(collection, ()):
                if row.get(key):
                    identity = str(row[key])
                    current[(key, identity)] = (key, identity, session_id)
        return set(current.values())

    async def _sync_locations(self, cursor, session_id, current) -> None:
        previous = self._persisted_locations.get(session_id, set())
        removed = sorted(previous - current)
        added = sorted(current - previous)
        if removed:
            await cursor.executemany(
                f"DELETE FROM {self._table('locations')} WHERE kind = %s AND identity = %s",
                [(kind, identity) for kind, identity, _ in removed],
            )
        if added:
            await cursor.executemany(
                f"""
                INSERT INTO {self._table("locations")} (kind, identity, session_id)
                VALUES (%s, %s, %s)
                """,
                added,
            )

    @staticmethod
    def _start_key_rows(session_id, compact) -> set[tuple[str, ...]]:
        return {
            (
                str(entry.get("tenant_id") or ""),
                _principal_lookup_key(
                    str(entry.get("principal_type") or ""),
                    str(entry["principal_id"]),
                ),
                str(entry["idempotency_key"]),
                session_id,
                str(entry["run_id"]),
                str(entry["request_digest"]),
            )
            for entry in compact.get("start_idempotency", ())
        }

    def _start_rows_after_mutation(self, session_id, mutation):
        current = {
            row[:3]: row for row in self._persisted_start_keys.get(session_id, set())
        }
        for tenant_id, principal_type, principal_id, key in mutation["deletes"].get(
            "start_idempotency", ()
        ):
            lookup = (
                str(tenant_id or ""),
                _principal_lookup_key(str(principal_type or ""), str(principal_id)),
                str(key),
            )
            current.pop(lookup, None)
        for row in self._start_key_rows(
            session_id,
            {"start_idempotency": mutation["upserts"].get("start_idempotency", ())},
        ):
            current[row[:3]] = row
        return set(current.values())

    async def _sync_start_idempotency(self, cursor, session_id, current) -> None:
        previous = self._persisted_start_keys.get(session_id, set())
        removed = sorted(previous - current)
        added = sorted(current - previous)
        if removed:
            await cursor.executemany(
                f"""
                DELETE FROM {self._table("start_idempotency")}
                WHERE tenant_id = %s AND principal_id = %s AND idempotency_key = %s
                """,
                [row[:3] for row in removed],
            )
        if added:
            await cursor.executemany(
                f"""
                INSERT INTO {self._table("start_idempotency")} (
                    tenant_id, principal_id, idempotency_key,
                    session_id, run_id, request_digest
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                added,
            )

    async def _delete_storage_locked(
        self, session_id: str, deleted_session_ids: frozenset[str]
    ) -> None:
        await self._ensure_ready()
        ordered = tuple(sorted(deleted_session_ids))
        async with self._writer_connection() as connection:
            try:
                async with connection.cursor() as cursor:
                    if ordered:
                        placeholders = ", ".join(["%s"] * len(ordered))
                        await cursor.execute(
                            f"""
                            DELETE FROM {self._table("sessions")}
                            WHERE session_id IN ({placeholders})
                            """,
                            list(ordered),
                        )
                await connection.commit()
            except Exception:
                try:
                    await connection.rollback()
                except Exception as rollback_error:
                    LOGGER.exception(
                        "session.mysql.rollback_failed",
                        "mysql session rollback failed",
                        rollback_error,
                    )
                raise
        for value in deleted_session_ids:
            self._forget_persisted_session(value)

    async def _read_attachment_bytes(self, session_id, artifact_id):
        if (session_id, artifact_id) in self._attachment_payloads:
            return self._attachment_payloads[(session_id, artifact_id)]
        await self._ensure_ready()
        async with self._writer_connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    f"SELECT payload FROM {self._table('attachments')} WHERE session_id = %s AND artifact_id = %s",
                    (session_id, artifact_id),
                )
                row = await cursor.fetchone()
        if row is None:
            raise self._attachment_error(
                "artifact.not_found", "Session attachment bytes were not found."
            )
        return bytes(row[0])

    @cached_session_operation
    async def get_derived_state(
        self, session_id: str, namespace: str, key: str
    ) -> Any | None:
        await self._ensure_session_loaded(session_id)
        await super().get_session(session_id)
        assert self._pool is not None
        async with self._reader_connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    f"""
                    SELECT value FROM {self._table("derived_state")}
                    WHERE session_id = %s AND namespace = %s AND `key` = %s
                    """,
                    (session_id, namespace, key),
                )
                row = await cursor.fetchone()
        if row is None:
            return None
        return _decode_json(row[0])

    @cached_session_operation
    async def put_derived_state(
        self, session_id: str, namespace: str, key: str, value: Any
    ) -> None:
        await self._ensure_session_loaded(session_id)
        # SQL is authoritative for derived state. Keeping the coordinator's
        # unused copy would bypass the Session cache byte budget.
        await super().get_session(session_id)
        await self._ensure_ready()
        async with self._writer_connection() as connection:
            try:
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        f"""
                        INSERT INTO {self._table("derived_state")}
                            (session_id, namespace, `key`, value)
                        VALUES (%s, %s, %s, CAST(%s AS JSON)) AS incoming
                        ON DUPLICATE KEY UPDATE value = incoming.value
                        """,
                        (session_id, namespace, key, _json(value)),
                    )
                await connection.commit()
            except Exception:
                try:
                    await connection.rollback()
                except Exception as rollback_error:
                    LOGGER.exception(
                        "session.mysql.rollback_failed",
                        "mysql session rollback failed",
                        rollback_error,
                    )
                raise

    @cached_session_operation
    async def delete_derived_state(
        self, session_id: str, namespace: str, key: str
    ) -> None:
        await self._ensure_session_loaded(session_id)
        await super().get_session(session_id)
        await self._ensure_ready()
        async with self._writer_connection() as connection:
            try:
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        f"""
                        DELETE FROM {self._table("derived_state")}
                        WHERE session_id = %s AND namespace = %s AND `key` = %s
                        """,
                        (session_id, namespace, key),
                    )
                await connection.commit()
            except Exception:
                try:
                    await connection.rollback()
                except Exception as rollback_error:
                    LOGGER.exception(
                        "session.mysql.rollback_failed",
                        "mysql session rollback failed",
                        rollback_error,
                    )
                raise

    async def forget_session(self, session_id: str) -> None:
        await super().forget_session(session_id)
        await self._ensure_ready()
        async with self._writer_connection() as connection:
            try:
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        f"DELETE FROM {self._table('derived_state')} WHERE session_id = %s",
                        (session_id,),
                    )
                await connection.commit()
            except Exception:
                try:
                    await connection.rollback()
                except Exception as rollback_error:
                    LOGGER.exception(
                        "session.mysql.rollback_failed",
                        "mysql session rollback failed",
                        rollback_error,
                    )
                raise

    @cached_session_operation
    async def create_run(self, command, context):
        await self._ensure_ready()
        if command.parent_run_id:
            await self._ensure_resource_loaded("runs", "run_id", command.parent_run_id)
        if command.session_id is not None:
            await self._ensure_session_loaded(command.session_id, missing_ok=True)
        else:
            lookup = await self._read_start_lookup(command, context)
            if lookup is not None:
                await self._ensure_session_loaded(lookup)
        return await super().create_run(command, context)

    @cached_session_operation
    async def get_session(self, session_id):
        await self._ensure_session_loaded(session_id)
        return await super().get_session(session_id)

    @cached_session_operation
    async def authorize_session_actor(self, session_id, context):
        await self._ensure_session_loaded(session_id)
        await super().authorize_session_actor(session_id, context)

    @cached_session_operation
    async def delete_session(self, session_id):
        await self._ensure_session_loaded(session_id)
        await self._ensure_descendants_loaded(session_id)
        result = await super().delete_session(session_id)
        self._loaded_session_ids.intersection_update(self._sessions)
        self._session_cache.evicted_suspended.discard(session_id)
        return result

    async def has_nonterminal_runs(self):
        return bool(self._session_cache.evicted_suspended) or await super().has_nonterminal_runs()

    @cached_session_operation
    async def get_execution_resource(self, run_id):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        return await super().get_execution_resource(run_id)

    @cached_session_operation
    async def commit_execution_resource(self, *, record, **kwargs):
        await self._ensure_resource_loaded("runs", "run_id", record.run_id)
        return await super().commit_execution_resource(record=record, **kwargs)

    @cached_session_operation
    async def get_run_context(self, run_id):
        return await super().get_run_context(run_id)

    @cached_session_operation
    async def put_attachment(self, session_id, **kwargs):
        return await super().put_attachment(session_id, **kwargs)

    @cached_session_operation
    async def get_attachment(self, session_id, artifact_id, **kwargs):
        return await super().get_attachment(session_id, artifact_id, **kwargs)

    @cached_session_operation
    async def copy_attachment(self, source_session_id, target_session_id, artifact_id, **kwargs):
        return await super().copy_attachment(source_session_id, target_session_id, artifact_id, **kwargs)

    @cached_session_operation
    async def export_session_backup(self, session_id, **kwargs):
        return await super().export_session_backup(session_id, **kwargs)

    @cached_session_operation
    async def restore_session_backup(self, backup, **kwargs):
        return await super().restore_session_backup(backup, **kwargs)

    @cached_session_operation
    async def list_session_runs(self, session_id):
        await self._ensure_session_loaded(session_id)
        return await super().list_session_runs(session_id)

    @cached_session_operation
    async def list_descendant_sessions(self, session_id):
        await self._ensure_session_loaded(session_id)
        await self._ensure_descendants_loaded(session_id)
        return await super().list_descendant_sessions(session_id)

    @cached_session_operation
    async def read_session_events(self, session_id, **kwargs):
        await self._ensure_session_loaded(session_id)
        return await super().read_session_events(session_id, **kwargs)

    @cached_session_operation
    async def list_session_commit_proposals(self, session_id):
        await self._ensure_session_loaded(session_id)
        return await super().list_session_commit_proposals(session_id)

    @cached_session_operation
    async def get_run(self, run_id):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        return await super().get_run(run_id)

    @cached_session_operation
    async def get_run_result(self, run_id):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        return await super().get_run_result(run_id)

    @cached_session_operation
    async def find_start_run(self, session_id, idempotency_key, context):
        await self._ensure_session_loaded(session_id, missing_ok=True)
        return await super().find_start_run(session_id, idempotency_key, context)

    @cached_session_operation
    async def get_start_command(self, run_id):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        return await super().get_start_command(run_id)

    @cached_session_operation
    async def get_latest_checkpoint(self, run_id):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        return await super().get_latest_checkpoint(run_id)

    @cached_session_operation
    async def read_events(self, run_id, **kwargs):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        return await super().read_events(run_id, **kwargs)

    @cached_session_operation
    async def read_stream_previews(self, run_id, **kwargs):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        return await super().read_stream_previews(run_id, **kwargs)

    @cached_session_operation
    async def publish_stream_preview(self, *, run_id, **kwargs):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        return await super().publish_stream_preview(run_id=run_id, **kwargs)

    @cached_session_operation
    async def commit_model_stream_batch(self, *, run, drafts, context, idempotency_key):
        """Persist item starts; send model deltas from the in-process buffer."""

        return await self._commit_model_stream_with_previews(
            run=run,
            drafts=drafts,
            context=context,
            idempotency_key=idempotency_key,
        )

    @cached_session_operation
    async def read_fork_base_events(self, run_id):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        return await super().read_fork_base_events(run_id)

    @cached_session_operation
    async def commit_run(self, *, run_id, **kwargs):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        return await super().commit_run(run_id=run_id, **kwargs)

    @cached_session_operation
    async def propose_session_commit(self, command, context):
        await self._ensure_resource_loaded("runs", "run_id", command.run_id)
        return await super().propose_session_commit(command, context)

    @cached_session_operation
    async def publish_session_commit(self, command, context):
        await self._ensure_resource_loaded(
            "session_commit_proposals", "proposal_id", command.proposal_id
        )
        return await super().publish_session_commit(command, context)

    @cached_session_operation
    async def reject_session_commit(self, command, context):
        await self._ensure_resource_loaded(
            "session_commit_proposals", "proposal_id", command.proposal_id
        )
        return await super().reject_session_commit(command, context)

    @cached_session_operation
    async def get_session_commit_proposal(self, proposal_id):
        await self._ensure_resource_loaded(
            "session_commit_proposals", "proposal_id", proposal_id
        )
        return await super().get_session_commit_proposal(proposal_id)

    @cached_session_operation
    async def get_checkpoint(self, checkpoint_id):
        await self._ensure_resource_loaded(
            "checkpoints", "checkpoint_id", checkpoint_id
        )
        return await super().get_checkpoint(checkpoint_id)

    @cached_session_operation
    async def get_suspension(self, suspension_id):
        await self._ensure_resource_loaded(
            "suspensions", "suspension_id", suspension_id
        )
        return await super().get_suspension(suspension_id)

    @cached_session_operation
    async def get_interaction(self, interaction_id):
        await self._ensure_resource_loaded(
            "interactions", "interaction_id", interaction_id
        )
        return await super().get_interaction(interaction_id)

    @cached_session_operation
    async def get_interaction_resolution(self, interaction_id):
        await self._ensure_resource_loaded(
            "interactions", "interaction_id", interaction_id
        )
        return await super().get_interaction_resolution(interaction_id)

    @cached_session_operation
    async def enqueue_steer(self, command, context):
        await self._ensure_resource_loaded("runs", "run_id", command.run_id)
        return await super().enqueue_steer(command, context)

    @cached_session_operation
    async def claim_steers(self, *, run_id, **kwargs):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        return await super().claim_steers(run_id=run_id, **kwargs)

    @cached_session_operation
    async def list_steers(self, run_id):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        return await super().list_steers(run_id)

    @cached_session_operation
    async def resolve_interaction(self, command, context):
        await self._ensure_resource_loaded("runs", "run_id", command.run_id)
        return await super().resolve_interaction(command, context)

    @cached_session_operation
    async def request_resume(self, command, context):
        await self._ensure_resource_loaded("runs", "run_id", command.run_id)
        return await super().request_resume(command, context)

    async def subscribe_events(self, cursor):
        retained = None
        try:
            async with self._session_cache.operation():
                await self._ensure_resource_loaded("runs", "run_id", cursor.run_id)
                sid = self._runs[cursor.run_id].session_id
                self._session_cache.retain(sid)
                retained = sid
            # Close the coordinator iterator before dropping its cache pin, even
            # when the transport closes this generator from a different Task.
            async with aclosing(super().subscribe_events(cursor)) as events:
                async for event in events:
                    yield event
        finally:
            if retained is not None:
                self._session_cache.release(retained)
                await self._session_cache.prune()

    async def _ensure_session_loaded(
        self, session_id: str, *, missing_ok: bool = False
    ) -> None:
        self._session_cache.pin(session_id)
        if session_id in self._loaded_session_ids:
            return
        await self._ensure_ready()
        lock = self._load_locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            if session_id in self._loaded_session_ids:
                return
            payload = await self._fetch_session(session_id)
            if payload is None:
                if missing_ok:
                    return
                raise self._not_found("session.not_found", session_id)
            prepared = await asyncio.to_thread(self._prepare_session, payload)
            async with self._lock:
                if session_id not in self._loaded_session_ids:
                    self._install_session_locked(payload, prepared=prepared)

    async def _ensure_descendants_loaded(self, session_id: str) -> None:
        await self._ensure_ready()
        await self._ensure_sessions_loaded(await self._list_descendant_ids(session_id))

    async def _ensure_sessions_loaded(self, session_ids) -> None:
        """Install cold aggregates in batches while sharing single-load locks."""
        ids = tuple(sorted(set(session_ids)))
        for sid in ids:
            self._session_cache.pin(sid)
        missing = [sid for sid in ids if sid not in self._loaded_session_ids]
        if not missing:
            return
        await self._ensure_ready()
        async with AsyncExitStack() as locks:
            for sid in missing:
                await locks.enter_async_context(self._load_locks.setdefault(sid, asyncio.Lock()))
            # A single loader may have installed a Session while we acquired its
            # lock. Keep that live identity and fetch only still-cold Sessions.
            missing = [sid for sid in missing if sid not in self._loaded_session_ids]
            if not missing:
                return
            payloads = await self._fetch_sessions(missing)
            def prepare():
                return {sid: self._prepare_session(payloads[sid]) for sid in missing if sid in payloads}
            prepared = await asyncio.to_thread(prepare)
            async with self._lock:
                for sid in missing:
                    if sid in prepared and sid not in self._loaded_session_ids:
                        self._install_session_locked(payloads[sid], prepared=prepared[sid])

    async def _list_descendant_ids(self, session_id: str) -> list[str]:
        return await self.list_workspace_descendant_ids([session_id])

    async def _ensure_resource_loaded(
        self, collection: str, identity_key: str, identity: str
    ) -> None:
        if self._resource_is_loaded(collection, identity):
            row = getattr(self, "_" + collection)[identity]
            sid = getattr(row, "session_id", None) or self._runs[row.run_id].session_id
            self._session_cache.pin(sid)
            return
        await self._ensure_ready()
        session_id = await self._locate_session(identity_key, identity)
        if session_id is None:
            raise self._not_found(f"{identity_key}.not_found", identity)
        await self._ensure_session_loaded(session_id)
        if not self._resource_is_loaded(collection, identity):
            raise self._not_found(f"{identity_key}.not_found", identity)

    def _resource_is_loaded(self, collection: str, identity: str) -> bool:
        mappings = {
            "runs": self._runs,
            "checkpoints": self._checkpoints,
            "suspensions": self._suspensions,
            "interactions": self._interactions,
            "session_commit_proposals": self._session_commit_proposals,
        }
        return identity in mappings[collection]

    async def _locate_session(self, identity_key: str, identity: str) -> str | None:
        if identity_key == "run_id" and identity in self._runs:
            return self._runs[identity].session_id
        assert self._pool is not None
        async with self._reader_connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    f"""
                    SELECT session_id FROM {self._table("locations")}
                    WHERE kind = %s AND identity = %s
                    """,
                    (identity_key, identity),
                )
                row = await cursor.fetchone()
        return None if row is None else row[0]

    async def _read_start_lookup(self, command, context) -> str | None:
        assert self._pool is not None
        async with self._reader_connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    f"""
                    SELECT session_id FROM {self._table("start_idempotency")}
                    WHERE tenant_id = %s AND principal_id IN (%s, %s)
                      AND idempotency_key = %s
                    """,
                    (
                        str(context.actor.tenant_id or ""),
                        _principal_lookup_key(
                            context.actor.principal_type.value,
                            context.actor.principal_id,
                        ),
                        context.actor.principal_id,
                        command.idempotency_key,
                    ),
                )
                row = await cursor.fetchone()
        return None if row is None else row[0]

    async def export_session_state(self, session_id: str) -> dict[str, Any]:
        """Read one durable aggregate, including replayed mutations and Run events.

        Trusted host export tooling must authorize the Session before calling.
        This intentionally excludes unrelated Sessions and derived caches.
        """
        await self._ensure_ready()
        payload = await self._fetch_session(session_id)
        if payload is None:
            raise self._not_found("session.not_found", session_id)
        payload.pop("_mutation_count", None)
        return payload

    async def _fetch_session(self, session_id: str) -> dict[str, Any] | None:
        assert self._pool is not None
        async with self._reader_connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    f"""
                    SELECT compact_state, revision, last_sequence
                    FROM {self._table("sessions")}
                    WHERE session_id = %s
                    """,
                    (session_id,),
                )
                row = await cursor.fetchone()
                if row is None:
                    return None
                await cursor.execute(
                    f"""
                    SELECT revision, mutation FROM {self._table("session_mutations")}
                    WHERE session_id = %s ORDER BY revision
                    """,
                    (session_id,),
                )
                mutation_rows = await cursor.fetchall()
                await cursor.execute(
                    f"""
                    SELECT run_id, event FROM {self._table("run_events")}
                    WHERE session_id = %s
                    ORDER BY run_id, run_sequence
                    """,
                    (session_id,),
                )
                event_rows = await cursor.fetchall()
        return await asyncio.to_thread(self._decode_session_rows, row, mutation_rows, event_rows)

    def _decode_session_rows(self, row, mutation_rows, event_rows):
        payload = self._replay_mutations(
            dict(_decode_json(row[0])), mutation_rows, int(row[1]), int(row[2]))
        payload["_mutation_count"] = len(mutation_rows)
        run_events: dict[str, list[dict[str, Any]]] = {}
        for run_id, event in event_rows:
            run_events.setdefault(run_id, []).append(_decode_json(event))
        payload["run_events"] = run_events
        return payload

    async def _fetch_sessions(self, session_ids) -> dict[str, dict[str, Any]]:
        """Read canonical aggregates with three SELECTs per 128 Session IDs."""
        ids = tuple(dict.fromkeys(session_ids))
        result = {}
        if not ids:
            return result
        async with self._reader_connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                await connection.begin()
                for start in range(0, len(ids), 128):
                    batch = ids[start:start + 128]
                    marks = ",".join(["%s"] * len(batch))
                    await cursor.execute(
                        f"SELECT session_id, compact_state, revision, last_sequence "
                        f"FROM {self._table('sessions')} WHERE session_id IN ({marks})", batch)
                    bases = await cursor.fetchall()
                    await cursor.execute(
                        f"SELECT session_id, revision, mutation FROM {self._table('session_mutations')} "
                        f"WHERE session_id IN ({marks}) ORDER BY session_id, revision", batch)
                    mutations = await cursor.fetchall()
                    await cursor.execute(
                        f"SELECT session_id, run_id, event FROM {self._table('run_events')} "
                        f"WHERE session_id IN ({marks}) ORDER BY session_id, run_id, run_sequence", batch)
                    events = await cursor.fetchall()
                    def decode():
                        mutation_rows, event_rows = {}, {}
                        for sid, revision, mutation in mutations:
                            mutation_rows.setdefault(sid, []).append((revision, mutation))
                        for sid, rid, event in events:
                            event_rows.setdefault(sid, []).append((rid, event))
                        decoded = {}
                        for sid, *row in bases:
                            payload = self._decode_session_rows(
                                row, mutation_rows.get(sid, ()), event_rows.get(sid, ()))
                            if payload["sessions"][0]["session_id"] != sid:
                                raise SessionStoreCorruptionError(RuntimeErrorInfo(
                                    code="session_store.aggregate_corrupt",
                                    category=ErrorCategory.CORRUPT_STATE,
                                    message="mysql Session snapshot identity disagrees with its row",
                                    safe_to_resume=False,
                                ))
                            decoded[sid] = payload
                        return decoded
                    result.update(await asyncio.to_thread(decode))
        return result

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

    @staticmethod
    def _replay_mutations(compact, mutation_rows, revision, last_sequence):
        try:
            aggregate = SessionAggregate(
                SessionAggregateSnapshotV2.model_validate(compact)
            )
            current_revision = aggregate.revision
            revision_sequences = dict(aggregate.snapshot.sessions[0].revision_sequences)
            def mutations():
                nonlocal current_revision
                for next_revision, encoded in mutation_rows:
                    if int(next_revision) != current_revision + 1:
                        raise ValueError("non-contiguous Session mutation revisions")
                    delta = dict(_decode_json(encoded))
                    session_rows = delta.get("upserts", {}).get("sessions", ())
                    if len(session_rows) != 1 or int(session_rows[0]["revision"]) != int(next_revision):
                        raise ValueError("Session mutation has an invalid head")
                    head = SessionRowSnapshot.model_validate(session_rows[0])
                    revision_sequences.update(head.revision_sequences)
                    current_revision = int(next_revision)
                    yield SessionStateDeltaMutation(**delta)
            aggregate = aggregate.apply_many(mutations())
            state = aggregate.snapshot.model_dump(mode="json")
            state["sessions"][0]["revision_sequences"] = revision_sequences
            if (
                current_revision != revision
                or state["sessions"][0]["last_sequence"] != last_sequence
            ):
                raise ValueError("Session head disagrees with its mutations")
            return state
        except (KeyError, TypeError, ValueError) as exc:
            raise SessionStoreCorruptionError(
                RuntimeErrorInfo(
                    code="session_store.aggregate_corrupt",
                    category=ErrorCategory.CORRUPT_STATE,
                    message=f"mysql Session mutations are invalid: {exc}",
                    safe_to_resume=False,
                )
            ) from exc

    async def _reload_session_from_storage_locked(self, session_id: str) -> None:
        # Keep the aggregate installed during I/O. Otherwise lazy readers can
        # install it in the eviction gap and recovery installs it a second time.
        # The caller holds the Session operation lock; replacement of the shared
        # state must also be atomic with respect to other Session loaders.
        payload = await self._fetch_session(session_id)
        prepared = await asyncio.to_thread(self._prepare_session, payload) if payload is not None else None
        async with self._lock:
            if session_id in self._sessions:
                self._evict_session_locked(session_id)
            if payload is not None:
                self._install_session_locked(payload, prepared=prepared)

    def _evict_session_locked(self, session_id: str) -> None:
        run_ids = self._session_run_ids_locked(session_id)
        self._drop_session_objects_locked(session_id)
        self._forget_persisted_session(session_id)
        # MySQL owns the durable projection. Releasing its redundant process
        # copy must not call forget_session(), which deletes the durable row.
        self._derived_state = {key: value for key, value in self._derived_state.items()
                               if key[0] != session_id}
        lock = self._session_locks.get(session_id)
        if not self._session_cache.users.get(session_id) and lock is not None and not lock.locked():
            self._session_locks.pop(session_id, None)
        for run_id in run_ids:
            if not self._subscribers.get(run_id):
                self._subscribers.pop(run_id, None)

    def _forget_persisted_session(self, session_id: str) -> None:
        self._session_cache.forget(session_id)
        self._loaded_session_ids.discard(session_id)
        self._persisted_session_revisions.pop(session_id, None)
        self._persisted_mutation_counts.pop(session_id, None)
        self._persisted_locations.pop(session_id, None)
        self._persisted_start_keys.pop(session_id, None)
        for run_id in self._persisted_session_runs.pop(session_id, set()):
            self._persisted_run_sequences.pop(run_id, None)

    def _remember_persisted_session(
        self,
        session_id: str,
        revision: int,
        run_sequences: dict[str, int],
        location_rows: set[tuple[str, str, str]],
        start_rows: set[tuple[str, ...]],
        mutation_count: int,
    ) -> None:
        previous = self._persisted_session_runs.get(session_id, set())
        for run_id in previous - set(run_sequences):
            self._persisted_run_sequences.pop(run_id, None)
        self._loaded_session_ids.add(session_id)
        self._persisted_session_revisions[session_id] = revision
        self._persisted_mutation_counts[session_id] = mutation_count
        self._persisted_session_runs[session_id] = set(run_sequences)
        self._persisted_run_sequences.update(run_sequences)
        self._persisted_locations[session_id] = location_rows
        self._persisted_start_keys[session_id] = start_rows
        self._session_cache.pin(session_id)
        self._session_cache.evicted_suspended.discard(session_id)

    @staticmethod
    def _prepare_session(payload: dict[str, Any]) -> tuple[SessionStoreCoordinator, int]:
        """Validate one isolated aggregate without touching live coordinator rows."""
        session_rows = payload.get("sessions", ())
        if len(session_rows) != 1:
            raise SessionStoreCorruptionError(
                RuntimeErrorInfo(
                    code="session_store.aggregate_corrupt",
                    category=ErrorCategory.CORRUPT_STATE,
                    message="mysql snapshot does not contain exactly one Session",
                    safe_to_resume=False,
                )
            )
        prepared = SessionStoreCoordinator()
        prepared._load_state_locked(payload)
        return prepared, 4 * len(_json(payload).encode())

    def _install_session_locked(self, payload: dict[str, Any], *, prepared=None) -> None:
        prepared, cache_bytes = prepared if prepared is not None else self._prepare_session(payload)
        session_id = payload["sessions"][0]["session_id"]
        # Publish only this Session. Replacing the complete coordinator would
        # invalidate unrelated writers' row references across their DB awaits.
        names = (
            "_sessions", "_runs", "_run_events", "_session_events", "_fork_base_events",
            "_start_idempotency", "_start_idempotency_digests", "_command_results",
            "_command_digests", "_execution_resources", "_execution_resource_command_results",
            "_execution_resource_command_digests", "_checkpoints", "_suspensions",
            "_interactions", "_interaction_resolutions", "_steer_inbox",
            "_session_commit_proposals", "_session_commit_command_results",
            "_session_commit_command_digests",
        )
        for name in names:
            if getattr(self, name).keys() & getattr(prepared, name).keys():
                # All collision checks precede publication, leaving live state
                # intact if a stored identity belongs to another Session.
                raise SessionStoreCorruptionError(
                    RuntimeErrorInfo(
                        code="session_store.aggregate_duplicate",
                        category=ErrorCategory.CORRUPT_STATE,
                        message=f"duplicate aggregate identities in {name}",
                        safe_to_resume=False,
                    )
                )
        for name in names:
            getattr(self, name).update(getattr(prepared, name))
        self._remember_persisted_session(
            session_id,
            int(payload["sessions"][0]["revision"]),
            {
                run_id: len(events)
                for run_id, events in payload.get("run_events", {}).items()
            },
            self._location_rows(session_id, payload),
            self._start_key_rows(session_id, payload),
            int(payload.get("_mutation_count", 0)),
        )
        self._session_cache.touch(session_id, size=cache_bytes)

    @staticmethod
    def _compact_state(state: dict[str, Any]) -> dict[str, Any]:
        compact = {"session_format_version": state["session_format_version"]}
        for key in _COMPACT_LISTS:
            compact[key] = deepcopy(state.get(key, []))
        for key in _COMPACT_MAPS:
            compact[key] = deepcopy(state.get(key, {}))
        return compact


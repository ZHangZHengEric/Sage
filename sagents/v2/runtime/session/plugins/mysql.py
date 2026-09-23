"""Optional MySQL SessionStore.

The coordinator still owns sequencing, idempotency, and legal transitions.
This adapter persists one Session tree at a time and appends Run events.
There is no global Session index or cross-process subscribe.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from contextlib import asynccontextmanager
from copy import deepcopy
from typing import Any
from urllib.parse import unquote, urlparse

from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)
from sagents.v2.contracts.run_state import RunState, TERMINAL_RUN_STATES
from sagents.v2.runtime.session.aggregate import SessionAggregate
from sagents.v2.runtime.session.journal import (
    SessionAggregateSnapshotV2,
    SessionStateDeltaMutation,
)
from sagents.v2.runtime.session.state import SessionStoreCoordinator


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
)
LOGGER = logging.getLogger(__name__)


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


class _MysqlSessionState(SessionStoreCoordinator):
    """Single-process MySQL adapter around the shared state coordinator."""

    format_version = "sage.session.mysql/v2"
    snapshot_interval = 256

    def __init__(
        self,
        dsn: str,
        *,
        table_prefix: str | None = None,
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
        self._init_lock = asyncio.Lock()
        self._load_lock = asyncio.Lock()
        self._loaded_session_ids: set[str] = set()
        self._persisted_run_sequences: dict[str, int] = {}
        self._persisted_session_runs: dict[str, set[str]] = {}
        self._persisted_session_revisions: dict[str, int] = {}
        self._persisted_mutation_counts: dict[str, int] = {}
        self._persisted_locations: dict[str, set[tuple[str, str, str]]] = {}
        self._persisted_start_keys: dict[str, set[tuple[str, ...]]] = {}
        self._closed = False
        super().__init__(**kwargs)

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
                maxsize=0,
                **self._connect_kwargs,
            )
            try:
                async with pool.acquire() as connection:
                    created = await self._bootstrap(connection)
                LOGGER.info(
                    "mysql session store ready prefix=%s created=%s",
                    self.table_prefix,
                    created,
                )
            except Exception:
                pool.close()
                await pool.wait_closed()
                raise
            self._pool = pool

    @asynccontextmanager
    async def _writer_connection(self):
        await self._ensure_ready()
        pool = self._pool
        assert pool is not None
        async with pool.acquire() as connection:
            yield connection

    @asynccontextmanager
    async def _reader_connection(self):
        await self._ensure_ready()
        pool = self._pool
        assert pool is not None
        async with pool.acquire() as connection:
            try:
                yield connection
            finally:
                await connection.rollback()

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
                PRIMARY KEY (session_id)
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
            await pool.wait_closed()

    async def _commit_storage_locked(self, session_id: str) -> None:
        await self._ensure_ready()
        mutation = self._session_mutation_locked().model_dump(mode="json", exclude={"kind"})
        location_rows = self._location_rows_after_mutation(session_id, mutation)
        start_rows = self._start_rows_after_mutation(session_id, mutation)
        appended = mutation["appends"].pop("run_events", {})
        replaced = mutation["replacements"].pop("run_events", {})
        mutation["map_deletes"].pop("run_events", None)
        run_ids = self._session_run_ids_locked(session_id)
        event_totals = {
            run_id: len(self._run_events[run_id]) for run_id in run_ids
        }
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
        started_at = time.perf_counter()
        async with self._writer_connection() as connection:
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
                            INSERT INTO {self._table('session_mutations')}
                                (session_id, revision, mutation)
                            VALUES (%s, %s, CAST(%s AS JSON))
                            """,
                            (session_id, new_revision, encoded_mutation),
                        )
                    await self._sync_locations(cursor, session_id, location_rows)
                    await self._sync_start_idempotency(cursor, session_id, start_rows)
                await connection.commit()
            except Exception as exc:
                try:
                    await connection.rollback()
                except Exception:
                    LOGGER.exception("mysql session rollback failed")
                failure = exc
        if failure is not None:
            await self._reload_session_from_storage_locked(session_id)
            raise failure
        self._remember_persisted_session(
            session_id,
            new_revision,
            next_run_sequences,
            location_rows,
            start_rows,
            0 if should_snapshot else self._persisted_mutation_counts.get(session_id, 0) + 1,
        )
        if LOGGER.isEnabledFor(logging.DEBUG):
            LOGGER.debug(
                "mysql session commit session=%s revision=%s snapshot=%s payload_bytes=%s event_count=%s duration_ms=%.2f",
                session_id,
                new_revision,
                should_snapshot,
                len((encoded_compact or encoded_mutation or "").encode("utf-8")),
                sum(len(rows) for rows in events.values()),
                (time.perf_counter() - started_at) * 1000,
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
            row[:3]: row
            for row in self._persisted_start_keys.get(session_id, set())
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
                DELETE FROM {self._table('start_idempotency')}
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
                except Exception:
                    LOGGER.exception("mysql session rollback failed")
                raise
        for value in deleted_session_ids:
            self._forget_persisted_session(value)

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

    async def put_derived_state(
        self, session_id: str, namespace: str, key: str, value: Any
    ) -> None:
        await self._ensure_session_loaded(session_id)
        await super().put_derived_state(session_id, namespace, key, value)
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
                except Exception:
                    LOGGER.exception("mysql session rollback failed")
                raise

    async def delete_derived_state(
        self, session_id: str, namespace: str, key: str
    ) -> None:
        await self._ensure_session_loaded(session_id)
        await super().delete_derived_state(session_id, namespace, key)
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
                except Exception:
                    LOGGER.exception("mysql session rollback failed")
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
                except Exception:
                    LOGGER.exception("mysql session rollback failed")
                raise

    async def create_run(self, command, context):
        await self._ensure_ready()
        if command.session_id is not None:
            await self._ensure_session_loaded(command.session_id, missing_ok=True)
        else:
            lookup = await self._read_start_lookup(command, context)
            if lookup is not None:
                await self._ensure_session_loaded(lookup)
        return await super().create_run(command, context)

    async def get_session(self, session_id):
        await self._ensure_session_loaded(session_id)
        return await super().get_session(session_id)

    async def delete_session(self, session_id):
        await self._ensure_session_loaded(session_id)
        await self._ensure_descendants_loaded(session_id)
        result = await super().delete_session(session_id)
        self._loaded_session_ids.intersection_update(self._sessions)
        return result

    async def list_session_runs(self, session_id):
        await self._ensure_session_loaded(session_id)
        return await super().list_session_runs(session_id)

    async def list_descendant_sessions(self, session_id):
        await self._ensure_session_loaded(session_id)
        await self._ensure_descendants_loaded(session_id)
        return await super().list_descendant_sessions(session_id)

    async def read_session_events(self, session_id, **kwargs):
        await self._ensure_session_loaded(session_id)
        return await super().read_session_events(session_id, **kwargs)

    async def list_session_commit_proposals(self, session_id):
        await self._ensure_session_loaded(session_id)
        return await super().list_session_commit_proposals(session_id)

    async def get_run(self, run_id):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        return await super().get_run(run_id)

    async def get_run_result(self, run_id):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        return await super().get_run_result(run_id)

    async def get_start_command(self, run_id):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        return await super().get_start_command(run_id)

    async def get_latest_checkpoint(self, run_id):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        return await super().get_latest_checkpoint(run_id)

    async def read_events(self, run_id, **kwargs):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        return await super().read_events(run_id, **kwargs)

    async def read_stream_previews(self, run_id, **kwargs):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        return await super().read_stream_previews(run_id, **kwargs)

    async def publish_stream_preview(self, *, run_id, **kwargs):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        return await super().publish_stream_preview(run_id=run_id, **kwargs)

    async def commit_model_stream_batch(
        self, *, run, drafts, context, idempotency_key
    ):
        """Persist item starts; send model deltas from the in-process buffer."""

        started = tuple(
            draft for draft in drafts
            if draft.type in {"message.started", "reasoning.started"}
        )
        previews = tuple(
            draft for draft in drafts
            if draft.type in {"message.delta", "reasoning.delta"}
        )
        if started:
            run = await self._commit_model_stream_drafts(
                run=run,
                drafts=started,
                context=context,
                idempotency_key=idempotency_key,
                expected_states={run.state},
                return_terminal_on_conflict=False,
            )
        if not previews:
            return run
        try:
            return await self.publish_stream_preview(
                run_id=run.run_id,
                expected_revision=run.revision,
                drafts=previews,
                context=context,
            )
        except SageV2Error as exc:
            if exc.info.category != ErrorCategory.CONFLICT:
                raise
            latest = await self.get_run(run.run_id)
            if latest.state in TERMINAL_RUN_STATES:
                return latest
            if latest.state not in {RunState.RUNNING, RunState.SUSPEND_REQUESTED}:
                raise
            return await self.publish_stream_preview(
                run_id=latest.run_id,
                expected_revision=latest.revision,
                drafts=previews,
                context=context,
            )

    async def read_fork_base_events(self, run_id):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        return await super().read_fork_base_events(run_id)

    async def commit_run(self, *, run_id, **kwargs):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        return await super().commit_run(run_id=run_id, **kwargs)

    async def propose_session_commit(self, command, context):
        await self._ensure_resource_loaded("runs", "run_id", command.run_id)
        return await super().propose_session_commit(command, context)

    async def publish_session_commit(self, command, context):
        await self._ensure_resource_loaded(
            "session_commit_proposals", "proposal_id", command.proposal_id
        )
        return await super().publish_session_commit(command, context)

    async def reject_session_commit(self, command, context):
        await self._ensure_resource_loaded(
            "session_commit_proposals", "proposal_id", command.proposal_id
        )
        return await super().reject_session_commit(command, context)

    async def get_session_commit_proposal(self, proposal_id):
        await self._ensure_resource_loaded(
            "session_commit_proposals", "proposal_id", proposal_id
        )
        return await super().get_session_commit_proposal(proposal_id)

    async def get_checkpoint(self, checkpoint_id):
        await self._ensure_resource_loaded(
            "checkpoints", "checkpoint_id", checkpoint_id
        )
        return await super().get_checkpoint(checkpoint_id)

    async def get_suspension(self, suspension_id):
        await self._ensure_resource_loaded(
            "suspensions", "suspension_id", suspension_id
        )
        return await super().get_suspension(suspension_id)

    async def get_interaction(self, interaction_id):
        await self._ensure_resource_loaded(
            "interactions", "interaction_id", interaction_id
        )
        return await super().get_interaction(interaction_id)

    async def get_interaction_resolution(self, interaction_id):
        await self._ensure_resource_loaded(
            "interactions", "interaction_id", interaction_id
        )
        return await super().get_interaction_resolution(interaction_id)

    async def enqueue_steer(self, command, context):
        await self._ensure_resource_loaded("runs", "run_id", command.run_id)
        return await super().enqueue_steer(command, context)

    async def claim_steers(self, *, run_id, **kwargs):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        return await super().claim_steers(run_id=run_id, **kwargs)

    async def list_steers(self, run_id):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        return await super().list_steers(run_id)

    async def resolve_interaction(self, command, context):
        await self._ensure_resource_loaded("runs", "run_id", command.run_id)
        return await super().resolve_interaction(command, context)

    async def request_resume(self, command, context):
        await self._ensure_resource_loaded("runs", "run_id", command.run_id)
        return await super().request_resume(command, context)

    async def subscribe_events(self, cursor):
        await self._ensure_resource_loaded("runs", "run_id", cursor.run_id)
        async for event in super().subscribe_events(cursor):
            yield event

    async def _ensure_session_loaded(
        self, session_id: str, *, missing_ok: bool = False
    ) -> None:
        if session_id in self._loaded_session_ids:
            return
        await self._ensure_ready()
        async with self._load_lock:
            if session_id in self._loaded_session_ids:
                return
            payload = await self._fetch_session(session_id)
            if payload is None:
                if missing_ok:
                    return
                raise self._not_found("session.not_found", session_id)
            async with self._lock:
                self._install_session_locked(payload)

    async def _ensure_descendants_loaded(self, session_id: str) -> None:
        await self._ensure_ready()
        for child_id in await self._list_descendant_ids(session_id):
            await self._ensure_session_loaded(child_id, missing_ok=True)

    async def _list_descendant_ids(self, session_id: str) -> list[str]:
        assert self._pool is not None
        found: list[str] = []
        frontier = [session_id]
        seen = {session_id}
        async with self._reader_connection() as connection:
            async with connection.cursor() as cursor:
                while frontier:
                    current = frontier.pop()
                    await cursor.execute(
                        f"""
                        SELECT session_id FROM {self._table("sessions")}
                        WHERE parent_session_id = %s
                        """,
                        (current,),
                    )
                    for (child_id,) in await cursor.fetchall():
                        if child_id in seen:
                            continue
                        seen.add(child_id)
                        found.append(child_id)
                        frontier.append(child_id)
        return found

    async def _ensure_resource_loaded(
        self, collection: str, identity_key: str, identity: str
    ) -> None:
        if self._resource_is_loaded(collection, identity):
            return
        await self._ensure_ready()
        async with self._load_lock:
            if self._resource_is_loaded(collection, identity):
                return
            session_id = await self._locate_session(identity_key, identity)
            if session_id is None:
                raise self._not_found(f"{identity_key}.not_found", identity)
            payload = await self._fetch_session(session_id)
            if payload is None:
                raise self._not_found(f"{identity_key}.not_found", identity)
            async with self._lock:
                if session_id not in self._loaded_session_ids:
                    self._install_session_locked(payload)

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
        payload = self._replay_mutations(
            dict(_decode_json(row[0])), mutation_rows, int(row[1]), int(row[2])
        )
        payload["_mutation_count"] = len(mutation_rows)
        run_events: dict[str, list[dict[str, Any]]] = {}
        for run_id, event in event_rows:
            run_events.setdefault(run_id, []).append(_decode_json(event))
        payload["run_events"] = run_events
        return payload

    @staticmethod
    def _replay_mutations(compact, mutation_rows, revision, last_sequence):
        try:
            aggregate = SessionAggregate(SessionAggregateSnapshotV2.model_validate(compact))
            current_revision = aggregate.revision
            for next_revision, encoded in mutation_rows:
                if int(next_revision) != current_revision + 1:
                    raise ValueError("non-contiguous Session mutation revisions")
                delta = dict(_decode_json(encoded))
                session_rows = delta.get("upserts", {}).get("sessions", ())
                if len(session_rows) != 1 or int(session_rows[0]["revision"]) != int(next_revision):
                    raise ValueError("Session mutation has an invalid head")
                head = dict(session_rows[0])
                head["revision_sequences"] = {
                    **aggregate.snapshot.sessions[0].revision_sequences,
                    **head["revision_sequences"],
                }
                delta["upserts"]["sessions"] = [head]
                aggregate = aggregate.apply(SessionStateDeltaMutation(**delta))
                current_revision = int(next_revision)
            state = aggregate.snapshot.model_dump(mode="json")
            if current_revision != revision or state["sessions"][0]["last_sequence"] != last_sequence:
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
        if session_id in self._sessions:
            self._evict_session_locked(session_id)
        payload = await self._fetch_session(session_id)
        if payload is not None:
            self._install_session_locked(payload)

    def _evict_session_locked(self, session_id: str) -> None:
        combined = self._filter_session_state(self._dump_state_locked(), session_id)
        subscribers = self._subscribers
        derived = self._derived_state
        self._load_state_locked(combined)
        self._subscribers.update(subscribers)
        self._derived_state.update(derived)
        self._forget_persisted_session(session_id)

    def _forget_persisted_session(self, session_id: str) -> None:
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

    def _install_session_locked(self, payload: dict[str, Any]) -> None:
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
        session_id = session_rows[0]["session_id"]
        combined = self._dump_state_locked()
        try:
            self._merge_state(combined, payload)
        except ValueError as exc:
            raise SessionStoreCorruptionError(
                RuntimeErrorInfo(
                    code="session_store.aggregate_duplicate",
                    category=ErrorCategory.CORRUPT_STATE,
                    message=str(exc),
                    safe_to_resume=False,
                )
            ) from exc
        subscribers = self._subscribers
        derived = self._derived_state
        self._load_state_locked(combined)
        self._subscribers.update(subscribers)
        self._derived_state.update(derived)
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

    @staticmethod
    def _compact_state(state: dict[str, Any]) -> dict[str, Any]:
        compact = {"session_format_version": state["session_format_version"]}
        for key in _COMPACT_LISTS:
            compact[key] = deepcopy(state.get(key, []))
        for key in _COMPACT_MAPS:
            compact[key] = deepcopy(state.get(key, {}))
        return compact

    @staticmethod
    def _filter_session_state(state: dict[str, Any], session_id: str) -> dict[str, Any]:
        run_ids = {
            row["run_id"]
            for row in state.get("runs", ())
            if row.get("session_id") == session_id
        }
        filtered = {
            "session_format_version": state["session_format_version"],
            "sessions": [
                row
                for row in state.get("sessions", ())
                if row.get("session_id") != session_id
            ],
            "runs": [
                row
                for row in state.get("runs", ())
                if row.get("session_id") != session_id
            ],
            "run_events": {
                run_id: events
                for run_id, events in state.get("run_events", {}).items()
                if run_id not in run_ids
            },
            "fork_base_events": {
                run_id: events
                for run_id, events in state.get("fork_base_events", {}).items()
                if run_id not in run_ids
            },
            "steer_inbox": {
                run_id: events
                for run_id, events in state.get("steer_inbox", {}).items()
                if run_id not in run_ids
            },
            "start_idempotency": [
                row
                for row in state.get("start_idempotency", ())
                if row.get("run_id") not in run_ids
            ],
            "command_results": [
                row
                for row in state.get("command_results", ())
                if row.get("run_id") not in run_ids
            ],
            "execution_resources": [
                row
                for row in state.get("execution_resources", ())
                if row.get("run_id") not in run_ids
            ],
            "execution_resource_command_results": [
                row
                for row in state.get("execution_resource_command_results", ())
                if row.get("run_id") not in run_ids
            ],
            "checkpoints": [
                row
                for row in state.get("checkpoints", ())
                if row.get("run_id") not in run_ids
            ],
            "suspensions": [
                row
                for row in state.get("suspensions", ())
                if row.get("run_id") not in run_ids
            ],
            "interactions": [
                row
                for row in state.get("interactions", ())
                if row.get("run_id") not in run_ids
            ],
            "session_commit_proposals": [
                row
                for row in state.get("session_commit_proposals", ())
                if row.get("session_id") != session_id
            ],
        }
        evicted_proposal_ids = {
            row.get("proposal_id")
            for row in state.get("session_commit_proposals", ())
            if row.get("session_id") == session_id
        }
        interaction_ids = {
            row.get("interaction_id") for row in filtered["interactions"]
        }
        filtered["interaction_resolutions"] = [
            row
            for row in state.get("interaction_resolutions", ())
            if row.get("interaction_id") in interaction_ids
        ]
        filtered["session_commit_command_results"] = [
            row
            for row in state.get("session_commit_command_results", ())
            if row.get("target_id") not in run_ids
            and row.get("proposal", {}).get("proposal_id") not in evicted_proposal_ids
        ]
        return filtered

    @staticmethod
    def _merge_state(target: dict[str, Any], source: dict[str, Any]) -> None:
        for key in _COMPACT_LISTS:
            target[key].extend(source.get(key, ()))
        for key in ("run_events", *_COMPACT_MAPS):
            overlap = set(target[key]) & set(source.get(key, {}))
            if overlap:
                raise ValueError(f"duplicate aggregate identities: {sorted(overlap)}")
            target[key].update(source.get(key, {}))


class _MysqlSessionStoreMeta(type):
    def __getattr__(cls, name):
        return getattr(_MysqlSessionState, name)


class MysqlSessionStore(metaclass=_MysqlSessionStoreMeta):
    """Composed durable MySQL SessionStore facade."""

    plugin_id = "sage.session.mysql"
    name = "MySQL SessionStore"
    description = (
        "Durable per-Session MySQL store with appended Run events. "
        "No global Session index."
    )

    def __init__(self, *args, **kwargs) -> None:
        object.__setattr__(self, "_coordinator", _MysqlSessionState(*args, **kwargs))

    async def start(self, context, dependencies):
        del context, dependencies
        await self._coordinator._ensure_ready()
        return {"session.store": self}

    def __getattr__(self, name):
        return getattr(self._coordinator, name)

    def __setattr__(self, name, value) -> None:
        if name == "_coordinator":
            object.__setattr__(self, name, value)
        else:
            setattr(self._coordinator, name, value)


__all__ = [
    "MysqlSessionStore",
    "SessionStoreCorruptionError",
    "parse_mysql_dsn",
]

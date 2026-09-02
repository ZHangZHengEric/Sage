"""Optional single-process MySQL SessionStore.

The coordinator still owns sequencing, idempotency, and legal transitions.
This adapter persists one Session tree at a time, appends Run events, and
rejects a second writer with GET_LOCK. There is no global Session index and
no cross-process subscribe.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from contextlib import asynccontextmanager
from copy import deepcopy
from typing import Any
from urllib.parse import unquote, urlparse

from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)
from sagents.v2.runtime.session.state import SessionStoreCoordinator


def _principal_lookup_key(principal_type: str, principal_id: str) -> str:
    identity = f"{principal_type}\0{principal_id}".encode("utf-8")
    return f"typed:{hashlib.sha256(identity).hexdigest()}"


class StoreInUseError(SageV2Error):
    """Raised when another writer already owns the same MySQL prefix."""


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

    format_version = "sage.session.mysql/v1"

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
        self._lock_conn = None
        self._init_lock = asyncio.Lock()
        self._writer_connection_lock = asyncio.Lock()
        self._writer_lock_lost = False
        self._load_lock = asyncio.Lock()
        self._loaded_session_ids: set[str] = set()
        self._persisted_run_sequences: dict[str, int] = {}
        self._persisted_session_runs: dict[str, set[str]] = {}
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

    @property
    def lock_name(self) -> str:
        scope = f"{self._connect_kwargs['db']}:{self.table_prefix}"
        digest = hashlib.sha256(scope.encode("utf-8")).hexdigest()[:24]
        return f"sage_sess_mysql_{digest}"

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
        if self._writer_lock_lost:
            raise self._writer_lock_lost_error()
        if self._pool is not None:
            if self._lock_conn is None or self._lock_conn.closed:
                self._writer_lock_lost = True
                raise self._writer_lock_lost_error()
            return
        async with self._init_lock:
            if self._writer_lock_lost:
                raise self._writer_lock_lost_error()
            if self._pool is not None:
                if self._lock_conn is None or self._lock_conn.closed:
                    self._writer_lock_lost = True
                    raise self._writer_lock_lost_error()
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
            lock_conn = await aiomysql.connect(**self._connect_kwargs)
            try:
                await self._acquire_writer_lock(lock_conn)
                created = await self._bootstrap(lock_conn)
                pool = await aiomysql.create_pool(
                    minsize=1,
                    maxsize=8,
                    **self._connect_kwargs,
                )
                LOGGER.info(
                    "mysql session store ready prefix=%s created=%s",
                    self.table_prefix,
                    created,
                )
            except Exception:
                await self._close_lock_conn(lock_conn)
                raise
            self._lock_conn = lock_conn
            self._pool = pool

    def _writer_lock_lost_error(self) -> SageV2Error:
        return SageV2Error(
            RuntimeErrorInfo(
                code="session_store.writer_lock_lost",
                category=ErrorCategory.RESOURCE_LOST,
                message="mysql SessionStore lost its single-writer lock connection",
                safe_to_resume=True,
            )
        )

    @asynccontextmanager
    async def _writer_connection(self):
        await self._ensure_ready()
        async with self._writer_connection_lock:
            connection = self._lock_conn
            if connection is None or connection.closed:
                self._writer_lock_lost = True
                raise self._writer_lock_lost_error()
            try:
                yield connection
            except BaseException:
                if connection.closed:
                    self._writer_lock_lost = True
                raise

    async def _acquire_writer_lock(self, connection) -> None:
        async with connection.cursor() as cursor:
            await cursor.execute("SELECT GET_LOCK(%s, 0)", (self.lock_name,))
            row = await cursor.fetchone()
        if not row or int(row[0] or 0) != 1:
            raise StoreInUseError(
                RuntimeErrorInfo(
                    code="session_store.in_use",
                    category=ErrorCategory.CONFLICT,
                    message=(
                        "mysql SessionStore prefix is already owned: "
                        f"{self.table_prefix}"
                    ),
                    safe_to_resume=True,
                )
            )

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
            CREATE TABLE {self._table("sessions")} (
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
                "run_events",
                f"""
            CREATE TABLE {self._table("run_events")} (
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
            CREATE TABLE {self._table("locations")} (
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
            CREATE TABLE {self._table("start_idempotency")} (
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
            CREATE TABLE {self._table("derived_state")} (
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
        async with self._writer_connection_lock:
            pool = self._pool
            lock_conn = self._lock_conn
            self._pool = None
            self._lock_conn = None
            if pool is not None:
                pool.close()
                await pool.wait_closed()
            await self._close_lock_conn(lock_conn)

    async def _close_lock_conn(self, connection) -> None:
        if connection is None or connection.closed:
            return
        try:
            async with connection.cursor() as cursor:
                await cursor.execute("SELECT RELEASE_LOCK(%s)", (self.lock_name,))
        finally:
            connection.close()

    async def _commit_storage_locked(self, session_id: str) -> None:
        await self._ensure_ready()
        state = self._dump_session_state_locked(session_id)
        compact = self._compact_state(state)
        session_row = compact["sessions"][0]
        events = {
            run_id: list(rows)
            for run_id, rows in state.get("run_events", {}).items()
        }
        next_run_sequences: dict[str, int] = {}
        async with self._writer_connection() as connection:
            try:
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        f"""
                        INSERT INTO {self._table("sessions")} (
                            session_id, parent_session_id, revision,
                            last_sequence, created_at, updated_at, compact_state
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, CAST(%s AS JSON)) AS incoming
                        ON DUPLICATE KEY UPDATE
                            parent_session_id = incoming.parent_session_id,
                            revision = incoming.revision,
                            last_sequence = incoming.last_sequence,
                            updated_at = incoming.updated_at,
                            compact_state = incoming.compact_state
                        """,
                        (
                            session_row["session_id"],
                            session_row.get("parent_session_id"),
                            int(session_row["revision"]),
                            int(session_row["last_sequence"]),
                            _datetime(session_row["created_at"]),
                            _datetime(session_row["updated_at"]),
                            _json(compact),
                        ),
                    )
                    next_run_sequences = await self._persist_events(
                        cursor, session_id, events
                    )
                    await self._replace_locations(cursor, session_id, compact)
                    await self._replace_start_idempotency(cursor, session_id, compact)
                await connection.commit()
            except Exception:
                try:
                    await connection.rollback()
                except Exception:
                    self._writer_lock_lost = True
                await self._reload_session_from_storage_locked(session_id)
                raise
        self._remember_persisted_session(session_id, next_run_sequences)

    async def _persist_events(self, cursor, session_id, events) -> dict[str, int]:
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
            if persisted > len(rows):
                await cursor.execute(
                    f"DELETE FROM {self._table('run_events')} WHERE run_id = %s",
                    (run_id,),
                )
                persisted = 0
            appended = rows[persisted:]
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
            next_sequences[run_id] = len(rows)
        return next_sequences

    async def _replace_locations(self, cursor, session_id, compact) -> None:
        await cursor.execute(
            f"DELETE FROM {self._table('locations')} WHERE session_id = %s",
            (session_id,),
        )
        rows = [
            (key, str(value.get(key)), session_id)
            for collection, key in _LOCATION_KINDS
            for value in compact.get(collection, ())
            if value.get(key)
        ]
        if rows:
            await cursor.executemany(
                f"""
                INSERT INTO {self._table("locations")} (kind, identity, session_id)
                VALUES (%s, %s, %s)
                """,
                rows,
            )

    async def _replace_start_idempotency(self, cursor, session_id, compact) -> None:
        await cursor.execute(
            f"DELETE FROM {self._table('start_idempotency')} WHERE session_id = %s",
            (session_id,),
        )
        rows = [
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
        ]
        if rows:
            await cursor.executemany(
                f"""
                INSERT INTO {self._table("start_idempotency")} (
                    tenant_id, principal_id, idempotency_key,
                    session_id, run_id, request_digest
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                rows,
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
                    self._writer_lock_lost = True
                raise
        for value in deleted_session_ids:
            self._forget_persisted_session(value)

    async def get_derived_state(
        self, session_id: str, namespace: str, key: str
    ) -> Any | None:
        await self._ensure_session_loaded(session_id)
        await super().get_session(session_id)
        assert self._pool is not None
        async with self._pool.acquire() as connection:
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
                    self._writer_lock_lost = True
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
                    self._writer_lock_lost = True
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
                    self._writer_lock_lost = True
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
        async with self._pool.acquire() as connection:
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
        async with self._pool.acquire() as connection:
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
        async with self._pool.acquire() as connection:
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
        async with self._pool.acquire() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    f"""
                    SELECT compact_state FROM {self._table("sessions")}
                    WHERE session_id = %s
                    """,
                    (session_id,),
                )
                row = await cursor.fetchone()
                if row is None:
                    return None
                await cursor.execute(
                    f"""
                    SELECT run_id, event FROM {self._table("run_events")}
                    WHERE session_id = %s
                    ORDER BY run_id, run_sequence
                    """,
                    (session_id,),
                )
                event_rows = await cursor.fetchall()
        payload = dict(_decode_json(row[0]))
        run_events: dict[str, list[dict[str, Any]]] = {}
        for run_id, event in event_rows:
            run_events.setdefault(run_id, []).append(_decode_json(event))
        payload["run_events"] = run_events
        return payload

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
        for run_id in self._persisted_session_runs.pop(session_id, set()):
            self._persisted_run_sequences.pop(run_id, None)

    def _remember_persisted_session(
        self, session_id: str, run_sequences: dict[str, int]
    ) -> None:
        previous = self._persisted_session_runs.get(session_id, set())
        for run_id in previous - set(run_sequences):
            self._persisted_run_sequences.pop(run_id, None)
        self._loaded_session_ids.add(session_id)
        self._persisted_session_runs[session_id] = set(run_sequences)
        self._persisted_run_sequences.update(run_sequences)

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
            {
                run_id: len(events)
                for run_id, events in payload.get("run_events", {}).items()
            },
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
        "Single-process writers; no global Session index."
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
    "StoreInUseError",
    "parse_mysql_dsn",
]

"""Optional single-process PostgreSQL SessionStore.

The coordinator still owns sequencing, idempotency, and legal transitions.
This adapter persists one Session tree at a time, appends Run events, and
rejects a second writer with an advisory lock. There is no global Session
index and no cross-process subscribe.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from contextlib import asynccontextmanager
from copy import deepcopy
from typing import Any

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
    """Raised when another writer already owns the same PostgreSQL prefix."""


class SessionStoreCorruptionError(SageV2Error):
    """Raised when a stored Session aggregate cannot be trusted."""


_SCHEMA_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
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


def _require_asyncpg():
    try:
        import asyncpg
    except ImportError as exc:
        raise SageV2Error(
            RuntimeErrorInfo(
                code="session_store.postgres_unavailable",
                category=ErrorCategory.RESOURCE_LOST,
                message="sage.session.postgres requires the optional asyncpg package",
                safe_to_resume=True,
            )
        ) from exc
    return asyncpg


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _decode_json(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


class _PostgresSessionState(SessionStoreCoordinator):
    """Row-CAS PostgreSQL adapter around the shared state coordinator."""

    format_version = "sage.session.postgres/v3"

    def __init__(
        self,
        dsn: str,
        *,
        schema: str | None = None,
        schema_name: str | None = None,
        table_prefix: str | None = None,
        **kwargs: Any,
    ) -> None:
        resolved = dsn.strip()
        if not resolved:
            raise ValueError(
                "sage.session.postgres requires dsn in the plugin declaration"
            )
        resolved_schema = schema_name or schema or "sage_v2"
        if not _SCHEMA_NAME.fullmatch(resolved_schema):
            raise ValueError("postgres SessionStore schema is invalid")
        prefix = table_prefix or "sagent"
        if not _PREFIX.fullmatch(prefix):
            raise ValueError("postgres SessionStore table_prefix is invalid")
        self.dsn = resolved
        self.schema_name = resolved_schema
        self.table_prefix = prefix
        self._pool = None
        self._lock_conn = None
        self._init_lock = asyncio.Lock()
        self._session_lock_guard = asyncio.Lock()
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._loaded_session_ids: set[str] = set()
        self._persisted_run_sequences: dict[str, int] = {}
        self._persisted_session_runs: dict[str, set[str]] = {}
        self._persisted_session_revisions: dict[str, int] = {}
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
    def lock_key(self) -> int:
        digest = hashlib.sha256(
            f"{self.schema_name}:{self.table_prefix}".encode("utf-8")
        ).digest()
        return int.from_bytes(digest[:8], "big") % (2**63)

    def composition_identity(self) -> dict[str, str]:
        return {
            "plugin": "sage.session.postgres",
            "schema": self.schema_name,
            "table_prefix": self.table_prefix,
            "format": self.format_version,
        }

    def _table(self, name: str) -> str:
        return f"{self.schema_name}.{self.table_prefix}_{name}"

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
                        message="postgres SessionStore is closed",
                        safe_to_resume=True,
                    )
                )
            asyncpg = _require_asyncpg()
            lock_conn = await asyncpg.connect(self.dsn)
            try:
                await self._acquire_writer_lock(lock_conn)
                await self._bootstrap(lock_conn)
                self._pool = await asyncpg.create_pool(
                    self.dsn, min_size=1, max_size=8
                )
            except Exception:
                await lock_conn.close()
                raise
            self._lock_conn = lock_conn

    async def _acquire_writer_lock(self, connection) -> None:
        locked = await connection.fetchval(
            "SELECT pg_try_advisory_lock($1)", self.lock_key
        )
        if not locked:
            raise StoreInUseError(
                RuntimeErrorInfo(
                    code="session_store.in_use",
                    category=ErrorCategory.CONFLICT,
                    message=(
                        "postgres SessionStore prefix is already owned: "
                        f"{self.schema_name}.{self.table_prefix}"
                    ),
                    safe_to_resume=True,
                )
            )

    async def _bootstrap(self, connection) -> None:
        sessions = self._table("sessions")
        run_events = self._table("run_events")
        await connection.execute(f"CREATE SCHEMA IF NOT EXISTS {self.schema_name}")
        await connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {sessions} (
                session_id TEXT PRIMARY KEY,
                parent_session_id TEXT,
                revision BIGINT NOT NULL,
                last_sequence BIGINT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL,
                compact_state JSONB NOT NULL
            )
            """
        )
        await connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {run_events} (
                session_id TEXT NOT NULL
                    REFERENCES {sessions} (session_id) ON DELETE CASCADE,
                run_id TEXT NOT NULL,
                run_sequence BIGINT NOT NULL,
                session_sequence BIGINT,
                event JSONB NOT NULL,
                PRIMARY KEY (run_id, run_sequence)
            )
            """
        )
        await connection.execute(
            f"""
            CREATE INDEX IF NOT EXISTS {self.table_prefix}_run_events_session_seq
            ON {run_events} (session_id, session_sequence)
            """
        )
        await connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self._table("locations")} (
                kind TEXT NOT NULL,
                identity TEXT NOT NULL,
                session_id TEXT NOT NULL
                    REFERENCES {sessions} (session_id) ON DELETE CASCADE,
                PRIMARY KEY (kind, identity)
            )
            """
        )
        await connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self._table("start_idempotency")} (
                tenant_id TEXT NOT NULL DEFAULT '',
                principal_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                session_id TEXT NOT NULL
                    REFERENCES {sessions} (session_id) ON DELETE CASCADE,
                run_id TEXT NOT NULL,
                request_digest TEXT NOT NULL,
                PRIMARY KEY (tenant_id, principal_id, idempotency_key)
            )
            """
        )
        await connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self._table("derived_state")} (
                session_id TEXT NOT NULL
                    REFERENCES {sessions} (session_id) ON DELETE CASCADE,
                namespace TEXT NOT NULL,
                key TEXT NOT NULL,
                value JSONB NOT NULL,
                PRIMARY KEY (session_id, namespace, key)
            )
            """
        )

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        lock_conn = self._lock_conn
        pool = self._pool
        self._lock_conn = None
        self._pool = None
        if pool is not None:
            await pool.close()
        if lock_conn is not None:
            await lock_conn.close()

    @asynccontextmanager
    async def _session_scope(self, session_id: str):
        async with self._session_lock_guard:
            lock = self._session_locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            yield

    async def _commit_storage_locked(self, session_id: str) -> None:
        await self._ensure_ready()
        state = self._dump_session_state_locked(session_id)
        compact = self._compact_state(state)
        session_row = compact["sessions"][0]
        events = {
            run_id: list(rows)
            for run_id, rows in state.get("run_events", {}).items()
        }
        expected = self._persisted_session_revisions.get(session_id)
        new_revision = int(session_row["revision"])
        next_run_sequences: dict[str, int] = {}
        assert self._pool is not None
        try:
            async with self._pool.acquire() as connection:
                async with connection.transaction():
                    current = await connection.fetchval(
                        f"""
                        SELECT revision FROM {self._table("sessions")}
                        WHERE session_id = $1
                        FOR UPDATE
                        """,
                        session_id,
                    )
                    if current is None:
                        if expected is not None:
                            raise self._conflict(
                                "session.revision_conflict",
                                f"session {session_id} was deleted by another writer",
                            )
                        await connection.execute(
                            f"""
                            INSERT INTO {self._table("sessions")} (
                                session_id, parent_session_id, revision,
                                last_sequence, created_at, updated_at,
                                compact_state
                            )
                            VALUES (
                                $1, $2, $3, $4, $5::timestamptz,
                                $6::timestamptz, $7::jsonb
                            )
                            """,
                            session_row["session_id"],
                            session_row.get("parent_session_id"),
                            new_revision,
                            int(session_row["last_sequence"]),
                            session_row["created_at"],
                            session_row["updated_at"],
                            _json(compact),
                        )
                    else:
                        if expected is None or int(current) != expected:
                            raise self._conflict(
                                "session.revision_conflict",
                                (
                                    f"expected session revision {expected}, "
                                    f"durable {current}"
                                ),
                            )
                        updated = await connection.execute(
                            f"""
                            UPDATE {self._table("sessions")} SET
                                parent_session_id = $2,
                                revision = $3,
                                last_sequence = $4,
                                updated_at = $5::timestamptz,
                                compact_state = $6::jsonb
                            WHERE session_id = $1 AND revision = $7
                            """,
                            session_id,
                            session_row.get("parent_session_id"),
                            new_revision,
                            int(session_row["last_sequence"]),
                            session_row["updated_at"],
                            _json(compact),
                            expected,
                        )
                        if updated != "UPDATE 1":
                            raise self._conflict(
                                "session.revision_conflict",
                                (
                                    f"lost session CAS for {session_id}: "
                                    f"expected {expected}"
                                ),
                            )
                    next_run_sequences = await self._persist_events(
                        connection, session_id, events
                    )
                    await self._replace_locations(
                        connection, session_id, compact
                    )
                    await self._replace_start_idempotency(
                        connection, session_id, compact
                    )
        except Exception as exc:
            await self._reload_session_from_storage_locked(session_id)
            asyncpg = _require_asyncpg()
            if isinstance(exc, asyncpg.UniqueViolationError):
                raise self._conflict(
                    "session.revision_conflict",
                    f"session {session_id} was written by another writer",
                ) from exc
            raise
        self._remember_persisted_session(session_id, new_revision, next_run_sequences)

    async def _replace_locations(self, connection, session_id, compact) -> None:
        await connection.execute(
            f"DELETE FROM {self._table('locations')} WHERE session_id = $1",
            session_id,
        )
        location_rows = []
        for collection, key in _LOCATION_KINDS:
            for value in compact.get(collection, ()):
                identity = value.get(key)
                if identity:
                    location_rows.append((key, str(identity), session_id))
        if location_rows:
            await connection.executemany(
                f"""
                INSERT INTO {self._table("locations")}
                    (kind, identity, session_id)
                VALUES ($1, $2, $3)
                """,
                location_rows,
            )

    async def _replace_start_idempotency(
        self, connection, session_id, compact
    ) -> None:
        await connection.execute(
            f"DELETE FROM {self._table('start_idempotency')} WHERE session_id = $1",
            session_id,
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
            await connection.executemany(
                f"""
                INSERT INTO {self._table("start_idempotency")} (
                    tenant_id, principal_id, idempotency_key,
                    session_id, run_id, request_digest
                )
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                rows,
            )

    async def _persist_events(
        self,
        connection,
        session_id: str,
        events: dict[str, list[dict[str, Any]]],
    ) -> dict[str, int]:
        next_sequences = {
            run_id: self._persisted_run_sequences[run_id]
            for run_id in events
            if run_id in self._persisted_run_sequences
        }
        removed = self._persisted_session_runs.get(session_id, set()) - set(events)
        for run_id in removed:
            await connection.execute(
                f"DELETE FROM {self._table('run_events')} WHERE run_id = $1",
                run_id,
            )
        for run_id, rows in events.items():
            persisted = next_sequences.get(run_id, 0)
            if persisted > len(rows):
                await connection.execute(
                    f"DELETE FROM {self._table('run_events')} WHERE run_id = $1",
                    run_id,
                )
                persisted = 0
            appended = rows[persisted:]
            if appended:
                await connection.executemany(
                    f"""
                    INSERT INTO {self._table("run_events")} (
                        session_id, run_id, run_sequence, session_sequence, event
                    )
                    VALUES ($1, $2, $3, $4, $5::jsonb)
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

    async def _delete_storage_locked(
        self, session_id: str, deleted_session_ids: frozenset[str]
    ) -> None:
        await self._ensure_ready()
        ordered = tuple(sorted(deleted_session_ids))
        assert self._pool is not None
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                if ordered:
                    await connection.fetch(
                        f"""
                        SELECT session_id FROM {self._table("sessions")}
                        WHERE session_id = ANY($1::text[])
                        ORDER BY session_id
                        FOR UPDATE
                        """,
                        list(ordered),
                    )
                await connection.execute(
                    f"""
                    DELETE FROM {self._table("sessions")}
                    WHERE session_id = ANY($1::text[])
                    """,
                    list(ordered),
                )
        for value in deleted_session_ids:
            self._forget_persisted_session(value)

    async def get_derived_state(
        self, session_id: str, namespace: str, key: str
    ) -> Any | None:
        async with self._session_scope(session_id):
            await self._refresh_session(session_id)
            await super().get_session(session_id)
        assert self._pool is not None
        async with self._pool.acquire() as connection:
            payload = await connection.fetchval(
                f"""
                SELECT value FROM {self._table("derived_state")}
                WHERE session_id = $1 AND namespace = $2 AND key = $3
                """,
                session_id,
                namespace,
                key,
            )
        if payload is None:
            return None
        return _decode_json(payload)

    async def put_derived_state(
        self, session_id: str, namespace: str, key: str, value: Any
    ) -> None:
        async with self._session_scope(session_id):
            await self._refresh_session(session_id)
            await super().put_derived_state(session_id, namespace, key, value)
        await self._ensure_ready()
        assert self._pool is not None
        async with self._pool.acquire() as connection:
            await connection.execute(
                f"""
                INSERT INTO {self._table("derived_state")}
                    (session_id, namespace, key, value)
                VALUES ($1, $2, $3, $4::jsonb)
                ON CONFLICT (session_id, namespace, key) DO UPDATE SET
                    value = EXCLUDED.value
                """,
                session_id,
                namespace,
                key,
                _json(value),
            )

    async def delete_derived_state(
        self, session_id: str, namespace: str, key: str
    ) -> None:
        async with self._session_scope(session_id):
            await self._refresh_session(session_id)
            await super().delete_derived_state(session_id, namespace, key)
        await self._ensure_ready()
        assert self._pool is not None
        async with self._pool.acquire() as connection:
            await connection.execute(
                f"""
                DELETE FROM {self._table("derived_state")}
                WHERE session_id = $1 AND namespace = $2 AND key = $3
                """,
                session_id,
                namespace,
                key,
            )

    async def create_run(self, command, context):
        await self._ensure_ready()
        session_id = command.session_id
        if session_id is None:
            session_id = await self._read_start_lookup(command, context)
        if session_id is not None:
            async with self._session_scope(session_id):
                await self._refresh_session(session_id, missing_ok=True)
                return await super().create_run(command, context)
        return await super().create_run(command, context)

    async def get_session(self, session_id):
        async with self._session_scope(session_id):
            await self._refresh_session(session_id)
            return await super().get_session(session_id)

    async def delete_session(self, session_id):
        async with self._session_scope(session_id):
            await self._refresh_session(session_id)
            await self._ensure_descendants_loaded(session_id)
            for child in await super().list_descendant_sessions(session_id):
                await self._refresh_session(child.session_id, missing_ok=True)
            result = await super().delete_session(session_id)
            self._loaded_session_ids.intersection_update(self._sessions)
            return result

    async def list_session_runs(self, session_id):
        async with self._session_scope(session_id):
            await self._refresh_session(session_id)
            return await super().list_session_runs(session_id)

    async def list_descendant_sessions(self, session_id):
        async with self._session_scope(session_id):
            await self._refresh_session(session_id)
            await self._ensure_descendants_loaded(session_id)
            return await super().list_descendant_sessions(session_id)

    async def read_session_events(self, session_id, **kwargs):
        async with self._session_scope(session_id):
            await self._refresh_session(session_id)
            return await super().read_session_events(session_id, **kwargs)

    async def list_session_commit_proposals(self, session_id):
        async with self._session_scope(session_id):
            await self._refresh_session(session_id)
            return await super().list_session_commit_proposals(session_id)

    async def get_run(self, run_id):
        await self._refresh_resource("run_id", run_id)
        return await super().get_run(run_id)

    async def get_run_result(self, run_id):
        await self._refresh_resource("run_id", run_id)
        return await super().get_run_result(run_id)

    async def get_start_command(self, run_id):
        await self._refresh_resource("run_id", run_id)
        return await super().get_start_command(run_id)

    async def get_latest_checkpoint(self, run_id):
        await self._refresh_resource("run_id", run_id)
        return await super().get_latest_checkpoint(run_id)

    async def read_events(self, run_id, **kwargs):
        await self._refresh_resource("run_id", run_id)
        return await super().read_events(run_id, **kwargs)

    async def read_fork_base_events(self, run_id):
        await self._refresh_resource("run_id", run_id)
        return await super().read_fork_base_events(run_id)

    async def commit_run(self, *, run_id, **kwargs):
        await self._refresh_resource("run_id", run_id)
        return await super().commit_run(run_id=run_id, **kwargs)

    async def propose_session_commit(self, command, context):
        await self._refresh_resource("run_id", command.run_id)
        return await super().propose_session_commit(command, context)

    async def publish_session_commit(self, command, context):
        await self._refresh_resource("proposal_id", command.proposal_id)
        return await super().publish_session_commit(command, context)

    async def reject_session_commit(self, command, context):
        await self._refresh_resource("proposal_id", command.proposal_id)
        return await super().reject_session_commit(command, context)

    async def get_session_commit_proposal(self, proposal_id):
        await self._refresh_resource("proposal_id", proposal_id)
        return await super().get_session_commit_proposal(proposal_id)

    async def get_checkpoint(self, checkpoint_id):
        await self._refresh_resource("checkpoint_id", checkpoint_id)
        return await super().get_checkpoint(checkpoint_id)

    async def get_suspension(self, suspension_id):
        await self._refresh_resource("suspension_id", suspension_id)
        return await super().get_suspension(suspension_id)

    async def get_interaction(self, interaction_id):
        await self._refresh_resource("interaction_id", interaction_id)
        return await super().get_interaction(interaction_id)

    async def get_interaction_resolution(self, interaction_id):
        await self._refresh_resource("interaction_id", interaction_id)
        return await super().get_interaction_resolution(interaction_id)

    async def enqueue_steer(self, command, context):
        await self._refresh_resource("run_id", command.run_id)
        return await super().enqueue_steer(command, context)

    async def claim_steers(self, *, run_id, **kwargs):
        await self._refresh_resource("run_id", run_id)
        return await super().claim_steers(run_id=run_id, **kwargs)

    async def list_steers(self, run_id):
        await self._refresh_resource("run_id", run_id)
        return await super().list_steers(run_id)

    async def resolve_interaction(self, command, context):
        await self._refresh_resource("run_id", command.run_id)
        return await super().resolve_interaction(command, context)

    async def request_resume(self, command, context):
        await self._refresh_resource("run_id", command.run_id)
        return await super().request_resume(command, context)

    async def subscribe_events(self, cursor):
        await self._refresh_resource("run_id", cursor.run_id)
        async for event in super().subscribe_events(cursor):
            yield event

    async def _refresh_resource(self, identity_key: str, identity: str) -> None:
        await self._ensure_ready()
        session_id = await self._locate_session(identity_key, identity)
        if session_id is None:
            session_id = self._session_id_for_loaded(identity_key, identity)
        if session_id is None:
            await self._ensure_resource_loaded(identity_key, identity)
            return
        async with self._session_scope(session_id):
            await self._refresh_session(session_id)

    def _session_id_for_loaded(
        self, identity_key: str, identity: str
    ) -> str | None:
        if identity_key == "run_id":
            row = self._runs.get(identity)
            return None if row is None else row.session_id
        if identity_key == "checkpoint_id":
            value = self._checkpoints.get(identity)
            return None if value is None else value.session_id
        if identity_key == "suspension_id":
            value = self._suspensions.get(identity)
            if value is None:
                return None
            run = self._runs.get(value.run_id)
            return None if run is None else run.session_id
        if identity_key == "proposal_id":
            value = self._session_commit_proposals.get(identity)
            return None if value is None else value.session_id
        if identity_key == "interaction_id":
            value = self._interactions.get(identity)
            if value is None:
                return None
            run = self._runs.get(value.run_id)
            return None if run is None else run.session_id
        return None

    async def _refresh_session(
        self, session_id: str, *, missing_ok: bool = False
    ) -> None:
        await self._ensure_ready()
        payload = await self._fetch_session(session_id)
        async with self._lock:
            if session_id in self._sessions:
                self._evict_session_locked(session_id)
            if payload is None:
                if missing_ok:
                    return
                raise self._not_found("session.not_found", session_id)
            self._install_session_locked(payload)

    async def _ensure_session_loaded(
        self, session_id: str, *, missing_ok: bool = False
    ) -> None:
        await self._refresh_session(session_id, missing_ok=missing_ok)

    async def _ensure_descendants_loaded(self, session_id: str) -> None:
        await self._ensure_ready()
        assert self._pool is not None
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                f"""
                WITH RECURSIVE tree AS (
                    SELECT session_id
                    FROM {self._table("sessions")}
                    WHERE parent_session_id = $1
                    UNION ALL
                    SELECT child.session_id
                    FROM {self._table("sessions")} AS child
                    JOIN tree ON child.parent_session_id = tree.session_id
                )
                SELECT session_id FROM tree
                """,
                session_id,
            )
        for row in rows:
            await self._refresh_session(row["session_id"], missing_ok=True)

    async def _ensure_resource_loaded(self, identity_key: str, identity: str) -> None:
        await self._ensure_ready()
        session_id = await self._locate_session(identity_key, identity)
        if session_id is None:
            if self._resource_is_loaded(identity_key, identity):
                return
            raise self._not_found(f"{identity_key}.not_found", identity)
        await self._refresh_session(session_id)

    def _resource_is_loaded(self, identity_key: str, identity: str) -> bool:
        mappings = {
            "run_id": self._runs,
            "checkpoint_id": self._checkpoints,
            "suspension_id": self._suspensions,
            "interaction_id": self._interactions,
            "proposal_id": self._session_commit_proposals,
        }
        return identity in mappings[identity_key]

    async def _locate_session(self, identity_key: str, identity: str) -> str | None:
        if identity_key == "run_id" and identity in self._runs:
            return self._runs[identity].session_id
        await self._ensure_ready()
        assert self._pool is not None
        async with self._pool.acquire() as connection:
            return await connection.fetchval(
                f"""
                SELECT session_id FROM {self._table("locations")}
                WHERE kind = $1 AND identity = $2
                """,
                identity_key,
                identity,
            )

    async def _read_start_lookup(self, command, context) -> str | None:
        assert self._pool is not None
        async with self._pool.acquire() as connection:
            return await connection.fetchval(
                f"""
                SELECT session_id FROM {self._table("start_idempotency")}
                WHERE tenant_id = $1 AND principal_id = ANY($2::text[])
                  AND idempotency_key = $3
                """,
                str(context.actor.tenant_id or ""),
                [
                    _principal_lookup_key(
                        context.actor.principal_type.value,
                        context.actor.principal_id,
                    ),
                    context.actor.principal_id,
                ],
                command.idempotency_key,
            )

    async def _fetch_session(self, session_id: str) -> dict[str, Any] | None:
        assert self._pool is not None
        async with self._pool.acquire() as connection:
            compact = await connection.fetchval(
                f"SELECT compact_state FROM {self._table('sessions')} WHERE session_id = $1",
                session_id,
            )
            if compact is None:
                return None
            event_rows = await connection.fetch(
                f"""
                SELECT run_id, event
                FROM {self._table("run_events")}
                WHERE session_id = $1
                ORDER BY run_id, run_sequence
                """,
                session_id,
            )
        payload = dict(_decode_json(compact))
        run_events: dict[str, list[dict[str, Any]]] = {}
        for row in event_rows:
            run_events.setdefault(row["run_id"], []).append(
                _decode_json(row["event"])
            )
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
        self._persisted_session_revisions.pop(session_id, None)
        for run_id in self._persisted_session_runs.pop(session_id, set()):
            self._persisted_run_sequences.pop(run_id, None)

    def _remember_persisted_session(
        self,
        session_id: str,
        revision: int,
        run_sequences: dict[str, int],
    ) -> None:
        previous = self._persisted_session_runs.get(session_id, set())
        for run_id in previous - set(run_sequences):
            self._persisted_run_sequences.pop(run_id, None)
        self._persisted_session_revisions[session_id] = revision
        self._persisted_session_runs[session_id] = set(run_sequences)
        self._persisted_run_sequences.update(run_sequences)

    def _install_session_locked(self, payload: dict[str, Any]) -> None:
        session_rows = payload.get("sessions", ())
        if len(session_rows) != 1:
            raise SessionStoreCorruptionError(
                RuntimeErrorInfo(
                    code="session_store.aggregate_corrupt",
                    category=ErrorCategory.CORRUPT_STATE,
                    message="postgres snapshot does not contain exactly one Session",
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
        self._loaded_session_ids.add(session_id)
        self._remember_persisted_session(
            session_id,
            int(session_rows[0]["revision"]),
            {
                run_id: len(events)
                for run_id, events in payload.get("run_events", {}).items()
            },
        )

    @staticmethod
    def _compact_state(state: dict[str, Any]) -> dict[str, Any]:
        compact = {
            "session_format_version": state["session_format_version"],
        }
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


class _PostgresSessionStoreMeta(type):
    def __getattr__(cls, name):
        return getattr(_PostgresSessionState, name)


class PostgresSessionStore(metaclass=_PostgresSessionStoreMeta):
    """Composed durable PostgreSQL SessionStore facade."""

    def __init__(self, *args, **kwargs) -> None:
        object.__setattr__(
            self, "_coordinator", _PostgresSessionState(*args, **kwargs)
        )

    def __getattr__(self, name):
        return getattr(self._coordinator, name)

    def __setattr__(self, name, value) -> None:
        if name == "_coordinator":
            object.__setattr__(self, name, value)
        else:
            setattr(self._coordinator, name, value)


__all__ = [
    "PostgresSessionStore",
    "SessionStoreCorruptionError",
    "StoreInUseError",
]

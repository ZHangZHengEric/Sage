"""Parameterized SQL reads and projections shared by durable backends."""

from __future__ import annotations

import asyncio
from typing import Any
from .aggregate import (
    _json,
    _decode_json,
    _principal_lookup_key,
    SessionStoreCorruptionError,
)
from .cache import cached_session_operation
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo

from .commit import SqlSessionCommit


class SqlSessionPersistence(SqlSessionCommit):
    _decode_derived_value = staticmethod(_decode_json)

    async def report_business_events(
        self, *, start, end, agent_id="", max_runs=10000, max_events=100000, exclude_sessions=(),
    ):
        from .reporting import replay_sql

        return await replay_sql(
            self, start=start, end=end, agent_id=agent_id, max_runs=max_runs, max_events=max_events,
            exclude_sessions=exclude_sessions,
        )

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
                    WHERE session_id = %s AND namespace = %s AND {self.key_column} = %s
                    """,
                    (session_id, namespace, key),
                )
                row = await cursor.fetchone()
        if row is None:
            return None
        return self._decode_derived_value(row[0])

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
                        self._derived_upsert_sql(),
                        (session_id, namespace, key, _json(value)),
                    )
                await connection.commit()
            except Exception:
                try:
                    await connection.rollback()
                except Exception as rollback_error:
                    self._storage_logger.exception(
                        f"session.{self.backend}.rollback_failed",
                        "SQL session rollback failed",
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
                        WHERE session_id = %s AND namespace = %s AND {self.key_column} = %s
                        """,
                        (session_id, namespace, key),
                    )
                await connection.commit()
            except Exception:
                try:
                    await connection.rollback()
                except Exception as rollback_error:
                    self._storage_logger.exception(
                        f"session.{self.backend}.rollback_failed",
                        "SQL session rollback failed",
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
                    self._storage_logger.exception(
                        f"session.{self.backend}.rollback_failed",
                        "SQL session rollback failed",
                        rollback_error,
                    )
                raise

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
        return await asyncio.to_thread(
            self._decode_session_rows, row, mutation_rows, event_rows
        )

    async def _fetch_sessions(self, session_ids) -> dict[str, dict[str, Any]]:
        """Read canonical aggregates with three SELECTs per 128 Session IDs."""
        ids = tuple(dict.fromkeys(session_ids))
        result = {}
        if not ids:
            return result
        async with self._reader_connection() as connection:
            async with connection.cursor() as cursor:
                await self._begin_snapshot(connection)
                for start in range(0, len(ids), 128):
                    batch = ids[start : start + 128]
                    marks = ",".join(["%s"] * len(batch))
                    await cursor.execute(
                        f"SELECT session_id, compact_state, revision, last_sequence "
                        f"FROM {self._table('sessions')} WHERE session_id IN ({marks})",
                        batch,
                    )
                    bases = await cursor.fetchall()
                    await cursor.execute(
                        f"SELECT session_id, revision, mutation FROM {self._table('session_mutations')} "
                        f"WHERE session_id IN ({marks}) ORDER BY session_id, revision",
                        batch,
                    )
                    mutations = await cursor.fetchall()
                    await cursor.execute(
                        f"SELECT session_id, run_id, event FROM {self._table('run_events')} "
                        f"WHERE session_id IN ({marks}) ORDER BY session_id, run_id, run_sequence",
                        batch,
                    )
                    events = await cursor.fetchall()

                    def decode():
                        mutation_rows, event_rows = {}, {}
                        for sid, revision, mutation in mutations:
                            mutation_rows.setdefault(sid, []).append(
                                (revision, mutation)
                            )
                        for sid, rid, event in events:
                            event_rows.setdefault(sid, []).append((rid, event))
                        decoded = {}
                        for sid, *row in bases:
                            payload = self._decode_session_rows(
                                row, mutation_rows.get(sid, ()), event_rows.get(sid, ())
                            )
                            if payload["sessions"][0]["session_id"] != sid:
                                raise SessionStoreCorruptionError(
                                    RuntimeErrorInfo(
                                        code="session_store.aggregate_corrupt",
                                        category=ErrorCategory.CORRUPT_STATE,
                                        message="SQL Session snapshot identity disagrees with its row",
                                        safe_to_resume=False,
                                    )
                                )
                            decoded[sid] = payload
                        return decoded

                    result.update(await asyncio.to_thread(decode))
        return result

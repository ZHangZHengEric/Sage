"""Transactional SQL persistence with Session CAS and append-only events."""

from __future__ import annotations

import time
from .aggregate import _json


class SqlSessionCommit:
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
                        VALUES (%s, %s, %s, %s, %s, %s, CAST(%s AS {self.json_type}))
                        """,
                            (
                                session_id,
                                session_row.get("parent_session_id"),
                                new_revision,
                                int(session_row["last_sequence"]),
                                self._storage_datetime(session_row["created_at"]),
                                self._storage_datetime(session_row["updated_at"]),
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
                                compact_state = CAST(%s AS {self.json_type})
                            WHERE session_id = %s AND revision = %s
                            """,
                                (
                                    session_row.get("parent_session_id"),
                                    new_revision,
                                    int(session_row["last_sequence"]),
                                    self._storage_datetime(session_row["updated_at"]),
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
                                    self._storage_datetime(session_row["updated_at"]),
                                    session_id,
                                    expected_revision,
                                ),
                            )
                        if cursor.rowcount != 1:
                            raise self._conflict(
                                "session.revision_conflict",
                                f"expected session revision {expected_revision} for {session_id}",
                            )
                    await self._insert_attachments(cursor, session_id)
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
                            VALUES (%s, %s, CAST(%s AS {self.json_type}))
                            """,
                            (session_id, new_revision, encoded_mutation),
                        )
                    await self._sync_locations(cursor, session_id, location_rows)
                    await self._sync_start_idempotency(cursor, session_id, start_rows)
                    await self._write_workspace_projection(
                        cursor,
                        session_id,
                        new_revision,
                        {rid: self._runs[rid].state.value for rid in run_ids},
                    )
                written_at = time.perf_counter()
                await connection.commit()
                committed_at = time.perf_counter()
            except Exception as exc:
                try:
                    await connection.rollback()
                except Exception as rollback_error:
                    self._storage_logger.exception(
                        f"session.{self.backend}.rollback_failed",
                        "SQL session rollback failed",
                        rollback_error,
                    )
                failure = exc
        if failure is not None:
            self._storage_logger.debug(
                f"session.{self.backend}.commit_failed",
                "SQL 会话提交失败",
                session_id=session_id,
                revision=new_revision,
                duration_ms=round((time.perf_counter() - started_at) * 1000, 3),
            )
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
        self._session_cache.touch(
            session_id,
            charge=4
            * (
                len((encoded_compact or encoded_mutation or "").encode())
                + sum(
                    len(_json(event).encode())
                    for rows in events.values()
                    for event in rows
                )
            ),
        )
        self._storage_logger.debug(
            f"session.{self.backend}.commit",
            "SQL 会话提交完成",
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
                    VALUES (%s, %s, %s, %s, CAST(%s AS {self.json_type}))
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
                    self._storage_logger.exception(
                        f"session.{self.backend}.rollback_failed",
                        "SQL session rollback failed",
                        rollback_error,
                    )
                raise
        for value in deleted_session_ids:
            self._forget_persisted_session(value)

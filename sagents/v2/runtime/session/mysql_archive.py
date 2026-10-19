"""Batch archival into the existing MySQL Session tables."""

from sagents.v2.runtime.session.mysql_state import _MysqlSessionState, _datetime, _json


class MysqlSessionArchive(_MysqlSessionState):
    async def _fetch_session(self, session_id):
        await self._ensure_ready()
        return await super()._fetch_session(session_id)

    async def _locate_session(self, kind, identity):
        await self._ensure_ready()
        return await super()._locate_session(kind, identity)

    async def _read_start_lookup(self, command, context):
        await self._ensure_ready()
        return await super()._read_start_lookup(command, context)

    async def _list_descendant_ids(self, session_id):
        await self._ensure_ready()
        return await super()._list_descendant_ids(session_id)

    async def archive_session(self, payload, attachments):
        """Publish a complete aggregate and its events in one SQL transaction.

        A locked revision comparison makes retry after an ambiguous commit safe
        and prevents an older archive from overwriting a newer Session.
        """
        await self._ensure_ready()
        head = payload["sessions"][0]
        sid, revision = head["session_id"], int(head["revision"])
        async with self._writer_connection() as connection:
            try:
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        f"SELECT revision FROM {self._table('sessions')} WHERE session_id = %s FOR UPDATE", (sid,))
                    previous = await cursor.fetchone()
                    if previous is not None and int(previous[0]) >= revision:
                        await connection.rollback()
                        return
                    compact = _json(self._compact_state(payload))
                    if previous is None:
                        await cursor.execute(
                            f"INSERT INTO {self._table('sessions')} "
                            "(session_id, parent_session_id, revision, last_sequence, created_at, updated_at, compact_state) "
                            "VALUES (%s, %s, %s, %s, %s, %s, CAST(%s AS JSON))",
                            (sid, head.get("parent_session_id"), revision, head["last_sequence"],
                             _datetime(head["created_at"]), _datetime(head["updated_at"]), compact))
                    else:
                        await cursor.execute(
                            f"UPDATE {self._table('sessions')} SET parent_session_id = %s, revision = %s, "
                            "last_sequence = %s, updated_at = %s, compact_state = CAST(%s AS JSON) WHERE session_id = %s",
                            (head.get("parent_session_id"), revision, head["last_sequence"],
                             _datetime(head["updated_at"]), compact, sid))
                    await cursor.execute(
                        f"SELECT run_id, MAX(run_sequence) FROM {self._table('run_events')} "
                        "WHERE session_id = %s GROUP BY run_id", (sid,))
                    offsets = {run_id: int(sequence) for run_id, sequence in await cursor.fetchall()}
                    for run_id, events in payload.get("run_events", {}).items():
                        appended = [event for event in events if event["run_sequence"] > offsets.get(run_id, 0)]
                        if appended:
                            await cursor.executemany(
                                f"INSERT INTO {self._table('run_events')} "
                                "(session_id, run_id, run_sequence, session_sequence, event) "
                                "VALUES (%s, %s, %s, %s, CAST(%s AS JSON))",
                                [(sid, run_id, event["run_sequence"], event.get("session_sequence"), _json(event))
                                 for event in appended])
                    await cursor.execute(f"DELETE FROM {self._table('session_mutations')} WHERE session_id = %s", (sid,))
                    await cursor.execute(f"DELETE FROM {self._table('locations')} WHERE session_id = %s", (sid,))
                    locations = sorted(self._location_rows(sid, payload))
                    if locations:
                        await cursor.executemany(
                            f"INSERT INTO {self._table('locations')} (kind, identity, session_id) VALUES (%s, %s, %s)", locations)
                    await cursor.execute(f"DELETE FROM {self._table('start_idempotency')} WHERE session_id = %s", (sid,))
                    starts = sorted(self._start_key_rows(sid, payload))
                    if starts:
                        await cursor.executemany(
                            f"INSERT INTO {self._table('start_idempotency')} "
                            "(tenant_id, principal_id, idempotency_key, session_id, run_id, request_digest) "
                            "VALUES (%s, %s, %s, %s, %s, %s)", starts)
                    for artifact_id, content in attachments.items():
                        await cursor.execute(
                            f"INSERT IGNORE INTO {self._table('attachments')} (session_id, artifact_id, payload) "
                            "VALUES (%s, %s, UNHEX(%s))", (sid, artifact_id, content.hex()))
                await connection.commit()
            except BaseException:
                await connection.rollback()
                raise

    async def delete_archived_sessions(self, session_ids):
        await self._delete_storage_locked("", frozenset(session_ids))

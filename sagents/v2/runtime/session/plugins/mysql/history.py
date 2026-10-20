"""Bounded authorized read projections over the existing MySQL event journal."""
from __future__ import annotations

import json
from contextlib import asynccontextmanager

from sagents.v2.contracts.commands import StartRun
from sagents.v2.contracts.events import RuntimeEvent
from sagents.v2.contracts.principals import ActorRef
from sagents.v2.runtime.session.contracts import SessionEventPage


def _decode(value):
    return json.loads(value) if isinstance(value, (str, bytes, bytearray)) else value


class MysqlHistoryQueries:
    # Redis's MySQL journal is an asynchronous archive, so Redis must use its
    # authoritative coordinator view instead of reading a stale archive page.
    durable_history_pages = True

    @asynccontextmanager
    async def _history_query(self, session_id, context):
        async with self._reader_connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                await connection.begin()
                await cursor.execute(
                    f"SELECT JSON_EXTRACT(compact_state, '$.sessions[0].owner'), last_sequence "
                    f"FROM {self._table('sessions')} WHERE session_id = %s", (session_id,),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise self._not_found("session.not_found", session_id)
                owner = _decode(row[0])
                # Only legacy owner-less snapshots need the existing full
                # derivation path. New snapshots never install execution state.
                if owner is not None or "session.admin" in context.actor.scopes:
                    self._authorize_session_owner(ActorRef.model_validate(owner) if owner else None, context)
                    yield cursor, int(row[1])
                else:
                    yield None, int(row[1])

    async def read_authorized_session_page(self, session_id, context, *, after_sequence, limit):
        if self.durable_history_pages:
            async with self._history_query(session_id, context) as (cursor, total):
                if cursor is not None:
                    start = max(0, total - limit) if after_sequence is None else after_sequence
                    await cursor.execute(
                        f"SELECT event FROM {self._table('run_events')} WHERE session_id = %s "
                        "AND session_sequence > %s AND session_sequence <= %s "
                        "ORDER BY session_sequence LIMIT %s", (session_id, start, total, limit),
                    )
                    rows = await cursor.fetchall()
                    events = tuple(RuntimeEvent.model_validate(_decode(row[0])) for row in rows)
                    return SessionEventPage(events, total, start)
        await self.authorize_session_actor(session_id, context)
        session = await self.get_session(session_id)
        start = max(0, session.last_sequence - limit) if after_sequence is None else after_sequence
        events = await self.read_session_events(session_id, after_sequence=start, limit=limit)
        return SessionEventPage(tuple(events), session.last_sequence, start)

    async def latest_authorized_session_command(self, session_id, context):
        if self.durable_history_pages:
            async with self._history_query(session_id, context) as (cursor, _):
                if cursor is not None:
                    # New Runs are journal upserts. Existing Run patches never
                    # change their admitted command. Only one command crosses
                    # the transport, regardless of the Session's history size.
                    await cursor.execute(f"""
                        SELECT admitted FROM (
                          SELECT JSON_EXTRACT(s.compact_state,
                                   CONCAT('$.runs[', r.pos - 1, '].start_command')) admitted,
                                 r.created_at, r.run_id
                          FROM {self._table('sessions')} s, JSON_TABLE(s.compact_state, '$.runs[*]'
                            COLUMNS (pos FOR ORDINALITY,
                                     created_at VARCHAR(64) PATH '$.created_at',
                                     run_id VARCHAR(128) PATH '$.run_id')) r
                          WHERE s.session_id = %s
                          UNION ALL
                          SELECT JSON_EXTRACT(m.mutation,
                                   CONCAT('$.upserts.runs[', r.pos - 1, '].start_command')) admitted,
                                 r.created_at, r.run_id
                          FROM {self._table('session_mutations')} m, JSON_TABLE(m.mutation, '$.upserts.runs[*]'
                            COLUMNS (pos FOR ORDINALITY,
                                     created_at VARCHAR(64) PATH '$.created_at',
                                     run_id VARCHAR(128) PATH '$.run_id')) r
                          WHERE m.session_id = %s
                        ) commands ORDER BY created_at DESC, run_id DESC LIMIT 1
                    """, (session_id, session_id))
                    row = await cursor.fetchone()
                    return StartRun.model_validate(_decode(row[0])) if row and row[0] is not None else None
        await self.authorize_session_actor(session_id, context)
        runs = await self.list_session_runs(session_id)
        return await self.get_start_command(runs[-1].run_id) if runs else None

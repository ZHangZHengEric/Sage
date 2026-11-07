"""Bounded authorized history pages from the PostgreSQL event journal."""

from contextlib import asynccontextmanager
from .._shared.aggregate import _decode_json as _decode
from sagents.v2.contracts.commands import StartRun
from sagents.v2.contracts.events import RuntimeEvent
from sagents.v2.contracts.principals import ActorRef
from sagents.v2.runtime.session.contracts import SessionEventPage


class PostgresHistoryQueries:
    # Redis's SQL journal is an asynchronous archive, so Redis must use its
    # authoritative coordinator view instead of reading a stale archive page.
    durable_history_pages = True

    @asynccontextmanager
    async def _history_query(self, session_id, context):
        store = self
        async with store._reader_connection() as connection:
            async with connection.cursor() as cursor:
                await store._begin_snapshot(connection)
                await cursor.execute(
                    f"SELECT compact_state #> '{{sessions,0,owner}}', last_sequence "
                    f"FROM {store._table('sessions')} WHERE session_id = %s",
                    (session_id,),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise store._not_found("session.not_found", session_id)
                owner = _decode(row[0])
                # Only legacy owner-less snapshots need the existing full
                # derivation path. New snapshots never install execution state.
                if owner is not None or "session.admin" in context.actor.scopes:
                    store._authorize_session_owner(
                        ActorRef.model_validate(owner) if owner else None, context
                    )
                    yield cursor, int(row[1])
                else:
                    yield None, int(row[1])

    async def read_authorized_session_page(
        self, session_id, context, *, after_sequence, limit
    ):
        store = self
        if store.durable_history_pages:
            async with store._history_query(session_id, context) as (cursor, total):
                if cursor is not None:
                    start = (
                        max(0, total - limit)
                        if after_sequence is None
                        else after_sequence
                    )
                    await cursor.execute(
                        f"SELECT event FROM {store._table('run_events')} WHERE session_id = %s "
                        "AND session_sequence > %s AND session_sequence <= %s "
                        "ORDER BY session_sequence LIMIT %s",
                        (session_id, start, total, limit),
                    )
                    rows = await cursor.fetchall()
                    events = tuple(
                        RuntimeEvent.model_validate(_decode(row[0])) for row in rows
                    )
                    return SessionEventPage(events, total, start)
        await store.authorize_session_actor(session_id, context)
        session = await store.get_session(session_id)
        start = (
            max(0, session.last_sequence - limit)
            if after_sequence is None
            else after_sequence
        )
        events = await store.read_session_events(
            session_id, after_sequence=start, limit=limit
        )
        return SessionEventPage(tuple(events), session.last_sequence, start)

    async def latest_authorized_session_command(self, session_id, context):
        store = self
        if store.durable_history_pages:
            async with store._history_query(session_id, context) as (cursor, _):
                if cursor is not None:
                    # New Runs are journal upserts. Existing Run patches never
                    # change their admitted command. Only one command crosses
                    # the transport, regardless of the Session's history size.
                    await cursor.execute(
                        f"""
                        SELECT payload->'start_command' FROM (
                          SELECT r.payload FROM {store._table("sessions")} s
                          CROSS JOIN LATERAL jsonb_array_elements(s.compact_state->'runs') r(payload)
                          WHERE s.session_id = %s
                          UNION ALL
                          SELECT r.payload FROM {store._table("session_mutations")} m
                          CROSS JOIN LATERAL jsonb_array_elements(m.mutation #> '{{upserts,runs}}') r(payload)
                          WHERE m.session_id = %s
                        ) commands ORDER BY payload->>'created_at' DESC, payload->>'run_id' DESC LIMIT 1
                    """,
                        (session_id, session_id),
                    )
                    row = await cursor.fetchone()
                    return (
                        StartRun.model_validate(_decode(row[0]))
                        if row and row[0] is not None
                        else None
                    )
        await store.authorize_session_actor(session_id, context)
        runs = await store.list_session_runs(session_id)
        return await store.get_start_command(runs[-1].run_id) if runs else None

"""PostgreSQL read views projected from compact JSONB and its journal."""

import asyncio
from .._shared.aggregate import _decode_json as _json
from .._shared.read_views import replay_view_rows
from sagents.v2.runtime.session.read_views import (
    validate_view_ids,
    views_from_payload,
    legacy_owner_sessions,
)


def _projection(source, path=""):
    entries = ",".join(
        f"'{name}',COALESCE({source} #> '{{{path.replace('.', ',')}{name}}}', '[]'::jsonb)"
        for name in ("sessions", "runs", "suspensions", "interactions")
    )
    return f"jsonb_build_object({entries})"


class PostgresSessionReadQueries:
    async def read_session_views(self, session_ids, **options):
        store = self
        ids = validate_view_ids(session_ids, options.get("run_ids"))
        if not ids:
            return {}
        async with store._reader_connection() as connection:
            await store._begin_snapshot(connection)
            return await store._read_session_views_on_connection(
                connection, ids, **options
            )

    async def _read_session_views_on_connection(
        self, connection, session_ids, **options
    ):
        """Reuse the caller's read snapshot for legacy metadata authorization."""
        store = self
        ids = validate_view_ids(session_ids, options.get("run_ids"))
        if not ids:
            return {}
        marks = ",".join(["%s"] * len(ids))
        async with connection.cursor() as cursor:
            await cursor.execute(
                f"SELECT session_id,{_projection('compact_state')},revision,last_sequence "
                f"FROM {store._table('sessions')} WHERE session_id IN ({marks})",
                ids,
            )
            bases = await cursor.fetchall()
            delta = (
                "jsonb_build_object("
                + ",".join(
                    f"'{op}',{_projection('mutation', op + '.')}"
                    for op in ("upserts", "patches", "deletes")
                )
                + ")"
            )
            await cursor.execute(
                f"SELECT session_id,revision,{delta} FROM {store._table('session_mutations')} "
                f"WHERE session_id IN ({marks}) ORDER BY session_id,revision",
                ids,
            )
            mutations = await cursor.fetchall()
            states = await asyncio.to_thread(
                replay_view_rows, bases, mutations, **options
            )
            legacy = legacy_owner_sessions(states)
            conditions, params = [], []
            if (
                options.get("include_events")
                and states
                and (options.get("run_ids") is None or options["run_ids"])
            ):
                conditions.append(f"session_id IN ({marks})")
                params.extend(ids)
                run_ids = options.get("run_ids")
                if run_ids is not None:
                    conditions[-1] += (
                        " AND run_id IN (" + ",".join(["%s"] * len(run_ids)) + ")"
                    )
                    params.extend(run_ids)
            if legacy:
                conditions.append(
                    "session_id IN ("
                    + ",".join(["%s"] * len(legacy))
                    + ") AND event->>'type' = 'run.accepted'"
                )
                params.extend(legacy)
            if conditions:
                await cursor.execute(
                    f"SELECT session_id,run_id,event FROM {store._table('run_events')} WHERE "
                    + " OR ".join("(" + clause + ")" for clause in conditions)
                    + " ORDER BY session_sequence,run_sequence",
                    tuple(params),
                )
                for sid, rid, raw in await cursor.fetchall():
                    if sid in states:
                        states[sid]["run_events"].setdefault(rid, []).append(_json(raw))

        def decode():
            result = {}
            for state in states.values():
                result.update(views_from_payload(state, **options))
            return result

        return await asyncio.to_thread(decode)

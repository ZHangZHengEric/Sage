"""Bounded Run metadata and authorization directly over PostgreSQL JSONB."""

from datetime import datetime
from sagents.v2.runtime.session.run_metadata import RunMetadata
from sagents.v2.contracts.run_state import RunState


def postgres_metadata_cte(table, marks):
    return f"""WITH sources AS (
      SELECT s.session_id, r.payload, (s.compact_state #>> '{{sessions,0,revision}}')::bigint revision
      FROM {table("sessions")} s CROSS JOIN LATERAL jsonb_array_elements(s.compact_state->'runs') r(payload)
      WHERE s.session_id IN ({marks})
      UNION ALL
      SELECT m.session_id, r.payload, m.revision FROM {table("session_mutations")} m
      CROSS JOIN LATERAL jsonb_array_elements(m.mutation #> '{{upserts,runs}}') r(payload)
      WHERE m.session_id IN ({marks})
    ), admissions AS (
      SELECT *, payload->>'run_id' run_id,
        ROW_NUMBER() OVER (PARTITION BY session_id,payload->>'run_id' ORDER BY revision DESC) admission_position
      FROM sources
    ), state_sources AS (
      SELECT session_id,payload->>'run_id' run_id,payload->>'state' state,revision FROM sources
      UNION ALL
      SELECT m.session_id,r.payload->>'run_id',r.payload->>'state',m.revision
      FROM {table("session_mutations")} m
      CROSS JOIN LATERAL jsonb_array_elements(m.mutation #> '{{patches,runs}}') r(payload)
      WHERE m.session_id IN ({marks}) AND r.payload->>'state' IS NOT NULL
      UNION ALL
      SELECT m.session_id,r.payload->>0,'__deleted__',m.revision
      FROM {table("session_mutations")} m
      CROSS JOIN LATERAL jsonb_array_elements(m.mutation #> '{{deletes,runs}}') r(payload)
      WHERE m.session_id IN ({marks})
    ), latest_states AS (
      SELECT *,ROW_NUMBER() OVER (PARTITION BY session_id,run_id ORDER BY revision DESC) state_position
      FROM state_sources
    ), metadata AS (
      SELECT a.session_id,a.run_id,a.payload->>'created_at' created_at,s.state,
        CASE WHEN a.payload #>> '{{start_command,parent_run_id}}' IS NULL THEN
          COALESCE(NULLIF(a.payload #>> '{{start_command,config,metadata,server_v2.execution,agent_id}}',''),
                   NULLIF(a.payload #>> '{{start_command,config,metadata,server_v2.composition,agent,id}}',''),
                   a.payload #>> '{{start_command,agent_id}}')
          ELSE a.payload #>> '{{start_command,agent_id}}' END agent_id,
        COALESCE(a.payload #>> '{{start_command,invocation_mode}}','') invocation_mode,
        a.payload #> '{{start_command,config,metadata,task_name}}' task_name,
        a.payload #>> '{{start_command,agent_id}}' admitted_agent_id,
        head.created_at session_created_at,head.parent_session_id
      FROM admissions a JOIN latest_states s ON s.session_id=a.session_id AND s.run_id=a.run_id
      JOIN {table("sessions")} head ON head.session_id=a.session_id
      WHERE a.admission_position=1 AND s.state_position=1 AND s.state <> '__deleted__'
    ) """


def decode_metadata(row):
    values = list(row)
    values[2] = datetime.fromisoformat(values[2])
    values[3] = RunState(values[3])
    values[6] = values[6] if values[6] is not None else ""
    return RunMetadata(*values)


class PostgresRunMetadataQueries:
    async def _run_metadata_batch(self, session_ids):
        store = self
        ids = tuple(dict.fromkeys(session_ids))
        if not ids:
            return (), {}
        marks = ",".join(["%s"] * len(ids))
        async with store._reader_connection() as connection:
            async with connection.cursor() as cursor:
                await store._begin_snapshot(connection)
            async with connection.cursor() as cursor:
                await cursor.execute(
                    f"SELECT session_id,compact_state #> '{{sessions,0,owner}}' FROM {store._table('sessions')} WHERE session_id IN ({marks})",
                    ids,
                )
                owners = {row[0]: row[1] for row in await cursor.fetchall()}
                await cursor.execute(
                    postgres_metadata_cte(store._table, marks)
                    + "SELECT * FROM metadata",
                    ids * 4,
                )
                rows = tuple(decode_metadata(row) for row in await cursor.fetchall())
            # Legacy owners are derived from existing rows/events in this same
            # snapshot, without hydrating one execution aggregate per Session.
            legacy = tuple(sid for sid, owner in owners.items() if owner is None)
            if legacy:
                views = await store._read_session_views_on_connection(
                    connection, legacy, run_ids=()
                )
                for sid, view in views.items():
                    owners[sid] = view.owner
        return rows, owners

    async def authorized_run_metadata_page(
        self, session_ids, context, *, after=None, limit=101, agent_id="", states=()
    ):
        store = self
        from sagents.v2.contracts.errors import SageV2Error, ErrorCategory
        from sagents.v2.contracts.principals import ActorRef

        if not 1 <= limit <= 201 or len(session_ids) > 200:
            raise ValueError("invalid Run metadata page")
        ids = tuple(dict.fromkeys(session_ids))
        if not ids:
            return ()
        marks = ",".join(["%s"] * len(ids))
        async with store._reader_connection() as connection:
            async with connection.cursor() as cursor:
                await store._begin_snapshot(connection)
            async with connection.cursor() as cursor:
                await cursor.execute(
                    f"SELECT session_id,compact_state #> '{{sessions,0,owner}}' FROM {store._table('sessions')} WHERE session_id IN ({marks})",
                    ids,
                )
                allowed = set()
                legacy = []
                for sid, raw in await cursor.fetchall():
                    decoded = raw
                    if decoded is None:
                        legacy.append(sid)
                        continue
                    try:
                        store._authorize_session_owner(
                            ActorRef.model_validate(decoded), context
                        )
                    except SageV2Error as exc:
                        if exc.info.category != ErrorCategory.AUTHORIZATION:
                            raise
                    else:
                        allowed.add(sid)
                legacy_views = (
                    await store._read_session_views_on_connection(
                        connection, tuple(legacy), run_ids=()
                    )
                    if legacy
                    else {}
                )
                for sid, view in legacy_views.items():
                    try:
                        store._authorize_session_owner(view.owner, context)
                    except SageV2Error as exc:
                        if exc.info.category != ErrorCategory.AUTHORIZATION:
                            raise
                    else:
                        allowed.add(sid)
                selected = tuple(sid for sid in ids if sid in allowed)
                if not selected:
                    return ()
                marks = ",".join(["%s"] * len(selected))
                params = list(selected) * 4
                filters = ["1=1"]
                if agent_id:
                    filters.append("agent_id = %s")
                    params.append(agent_id)
                if states:
                    filters.append("state IN (" + ",".join(["%s"] * len(states)) + ")")
                    params.extend(
                        str(getattr(state, "value", state)) for state in states
                    )
                if after is not None:
                    sid, at, run_id = after
                    remaining = (
                        selected[selected.index(sid) :]
                        if sid in selected
                        else tuple(
                            item
                            for item in selected
                            if ids.index(item) > ids.index(sid)
                        )
                    )
                    if not remaining:
                        return ()
                    filters.append(
                        "session_id IN (" + ",".join(["%s"] * len(remaining)) + ")"
                    )
                    params.extend(remaining)
                    filters.append(
                        "(session_id <> %s OR created_at > %s OR (created_at = %s AND run_id > %s))"
                    )
                    params.extend((sid, at, at, run_id))
                ordering = (
                    "CASE session_id "
                    + " ".join("WHEN %s THEN " + str(i) for i in range(len(selected)))
                    + " END"
                )
                params.extend(selected)
                params.append(limit)
                await cursor.execute(
                    postgres_metadata_cte(store._table, marks)
                    + "SELECT * FROM metadata WHERE "
                    + " AND ".join(filters)
                    + " ORDER BY "
                    + ordering
                    + ",created_at,run_id LIMIT %s",
                    params,
                )
                return tuple(decode_metadata(row) for row in await cursor.fetchall())

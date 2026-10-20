"""Small Run metadata projected from existing compact/journal JSON."""
def mysql_metadata_cte(table, marks):
    fields = """run_id VARCHAR(128) PATH '$.run_id', created_at VARCHAR(64) PATH '$.created_at',
       state VARCHAR(32) PATH '$.state', agent_id VARCHAR(191) PATH '$.start_command.agent_id',
       grant_agent_id VARCHAR(191) PATH '$.start_command.config.metadata.\"server_v2.execution\".agent_id',
       invocation_mode VARCHAR(64) PATH '$.start_command.invocation_mode',
       task_name JSON PATH '$.start_command.config.metadata.task_name',
       parent_run_id VARCHAR(128) PATH '$.start_command.parent_run_id'"""
    return f"""WITH sources AS (
      SELECT s.session_id, r.*, CAST(JSON_UNQUOTE(JSON_EXTRACT(s.compact_state,'$.sessions[0].revision')) AS UNSIGNED) revision
      FROM {table('sessions')} s, JSON_TABLE(s.compact_state, '$.runs[*]' COLUMNS ({fields})) r
      WHERE s.session_id IN ({marks})
      UNION ALL
      SELECT m.session_id, r.*, m.revision FROM {table('session_mutations')} m,
        JSON_TABLE(m.mutation, '$.upserts.runs[*]' COLUMNS ({fields})) r WHERE m.session_id IN ({marks})
    ), admissions AS (
      SELECT *, ROW_NUMBER() OVER (PARTITION BY session_id,run_id ORDER BY revision DESC) admission_position FROM sources
    ), state_sources AS (
      SELECT session_id,run_id,state,revision FROM sources
      UNION ALL
      SELECT m.session_id,r.run_id,r.state,m.revision FROM {table('session_mutations')} m,
        JSON_TABLE(m.mutation, '$.patches.runs[*]' COLUMNS (
          run_id VARCHAR(128) PATH '$.run_id', state VARCHAR(32) PATH '$.state')) r
        WHERE m.session_id IN ({marks}) AND r.state IS NOT NULL
      UNION ALL
      SELECT m.session_id,r.run_id,'__deleted__',m.revision FROM {table('session_mutations')} m,
        JSON_TABLE(m.mutation, '$.deletes.runs[*]' COLUMNS (run_id VARCHAR(128) PATH '$[0]')) r
        WHERE m.session_id IN ({marks})
    ), latest_states AS (
      SELECT *, ROW_NUMBER() OVER (PARTITION BY session_id,run_id ORDER BY revision DESC) state_position FROM state_sources
    ), metadata AS (
      SELECT a.session_id,a.run_id,a.created_at,s.state,
             CASE WHEN a.parent_run_id IS NULL THEN COALESCE(a.grant_agent_id,a.agent_id) ELSE a.agent_id END agent_id,
             COALESCE(a.invocation_mode,'') invocation_mode,a.task_name,
             a.agent_id admitted_agent_id,head.created_at session_created_at,head.parent_session_id
      FROM admissions a JOIN latest_states s ON s.session_id=a.session_id AND s.run_id=a.run_id
      JOIN {table('sessions')} head ON head.session_id=a.session_id
      WHERE a.admission_position=1 AND s.state_position=1 AND s.state <> '__deleted__'
    ) """


def decode_metadata(row):
    import json
    from datetime import datetime, timezone
    from sagents.v2.runtime.session.run_metadata import RunMetadata
    from sagents.v2.contracts.run_state import RunState
    values = list(row)
    values[2] = datetime.fromisoformat(values[2])
    values[3] = RunState(values[3])
    values[6] = json.loads(values[6]) if values[6] is not None else ''
    values[8] = values[8].replace(tzinfo=timezone.utc) if values[8].tzinfo is None else values[8]
    return RunMetadata(*values)


class MysqlRunMetadataQueries:
    async def _run_metadata_batch(self, session_ids):
        import json
        ids = tuple(dict.fromkeys(session_ids))
        if not ids:
            return (), {}
        marks = ','.join(['%s'] * len(ids))
        async with self._reader_connection() as connection:
            await connection.begin()
            async with connection.cursor() as cursor:
                await cursor.execute(f"SELECT session_id,JSON_EXTRACT(compact_state,'$.sessions[0].owner') FROM {self._table('sessions')} WHERE session_id IN ({marks})", ids)
                owners = {row[0]: json.loads(row[1]) if row[1] is not None else None for row in await cursor.fetchall()}
                await cursor.execute(mysql_metadata_cte(self._table, marks) + 'SELECT * FROM metadata', ids * 4)
                rows = tuple(decode_metadata(row) for row in await cursor.fetchall())
        # Old archives may have no explicit owner. Preserve the canonical
        # earliest-context/accepted-actor derivation for Redis cold reads too.
        # Only these legacy records need the existing aggregate JSON fallback;
        # it neither installs execution objects nor rewrites stored state.
        from sagents.v2.runtime.session.run_metadata import metadata_from_payload
        for sid, owner in tuple(owners.items()):
            if owner is None:
                payload = await self._fetch_session(sid)
                if payload is not None:
                    _, derived = metadata_from_payload(payload)
                    owners[sid] = derived.get(sid)
        return rows, owners

    async def authorized_run_metadata_page(self, session_ids, context, *, after=None, limit=101, agent_id='', states=()):
        import json
        from sagents.v2.contracts.errors import SageV2Error, ErrorCategory
        from sagents.v2.contracts.principals import ActorRef
        if not 1 <= limit <= 201 or len(session_ids) > 200:
            raise ValueError('invalid Run metadata page')
        ids = tuple(dict.fromkeys(session_ids))
        if not ids:
            return ()
        marks = ','.join(['%s'] * len(ids))
        async with self._reader_connection() as connection:
            await connection.begin()
            async with connection.cursor() as cursor:
                await cursor.execute(f"SELECT session_id,JSON_EXTRACT(compact_state,'$.sessions[0].owner') FROM {self._table('sessions')} WHERE session_id IN ({marks})", ids)
                allowed = set()
                legacy = []
                for sid, raw in await cursor.fetchall():
                    decoded = json.loads(raw) if raw is not None else None
                    if decoded is None:
                        legacy.append(sid)
                        continue
                    try:
                        self._authorize_session_owner(ActorRef.model_validate(decoded), context)
                    except SageV2Error as exc:
                        if exc.info.category != ErrorCategory.AUTHORIZATION:
                            raise
                    else:
                        allowed.add(sid)
                for sid in legacy:
                    try:
                        await self.authorize_session_actor(sid, context)
                    except SageV2Error as exc:
                        if exc.info.category != ErrorCategory.AUTHORIZATION:
                            raise
                    else:
                        allowed.add(sid)
                selected = tuple(sid for sid in ids if sid in allowed)
                if not selected:
                    return ()
                marks = ','.join(['%s'] * len(selected))
                params = list(selected) * 4
                filters = ['1=1']
                if agent_id:
                    filters.append('agent_id = %s')
                    params.append(agent_id)
                if states:
                    filters.append('state IN (' + ','.join(['%s'] * len(states)) + ')')
                    params.extend(str(getattr(state, 'value', state)) for state in states)
                if after is not None:
                    sid, at, run_id = after
                    remaining = selected[selected.index(sid):] if sid in selected else tuple(item for item in selected if ids.index(item) > ids.index(sid))
                    if not remaining:
                        return ()
                    filters.append('session_id IN (' + ','.join(['%s'] * len(remaining)) + ')')
                    params.extend(remaining)
                    filters.append('(session_id <> %s OR created_at > %s OR (created_at = %s AND run_id > %s))')
                    params.extend((sid, at, at, run_id))
                ordering = 'CASE session_id ' + ' '.join('WHEN %s THEN ' + str(i) for i in range(len(selected))) + ' END'
                params.extend(selected)
                params.append(limit)
                await cursor.execute(mysql_metadata_cte(self._table, marks) + 'SELECT * FROM metadata WHERE ' + ' AND '.join(filters) + ' ORDER BY ' + ordering + ',created_at,run_id LIMIT %s', params)
                return tuple(decode_metadata(row) for row in await cursor.fetchall())

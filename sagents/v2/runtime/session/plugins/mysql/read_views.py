"""Batch small Session read views from the existing compact state and journal."""
import asyncio
import json

from sagents.v2.runtime.session.read_views import (
    apply_view_delta, project_view_state, validate_view_ids, views_from_payload, legacy_owner_sessions,
)


def _json(value):
    return json.loads(value) if isinstance(value,(str,bytes)) else value


def _projection(source, path=''):
    entries = ','.join(f"'{name}',COALESCE(JSON_EXTRACT({source},'$.{path}{name}'),JSON_ARRAY())"
                       for name in ('sessions','runs','suspensions','interactions'))
    return f'JSON_OBJECT({entries})'


def replay_view_rows(rows, mutations, **options):
    replay_options = {key: options[key] for key in ('include_events','run_ids') if key in options}
    states, heads = {}, {}
    for sid, raw, revision, last_sequence in rows:
        state = project_view_state(_json(raw),**replay_options)
        if len(state['sessions']) != 1 or state['sessions'][0]['session_id'] != sid:
            raise ValueError('Session read view has an invalid head')
        states[sid] = state
        heads[sid] = (int(revision),int(last_sequence))
    for sid, revision, raw in mutations:
        if sid not in states:
            continue
        state = states[sid]
        if int(revision) != int(state['sessions'][0]['revision']) + 1:
            raise ValueError('Session read view mutation revision gap')
        apply_view_delta(state,_json(raw),**replay_options)
        if len(state['sessions']) != 1 or int(state['sessions'][0]['revision']) != int(revision):
            raise ValueError('Session read view mutation head mismatch')
    for sid,state in states.items():
        if (int(state['sessions'][0]['revision']),int(state['sessions'][0]['last_sequence'])) != heads[sid]:
            raise ValueError('Session read view durable head mismatch')
    return states



class MysqlSessionReadQueries:
    async def read_session_views(self, session_ids, **options):
        ids = validate_view_ids(session_ids,options.get('run_ids'))
        if not ids:
            return {}
        async with self._reader_connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            await connection.begin()
            return await self._read_session_views_on_connection(connection,ids,**options)

    async def _read_session_views_on_connection(self, connection, session_ids, **options):
        """Reuse the caller's read snapshot for legacy metadata authorization."""
        ids = validate_view_ids(session_ids,options.get('run_ids'))
        if not ids:
            return {}
        marks = ','.join(['%s']*len(ids))
        async with connection.cursor() as cursor:
            await cursor.execute(f"SELECT session_id,{_projection('compact_state')},revision,last_sequence "
                f"FROM {self._table('sessions')} WHERE session_id IN ({marks})",ids)
            bases = await cursor.fetchall()
            delta = 'JSON_OBJECT(' + ','.join(f"'{op}',{_projection('mutation',op+'.')}" for op in ('upserts','patches','deletes')) + ')'
            await cursor.execute(f"SELECT session_id,revision,{delta} FROM {self._table('session_mutations')} "
                f"WHERE session_id IN ({marks}) ORDER BY session_id,revision",ids)
            mutations = await cursor.fetchall()
            states = await asyncio.to_thread(replay_view_rows,bases,mutations,**options)
            legacy = legacy_owner_sessions(states)
            conditions, params = [], []
            if options.get('include_events') and states and (options.get('run_ids') is None or options['run_ids']):
                conditions.append(f"session_id IN ({marks})")
                params.extend(ids)
                run_ids = options.get('run_ids')
                if run_ids is not None:
                    conditions[-1] += ' AND run_id IN (' + ','.join(['%s']*len(run_ids)) + ')'
                    params.extend(run_ids)
            if legacy:
                conditions.append('session_id IN (' + ','.join(['%s']*len(legacy)) + ") AND JSON_UNQUOTE(JSON_EXTRACT(event,'$.type')) = 'run.accepted'")
                params.extend(legacy)
            if conditions:
                await cursor.execute(f"SELECT session_id,run_id,event FROM {self._table('run_events')} WHERE "
                    + ' OR '.join('('+clause+')' for clause in conditions) + ' ORDER BY session_sequence,run_sequence',tuple(params))
                for sid,rid,raw in await cursor.fetchall():
                    if sid in states:
                        states[sid]['run_events'].setdefault(rid,[]).append(_json(raw))
        def decode():
            result = {}
            for state in states.values():
                result.update(views_from_payload(state,**options))
            return result
        return await asyncio.to_thread(decode)

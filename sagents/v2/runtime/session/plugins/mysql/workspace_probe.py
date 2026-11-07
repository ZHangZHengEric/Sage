"""Read current Run states without expanding every historical JSON document."""
import json

from sagents.v2.contracts.run_state import TERMINAL_RUN_STATES
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error

NAMESPACE = 'sage.workspace.lifecycle.v1'


async def write_projection(cursor, table, sid, revision, states):
    value = json.dumps({'revision': revision, 'states': states}, separators=(',', ':'))
    # A concurrent revision/deletion makes this read repair a no-op. Normal
    # writers call it inside the transaction that publishes that revision.
    await cursor.execute(f"""
        INSERT INTO {table('derived_state')} (session_id, namespace, `key`, value)
        SELECT session_id, %s, 'runs', CAST(%s AS JSON)
        FROM {table('sessions')} WHERE session_id = %s AND revision = %s
        ON DUPLICATE KEY UPDATE value = VALUES(value)
    """, (NAMESPACE, value, sid, revision))


def _rows(encoded):
    return (json.loads(encoded) if isinstance(encoded, (str, bytes)) else encoded) or ()


async def has_nonterminal_sessions(store, session_ids, *, include_descendants):
    ids = tuple(dict.fromkeys(session_ids))
    if not ids:
        return False
    repairs = []
    # locations and journal writes commit together. Keep the roster, reverse
    # journal pages and compact fallback in one snapshot, including compaction.
    async with store._reader_connection() as connection:
        async with connection.cursor() as cursor:
            await cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        await connection.begin()
        async with connection.cursor() as cursor:
            for offset in range(0, len(ids), 128):
                batch = ids[offset:offset + 128]
                marks = ','.join(['%s'] * len(batch))
                descendants = f"""
                    UNION DISTINCT
                    SELECT child.session_id FROM {store._table('sessions')} child
                    JOIN tree parent ON child.parent_session_id = parent.session_id
                """ if include_descendants else ""
                await cursor.execute(f"""
                    WITH RECURSIVE tree AS (
                        SELECT session_id FROM {store._table('sessions')}
                        WHERE session_id IN ({marks})
                        {descendants}
                    ) SELECT l.session_id, l.identity, s.revision, d.value
                    FROM tree JOIN {store._table('sessions')} s ON s.session_id = tree.session_id
                    JOIN {store._table('locations')} l
                      ON l.session_id = tree.session_id AND l.kind = 'run_id'
                    LEFT JOIN {store._table('derived_state')} d ON d.session_id = s.session_id
                      AND d.namespace = '{NAMESPACE}' AND d.`key` = 'runs'
                """, batch)
                pending_by_session = {}
                heads = {}
                for sid, run_id, revision, encoded in await cursor.fetchall():
                    pending_by_session.setdefault(sid, set()).add(run_id)
                    heads[sid] = (revision, json.loads(encoded) if isinstance(encoded, (str, bytes)) else encoded)
                for sid, pending in pending_by_session.items():
                    revision, projection = heads[sid]
                    if (isinstance(projection, dict) and projection.get('revision') == revision
                            and isinstance(projection.get('states'), dict)
                            and set(projection['states']) == pending):
                        if any(state not in TERMINAL_RUN_STATES for state in projection['states'].values()):
                            return True
                        continue
                    resolved = {}
                    before = None
                    page_size = 1
                    while pending:
                        bound = '' if before is None else ' AND revision < %s'
                        parameters = (sid,) if before is None else (sid, before)
                        await cursor.execute(f"""
                            SELECT revision,
                                JSON_EXTRACT(mutation, '$.patches.runs'),
                                JSON_EXTRACT(mutation, '$.upserts.runs')
                            FROM {store._table('session_mutations')}
                            WHERE session_id = %s {bound}
                            ORDER BY revision DESC LIMIT {page_size}
                        """, parameters)
                        rows = await cursor.fetchall()
                        if not rows:
                            break
                        for revision, patches, upserts in rows:
                            # Patches supersede upserts at the same revision;
                            # patches without state cannot resolve a Run.
                            for encoded in (patches, upserts):
                                for change in _rows(encoded):
                                    run_id, state = change.get('run_id'), change.get('state')
                                    if run_id in pending and state is not None:
                                        if state not in TERMINAL_RUN_STATES:
                                            return True
                                        resolved[run_id] = state
                                        pending.remove(run_id)
                            if not pending:
                                break
                        before = rows[-1][0]
                        if len(rows) < page_size:
                            break
                        page_size = min(page_size * 4, 32)
                    if pending:
                        await cursor.execute(f"""
                            SELECT JSON_EXTRACT(compact_state, '$.runs')
                            FROM {store._table('sessions')} WHERE session_id = %s
                        """, (sid,))
                        row = await cursor.fetchone()
                        for run in _rows(row[0] if row else None):
                            if run['run_id'] in pending:
                                if run.get('state') not in TERMINAL_RUN_STATES:
                                    return True
                                resolved[run['run_id']] = run['state']
                                pending.remove(run['run_id'])
                        if pending:
                            # Never authorize deletion from incomplete state.
                            raise SageV2Error(RuntimeErrorInfo(
                                code='session_store.workspace_state_missing',
                                category=ErrorCategory.RESOURCE_LOST,
                                message='Workspace Run state is missing',
                                safe_to_resume=False,
                            ))
                    repairs.append((sid, heads[sid][0], resolved))
    if repairs:
        async with store._writer_connection() as connection:
            try:
                async with connection.cursor() as cursor:
                    for sid, revision, states in repairs:
                        await write_projection(cursor, store._table, sid, revision, states)
                await connection.commit()
            except BaseException:
                await connection.rollback()
                raise
    return False

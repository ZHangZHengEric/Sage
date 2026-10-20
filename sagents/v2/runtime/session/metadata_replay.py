"""Read-only replay of Run/Session metadata without execution payload objects."""


def project_metadata_state(state):
    sessions = [{key: row.get(key) for key in ('session_id','owner','created_at','parent_session_id','revision','last_sequence')}
                for row in state.get('sessions', ())]
    runs = []
    for row in state.get('runs', ()):
        command = row.get('start_command') or {}
        config = command.get('config', {}).get('metadata', {})
        metadata = {key: config[key] for key in ('task_name','server_v2.execution') if key in config}
        composition = config.get('server_v2.composition')
        if isinstance(composition, dict) and isinstance(composition.get('agent'), dict):
            metadata['server_v2.composition'] = {'agent': {'id': composition['agent'].get('id')}}
        runs.append({key: row[key] for key in ('session_id','run_id','created_at','state')}
            | {'request_context': {'actor': (row.get('request_context') or {}).get('actor')},
               'start_command': {key: command.get(key) for key in ('agent_id','invocation_mode','parent_run_id')}
               | {'config': {'metadata': metadata}}})
    # Retain only accepted actors for legacy owner derivation. Context actors
    # must keep precedence over this fallback, including after later patches.
    accepted = {rid:[{key:event.get(key) for key in ('type','session_id','session_sequence','actor')}
                     for event in values if event.get('type') == 'run.accepted']
                for rid,values in state.get('run_events', {}).items()}
    return {'sessions': sessions, 'runs': runs, 'run_events': accepted}


def apply_metadata_delta(state, delta):
    for collection, key in (('sessions','session_id'),('runs','run_id')):
        current = {row[key]: row for row in state[collection]}
        for row in delta.get('upserts', {}).get(collection, ()):
            value = project_metadata_state({collection:[row]})[collection][0]
            current[row[key]] = value
        for patch in delta.get('patches', {}).get(collection, ()):
            if patch[key] not in current:
                raise ValueError('metadata patch refers to a missing row')
            for field in (('state',) if collection == 'runs' else tuple(patch)):
                if field in patch:
                    current[patch[key]][field] = patch[field]
        for deleted in delta.get('deletes', {}).get(collection, ()):
            current.pop(deleted[0], None)
        state[collection] = list(current.values())
    for operation in ('replacements','appends'):
        for rid, values in delta.get(operation, {}).get('run_events', {}).items():
            accepted = [{key:event.get(key) for key in ('type','session_id','session_sequence','actor')}
                        for event in values if event.get('type') == 'run.accepted']
            if operation == 'replacements':
                state['run_events'][rid] = accepted
            else:
                state['run_events'].setdefault(rid,[]).extend(accepted)
    for rid in delta.get('map_deletes', {}).get('run_events', ()):
        state['run_events'].pop(rid,None)
    return state


def read_filesystem_metadata(store, snapshot, *, project=project_metadata_state, apply=apply_metadata_delta):
    import json
    payload = store._read_snapshot_payload(snapshot)
    if payload.get('format') not in {'sage.filesystem-session-store/v2','sage.filesystem-session-store/v3','sage.filesystem-session-store/v4'}:
        raise ValueError('unsupported metadata snapshot format')
    revision = int(payload['current_session_revision'])
    state = project(payload['state'])
    journal = snapshot.parent / 'journal.jsonl'
    if journal.exists():
        with journal.open('rb') as stream:
            for line in stream:
                if not line.endswith(b'\n'):
                    break
                entry = json.loads(line)
                unsigned = {key:value for key,value in entry.items() if key != 'checksum'}
                if entry.get('checksum') != store._checksum(unsigned):
                    raise store._corrupt('session_store.hash_mismatch', 'metadata journal checksum mismatch')
                if int(entry['current_session_revision']) <= revision:
                    continue
                if int(entry['previous_session_revision']) != revision:
                    raise store._corrupt('session_store.revision_gap', 'metadata journal revision gap')
                state = apply(state, entry.get('mutation', entry.get('delta', {})))
                revision = int(entry['current_session_revision'])
                if int(state['sessions'][0]['revision']) != revision:
                    raise store._corrupt('session_store.revision_mismatch', 'metadata journal revision mismatch')
    if len(state['sessions']) != 1 or int(state['sessions'][0]['revision']) != revision:
        raise store._corrupt('session_store.revision_mismatch', 'metadata snapshot revision mismatch')
    return state


def decode_redis_metadata(fields, *, project=project_metadata_state, apply=apply_metadata_delta):
    import json
    state = project(json.loads(fields['base']))
    revision = int(state['sessions'][0]['revision'])
    for next_revision, encoded in sorted((int(key[2:]),value) for key,value in fields.items() if key.startswith('d:')):
        if next_revision != revision + 1:
            raise ValueError('metadata Redis revision gap')
        state = apply(state, json.loads(encoded))
        revision = next_revision
        if int(state['sessions'][0]['revision']) != revision:
            raise ValueError('metadata Redis revision mismatch')
    if revision != int(fields['revision']) or int(state['sessions'][0]['last_sequence']) != int(fields['last_sequence']):
        raise ValueError('metadata Redis head mismatch')
    return state


async def _read_redis_fields_batched(store, operations):
    """Cap each Redis reply batch at 32 commands and 256 projected fields."""
    results = []
    for start in range(0,len(operations),32):
        async with store._redis.pipeline(transaction=False) as pipe:
            for name,key,fields in operations[start:start+32]:
                if name == 'hget':
                    pipe.hget(key,fields)
                else:
                    pipe.hmget(key,fields)
            results.extend(await pipe.execute())
    return results


async def read_redis_metadata_batch(store, session_ids):
    """Batch the existing immutable-base protocol, including compaction checks."""
    import asyncio
    import json
    names = ('base_snapshot','base_parts','base_revision','revision','last_sequence','deleted')
    pending = list(session_ids)
    complete = {}
    for _ in range(5):
        if not pending:
            return complete
        heads = await _read_redis_fields_batched(store,
            [('hmget',store._session_key(sid),names) for sid in pending])
        fields = {sid:{key:value for key,value in zip(names, values) if value is not None}
                  for sid,values in zip(pending, heads)}
        operations, reads = [], []
        for sid, head in fields.items():
            if not head or head.get('deleted') == '1':
                continue
            if head.get('base_snapshot'):
                for start in range(0,int(head['base_parts']),8):
                    reads.append(('hmget',store._key('snapshot:' + head['base_snapshot']),
                        [str(i) for i in range(start,min(start+8,int(head['base_parts'])))]))
                    operations.append((sid,'parts'))
            else:
                reads.append(('hget',store._session_key(sid),'base'))
                operations.append((sid,'base'))
        bases = await _read_redis_fields_batched(store,reads)
        fragments = {}
        for (sid,kind), result in zip(operations,bases):
            if kind == 'parts':
                fragments.setdefault(sid,[]).extend(result)
            else:
                fields[sid]['base'] = result
        for sid, parts in fragments.items():
            if all(part is not None for part in parts):
                fields[sid]['base'] = ''.join(parts)
        deltas, reads = [], []
        for sid, head in fields.items():
            if not head or head.get('deleted') == '1' or not head.get('base'):
                continue
            if 'base_revision' not in head:
                head['base_revision'] = str(await asyncio.to_thread(lambda: int(json.loads(head['base'])['sessions'][0]['revision'])))
            for start in range(int(head['base_revision'])+1,int(head['revision'])+1,8):
                keys = [f'd:{i}' for i in range(start,min(start+8,int(head['revision'])+1))]
                reads.append(('hmget',store._session_key(sid),keys))
                deltas.append((sid,keys))
        values = await _read_redis_fields_batched(store,reads)
        for (sid,keys), values in zip(deltas,values):
            fields[sid].update(zip(keys,values))
        current = await _read_redis_fields_batched(store,
            [('hmget',store._session_key(sid),('base_snapshot','base_revision','deleted')) for sid in pending])
        retry = []
        for index, (sid, head) in enumerate(zip(pending, current)):
            value = fields[sid]
            original_head = dict(zip(names, heads[index]))
            expected = [original_head.get(key) for key in ('base_snapshot','base_revision','deleted')]
            if not value or value.get('deleted') == '1':
                complete[sid] = value
            elif head == expected and value.get('base') and all(item is not None for key,item in value.items() if key.startswith('d:')):
                complete[sid] = value
            else:
                retry.append(sid)
        pending = retry
    raise store._conflict('session.revision_conflict','Redis metadata base changed during loading')

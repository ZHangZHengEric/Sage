"""Recover task-local websites from successful native Sage file operations."""
import hashlib
from pathlib import PurePosixPath, PureWindowsPath

TOOLS = ('file_write', 'file_update', 'file_read', 'list_dir', 'turn_status', 'load_skill', 'read_lints')
MAX_BYTES = 1024 * 1024


def file_path(value, *, workspace_roots=()):
    if not isinstance(value, str) or '\x00' in value or len(value) > 8192:
        raise ValueError('Invalid website path')
    absolute_type = (PureWindowsPath if PureWindowsPath(value).is_absolute() else
        PurePosixPath if PurePosixPath(value).is_absolute() else None)
    mapped = set()
    if absolute_type is not None:
        absolute = absolute_type(value)
        if '..' in absolute.parts:
            raise ValueError('Invalid website path')
        for root in workspace_roots:
            base = absolute_type(root)
            if base.is_absolute() and absolute.is_relative_to(base):
                mapped.add(absolute.relative_to(base).as_posix())
        if len(mapped) > 1:
            raise ValueError('Ambiguous workspace path mapping')
    if mapped:
        value = mapped.pop()
    elif value.startswith('/workspace/'):
        value = value[len('/workspace/'):]
    elif absolute_type is not None:
        raise ValueError('Absolute project path is outside the attested workspace')
    if '\\' in value:
        raise ValueError('Invalid website path')
    if value.startswith('./'):
        value = value[2:]
    path = PurePosixPath(value)
    if not value or not path.parts or path.is_absolute() or '..' in path.parts or len(value) > 200:
        raise ValueError('Use a relative project file path')
    return str(path)


def attested_workspace_roots(observation):
    evidence = observation.get('evidence') or {}
    info = evidence.get('workspace_attestation')
    if info is None:
        return ()
    if (not isinstance(info, dict) or info.get('protocol') != 'sage.rsi.workspace/v1'
            or not isinstance(evidence.get('run_id'), str) or not evidence['run_id']
            or info.get('run_id') != evidence['run_id']):
        raise ValueError('Unbound host workspace attestation')
    roots = info.get('roots')
    if (not isinstance(roots, (list, tuple)) or not 1 <= len(roots) <= 4
            or any(not isinstance(p, str) or len(p) > 8192 or '..' in PurePosixPath(p).parts
                or '..' in PureWindowsPath(p).parts or not (PurePosixPath(p).is_absolute()
                or PureWindowsPath(p).is_absolute()) for p in roots)):
        raise ValueError('Invalid host workspace roots')
    return tuple(roots)


def native_value(result):
    values = [b['value'] for b in result.get('content', ()) if b.get('kind') == 'json']
    if len(values) != 1 or not isinstance(values[0], dict):
        raise ValueError('Native file mutation requires a complete structured result')
    return values[0]


def final_files(observation, roots):
    evidence = observation.get('evidence') or {}
    snapshot = evidence.get('workspace_files')
    if snapshot is None:
        return None
    if (not isinstance(snapshot, dict) or not roots or not evidence.get('run_id')
            or snapshot.get('protocol') != 'sage.rsi.workspace-files/v1'
            or snapshot.get('run_id') != evidence['run_id']):
        raise ValueError('Unbound final workspace files')
    if snapshot.get('complete') is not True:
        return None  # A bounded/incomplete snapshot cannot replace receipt replay.
    if observation.get('state') != 'completed' or not isinstance(snapshot.get('files'), dict):
        raise ValueError('Final workspace files require a terminal native execution')
    files = {}
    for name, value in snapshot['files'].items():
        if file_path(name) != name or not isinstance(value, dict) or not isinstance(value.get('content'), str):
            raise ValueError('Invalid final workspace file')
        data = value['content'].encode()
        if hashlib.sha256(data).hexdigest() != value.get('sha256'):
            raise ValueError('Final workspace content hash mismatch')
        files[name] = value['content']
    size = sum(len(v.encode()) for v in files.values())
    if size != snapshot.get('bytes') or len(files) > 64 or size > MAX_BYTES:
        raise ValueError('Final website exceeds source bounds or byte receipt')
    return files


def replay(request):
    from evaluation_datasets._support import native_events
    from sagents.v2.tool.official.filesystem import _apply_update_operations
    events = native_events(request, allow_closed=True)
    workspace_roots = attested_workspace_roots(request['observation'])
    snapshot = final_files(request['observation'], workspace_roots)
    results = {e['tool_call_id']: e for e in events if e.get('kind') == 'tool_result'}
    batches = {e['data']['tool_call_id']: (e.get('run_id'), e.get('step_id'))
        for e in request['observation']['evidence']['final_items'] if e.get('data', {}).get('kind') == 'tool_call'}
    files, trace, seen, written, mutated = {}, [], set(), set(), set()
    if request['observation'].get('state') != 'completed':
        from sagents.v2.optimization.contracts import OptimizationCase, OptimizationObservation
        from sagents.v2.optimization.native_episode import close_single_turn_episode
        closed = close_single_turn_episode(OptimizationObservation.model_validate(request['observation']),
            OptimizationCase.model_validate(request['case']))
        if closed is None:
            raise ValueError('Native loop closure could not be verified')
        trace.append({'kind':'episode_boundary','native_state':closed.state,
            'episode_termination':closed.evidence['episode_termination']})
    for event in events:
        if event.get('kind') == 'message' and event.get('role') == 'assistant':
            text = ''.join(b.get('text', '') for b in event.get('content', ()) if b.get('kind') == 'text')
            if text:
                trace.append({'kind': 'assistant', 'text': text})
        if event.get('kind') != 'tool_call':
            continue
        identity, name = event['tool_call_id'], event['tool_name']
        if identity in seen:
            raise ValueError('Duplicate native tool call')
        seen.add(identity)
        result = results[identity]
        args = {k: v for k, v in event['arguments'].items() if k != 'session_id'}
        record = {'kind': 'tool', 'tool': name, 'arguments': dict(args), 'success': not bool(result.get('error'))}
        if name == 'file_write' and isinstance(args.get('content'), str):
            content = record['arguments'].pop('content')
            record['arguments'].update(content_sha256=hashlib.sha256(content.encode()).hexdigest(), content_characters=len(content))
        if name == 'file_update':
            operations = []
            for operation in args.get('operations') or ():
                compact = dict(operation)
                for key in ('replacement', 'search_pattern'):
                    value = compact.get(key)
                    if isinstance(value, str) and len(value) > 512:
                        compact[key] = {'preview': value[:256], 'characters': len(value),
                            'sha256': hashlib.sha256(value.encode()).hexdigest()}
                operations.append(compact)
            record['arguments']['operations'] = operations
        error = result.get('error') or {}
        if error:
            record['error_code'] = error.get('code')
        trace.append(record)
        if name not in {'file_write', 'file_update'}:
            if not error:
                values = [b.get('value') for b in result.get('content', ()) if b.get('kind') == 'json']
                if values and isinstance(values[0], dict):
                    record['result'] = {k: v for k, v in values[0].items()
                        if k in {'status', 'file_path', 'start_line', 'end_line', 'total_lines', 'note', 'diagnostics', 'diagnostics_count', 'truncated', 'linters', 'skipped_linters', 'passed', 'success', 'unsupported_paths', 'coverage'}}
                if result.get('metadata', {}).get('result_offloaded'):
                    record['result_was_previewed'] = True
            if not error and name not in TOOLS:
                raise ValueError('Unsupported successful tool may have changed the website')
            continue
        if error:
            if error.get('code') == 'tool.arguments_invalid' or error.get('metadata', {}).get('side_effect_state') == 'not_applied':
                continue
            raise ValueError('Failed file mutation has uncertain effects')
        receipt = native_value(result)
        record['result'] = receipt
        if receipt.get('status') != 'success' or receipt.get('file_path') != args.get('file_path'):
            raise ValueError('Native file receipt does not match the operation')
        path = file_path(args['file_path'], workspace_roots=workspace_roots)
        mutated.add(path)
        if snapshot is not None:
            # Native read/modify/write calls can overlap. The host captured the
            # actual terminal bytes before disposal; never guess a linear order.
            record['final_file_authority'] = 'host_terminal_workspace'
            continue
        batch = (*batches.get(identity, (None, None)), path)
        if batch in written:
            raise ValueError('Concurrent mutations to the same file have ambiguous ordering')
        written.add(batch)
        if name == 'file_write':
            mode = args.get('mode', 'overwrite')
            if mode not in {'overwrite', 'append'} or receipt.get('mode') != mode or not isinstance(args.get('content'), str):
                raise ValueError('Invalid file-write receipt')
            content = (files.get(path, '') if mode == 'append' else '') + args['content']
        else:
            if path not in files:
                raise ValueError('Cannot replay an update to an unrecorded file')
            content, summaries, replacements = _apply_update_operations(files[path], args.get('operations') or [])
            if content == files[path]:
                replacements = 0  # Matches OfficialToolPlugin.file_update.
            if receipt.get('replacements') != replacements or receipt.get('operations') != summaries:
                raise ValueError('File-update result differs from replay')
        files[path] = content
        if len(files) > 64 or sum(len(v.encode()) for v in files.values()) > MAX_BYTES:
            raise ValueError('Website exceeds 64 files or 1 MiB of source')
    if snapshot is not None:
        if set(snapshot) != mutated:
            raise ValueError('Final workspace files do not match recorded native mutations')
        return snapshot, trace
    return files, trace

"""Host-owned final text files, captured before an isolated workspace is removed."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath


def local_workspace(configuration):
    binding = configuration.runtime.capabilities.get('execution.binding')
    if (getattr(binding, 'plugin', None) == 'sage.execution.binding.local-workspace'
            and isinstance(binding.config.get('workspace'), str)):
        return Path(binding.config['workspace'])
    return None


def relative_path(value, roots):
    if not isinstance(value, str) or '\x00' in value or '\\' in value:
        raise ValueError('Invalid recorded file path')
    path = PurePosixPath(value)
    if '..' in path.parts:
        raise ValueError('Recorded file path escapes workspace')
    if path.is_absolute():
        matches = {path.relative_to(root).as_posix() for root in map(PurePosixPath, roots)
                   if path.is_relative_to(root)}
        if not matches and value.startswith('/workspace/'):
            matches = {value[len('/workspace/'):]}
        if len(matches) != 1:
            raise ValueError('Recorded file path is outside workspace')
        path = PurePosixPath(matches.pop())
    if not path.parts or str(path) == '.':
        raise ValueError('Recorded file path is not a file')
    return path.as_posix()


def read_private_text(root, name, remaining):
    """Never follow directory or file symlinks, including during open."""
    if (not all(hasattr(os, flag) for flag in ('O_DIRECTORY', 'O_NOFOLLOW', 'O_NONBLOCK'))
            or os.open not in os.supports_dir_fd):
        # Retain strict receipt replay on platforms without a secure openat;
        # never substitute a path-based read that could follow a raced symlink.
        raise OSError('Secure workspace snapshot is unavailable on this platform')
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        parts = PurePosixPath(name).parts
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, 'rb') as stream:
            import stat
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError('Recorded file is not regular')
            data = stream.read(remaining + 1)
            if len(data) > remaining:
                raise ValueError('Workspace text snapshot exceeds its byte bound')
        return data
    finally:
        os.close(directory)


def attest_files(observation, workspace):
    roots = list(dict.fromkeys((Path(os.path.abspath(workspace)).as_posix(),
                              Path(workspace).resolve().as_posix())))
    run_id = observation.evidence.get('run_id')
    evidence = {**observation.evidence, 'workspace_attestation': {
        'protocol': 'sage.rsi.workspace/v1', 'run_id': run_id, 'roots': roots}}
    # Only terminal runs have no outstanding native writes. Suspended episodes
    # retain receipt replay; no snapshot is allowed to hide unresolved effects.
    if observation.state != 'completed':
        return evidence
    items = observation.evidence.get('final_items', ())
    results = {v['data'].get('tool_call_id'): v['data'] for v in items
               if v.get('data', {}).get('kind') == 'tool_result'}
    names, files, errors, size = set(), {}, [], 0
    try:
        for item in items:
            call = item.get('data', {})
            if call.get('kind') != 'tool_call' or call.get('tool_name') not in {'file_write', 'file_update'}:
                continue
            result = results.get(call.get('tool_call_id'))
            if result is None:
                raise ValueError('File mutation has no terminal receipt')
            if not result.get('error'):
                names.add(relative_path(call.get('arguments', {}).get('file_path'), roots))
        if len(names) > 512:
            raise ValueError('Workspace text snapshot exceeds its file bound')
        for name in sorted(names):
            data = read_private_text(roots[-1], name, 4 * 1024 * 1024 - size)
            files[name] = {'content': data.decode('utf-8'), 'sha256': hashlib.sha256(data).hexdigest()}
            size += len(data)
    except (OSError, ValueError, UnicodeError) as error:
        errors.append(type(error).__name__)
    evidence['workspace_files'] = {'protocol': 'sage.rsi.workspace-files/v1', 'run_id': run_id,
        'complete': not errors, 'files': files, 'bytes': size, 'errors': errors}
    return evidence

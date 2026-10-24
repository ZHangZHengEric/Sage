"""Bind local scorer code/data and the Python environment to an admitted version.

This is integrity checking for trusted host code, not a Python security sandbox.
Repository benchmark packages are captured in full; other lazy resources can be
listed explicitly in SCORER_DEPENDENCIES. Runtime state and bytecode are excluded.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import sysconfig

PROTOCOL = 'sage.rsi.scorer-dependencies/v1'
_IGNORED = {'__pycache__', '.runtime', '.git', '.venv', 'node_modules'}


class ScorerDependencyError(ValueError):
    pass


def _digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _binding(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':')).encode()).hexdigest()


def dependency_binding(source_hash, manifest):
    return _binding({'source': source_hash, 'dependencies': manifest['binding']}) if manifest else source_hash


def _ignored(path):
    return any(part in _IGNORED for part in path.parts) or path.suffix in {'.pyc', '.pyo'}


def _members(root):
    if not root.is_dir():
        raise ScorerDependencyError('frozen scorer dependencies changed')
    return sorted(p.relative_to(root).as_posix() for p in root.rglob('*')
        if not _ignored(p.relative_to(root)) and p.is_file())


def _environment():
    versions = sorted({(d.metadata['Name'].lower().replace('_', '-'), d.version)
        for d in importlib.metadata.distributions() if d.metadata.get('Name')})
    return {'python': sys.version, 'platform': sys.platform, 'distributions': [list(v) for v in versions]}


def verify_dependencies(manifest):
    """Check membership as well as hashes: a newly added module can change imports."""
    try:
        content = {k: v for k, v in manifest.items() if k != 'binding'}
        if manifest.get('protocol') != PROTOCOL or _binding(content) != manifest['binding']:
            raise ScorerDependencyError('frozen scorer dependencies changed')
        if manifest['environment'] != _environment():
            raise ScorerDependencyError('frozen scorer dependencies changed')
        for root, members in manifest['trees'].items():
            if _members(Path(root)) != members:
                raise ScorerDependencyError('frozen scorer dependencies changed')
        for name, digest in manifest['files'].items():
            if _digest(Path(name)) != digest:
                raise ScorerDependencyError('frozen scorer dependencies changed')
    except (OSError, KeyError, TypeError) as error:
        raise ScorerDependencyError('frozen scorer dependencies changed') from error


def verify_capture(expected, observed):
    """A new case may use fewer pinned files, never new unbound dependencies."""
    if expected['environment'] != observed['environment']:
        raise ScorerDependencyError('frozen scorer dependencies changed')
    if any(expected['files'].get(name) != digest for name, digest in observed['files'].items()):
        raise ScorerDependencyError('frozen scorer dependencies changed')
    if any(expected['trees'].get(root) != members for root, members in observed['trees'].items()):
        raise ScorerDependencyError('frozen scorer dependencies changed')


class DependencyCapture:
    def __init__(self, entry):
        self.entry = Path(entry).resolve()
        self.files = {}
        self.active, self.hashing = True, False
        # Installed libraries are version-bound rather than hashing large native
        # binaries on every case. Editable source outside these roots is hashed.
        self.installations = {Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve(),
            Path(sysconfig.get_path('stdlib')).resolve()}
        sys.addaudithook(self._audit)

    def _local(self, path):
        return (path != self.entry and not _ignored(path)
            and not any(path.is_relative_to(root) for root in self.installations))

    def _capture(self, path):
        path = Path(path).resolve()
        if not self._local(path) or not path.is_file():
            return
        key, digest = str(path), _digest(path)
        if key in self.files and self.files[key] != digest:
            raise ScorerDependencyError('frozen scorer dependencies changed')
        self.files[key] = digest

    def _audit(self, event, args):
        if not self.active or self.hashing or event != 'open' or not isinstance(args[0], (str, bytes)):
            return
        name, mode, flags = args
        if (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (
                isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)):
            return
        self.hashing = True
        try:
            path = Path(os.fsdecode(name)).resolve()
            # Hash a read once; finish() checks it again after execution.
            if str(path) not in self.files:
                self._capture(path)
        finally:
            self.hashing = False

    def finish(self, module, *, declaration="SCORER_DEPENDENCIES"):
        self.active = False
        roots = set()
        for name, imported in tuple(sys.modules.items()):
            file = getattr(imported, '__file__', None)
            if file and Path(file).suffix in {'.py', '.pyc'}:
                source = Path(file)
                if source.suffix == '.pyc':
                    import importlib.util
                    try:
                        source = Path(importlib.util.source_from_cache(str(source)))
                    except ValueError:
                        continue
                self._capture(source)
            # Our benchmark adapters import a small entrypoint but score many
            # different upstream tasks. Pin every packaged scenario and source.
            if name.startswith('evaluation_datasets.'):
                package = sys.modules.get('.'.join(name.split('.')[:2]))
                for root in getattr(package, '__path__', ()):
                    roots.add(Path(root).resolve())
        declared = getattr(module, declaration, ())
        if not isinstance(declared, (tuple, list)) or any(not isinstance(p, str) for p in declared):
            raise ValueError(f'{declaration} must be a list of file/directory paths')
        for name in declared:
            path = Path(name)
            path = (self.entry.parent / path).resolve() if not path.is_absolute() else path.resolve()
            if path.is_dir():
                roots.add(path)
            elif path.is_file():
                # Explicit declarations can bind installed resources too.
                self.files[str(path)] = _digest(path)
            else:
                raise ValueError('Declared scorer dependency does not exist')
        trees = {}
        for root in sorted(roots):
            members = _members(root)
            trees[str(root)] = members
            for name in members:
                path = (root / name).resolve()
                self.files[str(path)] = _digest(path)
        # Also catch modifications to files read during validation/execution.
        for name, digest in self.files.items():
            if _digest(Path(name)) != digest:
                raise ScorerDependencyError('frozen scorer dependencies changed')
        result = {'protocol': PROTOCOL, 'files': dict(sorted(self.files.items())),
            'trees': trees, 'environment': _environment()}
        return {**result, 'binding': _binding(result)}

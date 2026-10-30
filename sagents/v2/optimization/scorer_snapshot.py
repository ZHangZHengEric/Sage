"""Content-addressed worker sources, separate from an editable checkout."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile


def freeze_worker_sources(destination, *, source_root, dependency_manifest):
    root = Path(source_root).resolve()
    roots = {root / 'sagents'}
    for name in dependency_manifest.get('trees', {}):
        path = Path(name).resolve()
        if path.is_relative_to(root):
            roots.add(path)
    files = {}
    ignored = {'.venv', '__pycache__', '.git', '.runtime', 'node_modules'}
    for directory in roots:
        for base, dirs, names in os.walk(directory):
            dirs[:] = sorted(d for d in dirs if d not in ignored)
            for name in sorted(names):
                path = Path(base) / name
                if path.is_symlink():
                    raise ValueError('Worker source snapshots cannot contain symlinks')
                relative = path.relative_to(root)
                files[str(relative)] = hashlib.sha256(path.read_bytes()).hexdigest()
        # Preserve namespace/package boundaries, without copying unrelated datasets.
        parent = directory.parent
        while parent != root and parent.is_relative_to(root):
            init = parent / '__init__.py'
            if init.is_file():
                files[str(init.relative_to(root))] = hashlib.sha256(init.read_bytes()).hexdigest()
            parent = parent.parent
    # Modules beside a dataset package (for example evaluation_datasets/_support.py)
    # are imported dependencies too, even when not members of a captured tree.
    for name in dependency_manifest.get('files', {}):
        path = Path(name).resolve()
        if path.is_relative_to(root):
            files[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    identity = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    target = Path(destination) / identity
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        temporary = Path(tempfile.mkdtemp(prefix='.snapshot-', dir=target.parent))
        try:
            for relative, digest in files.items():
                out = temporary / relative
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(root / relative, out)
                if hashlib.sha256(out.read_bytes()).hexdigest() != digest:
                    raise ValueError('Worker sources changed during snapshot creation')
                out.chmod(0o444)
            (temporary / 'snapshot.json').write_text(json.dumps(files, sort_keys=True))
            try:
                temporary.rename(target)
            except OSError:
                if not target.is_dir():
                    raise
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    for relative, digest in files.items():
        if hashlib.sha256((target / relative).read_bytes()).hexdigest() != digest:
            raise ValueError('Frozen worker source snapshot changed')
    return target

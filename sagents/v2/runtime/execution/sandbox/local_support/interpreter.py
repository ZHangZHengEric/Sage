"""Validation of the trusted isolation helper, separate from Agent commands."""

from __future__ import annotations

import hashlib
from functools import lru_cache
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys


_PROBE = """import json,sys,os,sysconfig
assert sys.implementation.name == 'cpython'
print(json.dumps({'executable':os.path.realpath(sys.executable),
 'version':list(sys.version_info[:3]),
 'paths':sorted(set(os.path.realpath(p) for p in
 [sys.prefix,sys.base_prefix,*sys.path] if p and os.path.isdir(p)))}))
"""


def inspect_isolation_python(executable: str | None = None, *, forbidden_roots=()) -> dict:
    """Probe real CPython in isolated mode without inheriting loader variables."""
    candidate = Path(executable or sys.executable).expanduser().resolve(strict=True)
    if getattr(sys, "frozen", False) and candidate == Path(sys.executable).resolve():
        raise ValueError("frozen hosts must configure isolation_python as real CPython")
    for root in forbidden_roots:
        root = Path(root).resolve()
        if candidate == root or root in candidate.parents:
            raise ValueError("isolation_python must be outside writable workspaces")
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        raise ValueError("isolation_python must be an executable CPython file")
    stat = candidate.stat()
    with candidate.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    identity = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, digest)
    report = deepcopy(_probe_python(str(candidate), identity))
    if any(not Path(path).is_dir() for path in report["paths"]):
        _probe_python.cache_clear()
        report = deepcopy(_probe_python(str(candidate), identity))
    return report


@lru_cache(maxsize=64)
def _probe_python(executable, identity):
    # Trust and workspace checks precede this cache. Executable bytes and inode
    # identity are checked on every use; unrelated Runs can reuse the same probe.
    candidate = Path(executable)
    result = subprocess.run(
        [str(candidate), "-I", "-c", _PROBE], check=True,
        capture_output=True, text=True, timeout=20,
        env={"PATH": os.defpath, "LANG": "C"},
    )
    report = json.loads(result.stdout)
    if Path(report["executable"]).resolve() != candidate:
        raise ValueError("isolation_python must directly execute real CPython")
    if report["version"][:2] < [3, 10]:
        raise ValueError("isolation_python requires CPython 3.10 or later")
    stat = candidate.stat()
    if (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns) != identity[:5]:
        raise ValueError("isolation_python changed during validation")
    report["sha256"] = identity[-1]
    return report

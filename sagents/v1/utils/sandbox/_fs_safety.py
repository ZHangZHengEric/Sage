"""Shared filesystem-safety primitives for in-process sandbox providers.

The ``Local`` and ``Passthrough`` providers both resolve a candidate host path,
confirm it stays within an allowed set of roots, and write files on the host
filesystem. Each historically carried its own near-identical copy of the
containment check and a truncating writer. This module holds the single
implementation both import, so the safety contract has exactly one place to
reason about.

Remote providers operate on paths inside a separate sandbox and do not share
this host-side logic; bringing them under the same contract is tracked as
follow-up work.
"""

from __future__ import annotations

import os
import stat
import sys
import tempfile
from functools import lru_cache
from typing import Any, List, Optional, Tuple

# Operations that mutate the filesystem; read-only mounts reject these.
WRITE_OPERATIONS = frozenset({"write", "delete", "mkdir"})


def _process_umask() -> int:
    # os has no getter for the umask; the set-and-restore dance is the standard
    # way to read it. Captured once at import (process startup is single
    # threaded) to avoid racing the process-global umask from worker threads.
    current = os.umask(0)
    os.umask(current)
    return current


# Mode applied to a newly created file. Matches what ``open(path, "w")`` would
# produce (0o666 restricted by the process umask), so atomic writes never make a
# new file more permissive than an ordinary write would have. Existing files
# keep their own mode instead (see ``write_text``).
DEFAULT_FILE_MODE = 0o666 & ~_process_umask()


def dedupe_roots(roots: List[Tuple[str, bool]]) -> List[Tuple[str, bool]]:
    """Collapse duplicate allowed roots, longest path first.

    ``roots`` is a list of ``(host_path, read_only)`` pairs. Duplicates are
    merged; the merge keeps the historical semantics where a root counts as
    read-only only when every occurrence is read-only. Sorting longest-first
    lets callers match the most specific mount before its parents.
    """
    deduped: dict[str, bool] = {}
    for root, read_only in roots:
        if not root:
            continue
        deduped[root] = deduped.get(root, True) and read_only
    return sorted(deduped.items(), key=lambda item: len(item[0]), reverse=True)


def path_under_root(path: str, root: str) -> bool:
    """Return True when ``path`` is ``root`` or lives beneath it."""
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:
        # Raised when the paths live on different drives (Windows) or mix
        # absolute and relative; treat as "not contained".
        return False


def resolve_within_roots(
    host_path: str,
    allowed_roots: List[Tuple[str, bool]],
    *,
    operation: str,
    read_only_label: str,
) -> str:
    """Resolve ``host_path`` and confirm it stays within ``allowed_roots``.

    Returns the fully resolved (``realpath``) host path. Symlinks and ``..``
    segments are collapsed before the containment check, so a path that escapes
    the allowed roots — directly or through a link — is rejected with
    ``PermissionError`` rather than silently followed.

    Args:
        host_path: Candidate host path (may be relative or contain symlinks).
        allowed_roots: ``(root, read_only)`` pairs, e.g. from ``dedupe_roots``.
        operation: One of ``read``/``write``/``delete``/``mkdir``; write-like
            operations are refused on read-only roots.
        read_only_label: Sandbox name used in the read-only error message so
            each provider keeps its existing wording.
    """
    actual = os.path.realpath(os.path.abspath(host_path))
    write_operation = operation in WRITE_OPERATIONS
    for root, read_only in allowed_roots:
        if path_under_root(actual, root):
            if write_operation and read_only:
                raise PermissionError(
                    f"Path is read-only in {read_only_label}: {host_path}"
                )
            return actual

    allowed = ", ".join(root for root, _ in allowed_roots) or "<none>"
    raise PermissionError(
        f"Access denied: path outside sandbox workspace or mounted paths: {host_path}. "
        f"Allowed roots: {allowed}"
    )


@lru_cache(maxsize=1)
def _darwin_copyfile() -> Optional[Any]:
    """Return macOS copyfile(3) for builds without os.*xattr."""
    if sys.platform != "darwin":
        return None

    import ctypes

    try:
        libc = ctypes.CDLL(None, use_errno=True)
        copy_file = libc.copyfile
    except (AttributeError, OSError):
        return None
    copy_file.argtypes = [
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    copy_file.restype = ctypes.c_int
    return copy_file


def _copy_xattrs(source: str, destination: str) -> None:
    """Copy accessible extended attributes without making writes less reliable."""
    if all(hasattr(os, name) for name in ("listxattr", "getxattr", "setxattr")):
        try:
            names = os.listxattr(source)
        except OSError:
            return
        for name in names:
            try:
                os.setxattr(destination, name, os.getxattr(source, name))
            except OSError:
                # Attributes can disappear or be system-managed. Preserve the
                # attributes still accessible without failing the content write.
                continue
        return

    copy_file = _darwin_copyfile()
    if copy_file is not None:
        # COPYFILE_XATTR from <copyfile.h>. copyfile(3) returns non-zero on
        # failure; metadata preservation is intentionally best effort.
        copy_file(os.fsencode(source), os.fsencode(destination), None, 1 << 2)


def write_text(
    actual_path: str,
    content: str,
    encoding: str = "utf-8",
    mode: str = "overwrite",
) -> None:
    """Write ``content`` to an already-resolved host path.

    ``overwrite`` is atomic: content is written to a temporary file in the same
    directory and then ``os.replace``d into place. A reader therefore sees
    either the old file or the fully written new one — never a truncated
    intermediate — and a write interrupted before ``os.replace`` leaves the
    original untouched. This guarantees atomicity for concurrent readers and
    against mid-write interruption, not power-loss durability (the parent
    directory is not fsynced).

    Because ``os.replace`` swaps the inode instead of truncating in place, an
    overwrite carries over the previous file's permission bits, ownership, and
    extended attributes on platforms that expose them (the latter two best
    effort), but it does not keep hard links to the old inode pointing at the new
    content, and it briefly needs extra space for the temporary copy. A newly
    created file uses ``DEFAULT_FILE_MODE``.

    ``append`` appends to the existing file (creating it if absent). A torn
    append can leave trailing bytes but never destroys existing content, so it
    keeps the plain append path.

    ``actual_path`` is expected to already be resolved and validated by the
    caller (see ``resolve_within_roots``).
    """
    parent = os.path.dirname(actual_path) or "."
    os.makedirs(parent, exist_ok=True)

    if mode == "append":
        with open(actual_path, "a", encoding=encoding) as handle:
            handle.write(content)
        return

    try:
        existing = os.stat(actual_path)
    except FileNotFoundError:
        existing = None
    target_mode = stat.S_IMODE(existing.st_mode) if existing else DEFAULT_FILE_MODE
    fd, tmp_path = tempfile.mkstemp(dir=parent, prefix=".sage-tmp-")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as handle:
            handle.write(content)
        os.chmod(tmp_path, target_mode)
        # Preserve the replaced file's ownership when we can. This is a no-op in
        # the common same-user case and only matters when a privileged process
        # rewrites another user's file; if the chown is not permitted we keep
        # the writing process's ownership rather than fail the write.
        if existing is not None and hasattr(os, "chown"):
            try:
                os.chown(tmp_path, existing.st_uid, existing.st_gid)
            except OSError:
                pass
        if existing is not None:
            _copy_xattrs(actual_path, tmp_path)
        os.replace(tmp_path, actual_path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


__all__ = [
    "WRITE_OPERATIONS",
    "DEFAULT_FILE_MODE",
    "dedupe_roots",
    "path_under_root",
    "resolve_within_roots",
    "write_text",
]

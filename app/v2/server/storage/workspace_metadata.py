"""Metadata reads for the machine workspace API."""
from contextlib import ExitStack
from pathlib import PurePosixPath
import errno
import hashlib
import os
import stat

from app.v2.server.storage.downloads import SnapshotChangedError, open_entry
from app.v2.server.storage.external_workspaces import workspace_parts
from app.v2.server.storage.paths import identity_segment

MAX_LIST_DEPTH = 12
MAX_LIST_ENTRIES = 2000
MAX_STAT_PATHS = 128
MAX_STAT_BYTES = 1 << 30
_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def directory_parts(path):
    return () if path in {"", "."} else inspect_parts(path)


def inspect_parts(path):
    return workspace_parts(path, max_parts=2048)


def _workspace(tenant_id, agent_id):
    return PurePosixPath(identity_segment(tenant_id), identity_segment(agent_id), "workspace")


def _visible_info(fd, name):
    if name.startswith(".") or "\\" in name:
        return None
    try:
        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if stat.S_ISDIR(info.st_mode) or (stat.S_ISREG(info.st_mode) and info.st_nlink == 1):
        return info
    return None


def _metadata(path, info):
    is_file = stat.S_ISREG(info.st_mode)
    return {"path": path, "type": "file" if is_file else "directory",
            "size": info.st_size if is_file else None}


def list_workspace_files(paths, tenant_id, agent_id, path, depth):
    parts = directory_parts(path)
    rows, truncated, scanned = [], False, 0

    def walk(fd, prefix, remaining):
        nonlocal truncated, scanned
        with os.scandir(fd) as entries:
            for entry in entries:
                scanned += 1
                if scanned > MAX_LIST_ENTRIES:
                    raise OverflowError("workspace listing exceeds entry limit")
                info = _visible_info(fd, entry.name)
                if info is None:
                    continue
                if remaining == 0:
                    truncated = True
                    return
                name = "/".join((*prefix, entry.name))
                rows.append(_metadata(name, info))
                if stat.S_ISDIR(info.st_mode):
                    child = os.open(entry.name, _DIRECTORY, dir_fd=fd)
                    try:
                        walk(child, (*prefix, entry.name), remaining - 1)
                    finally:
                        os.close(child)

    with ExitStack() as stack:
        try:
            fd = stack.enter_context(open_entry(paths.tenants_root,
                _workspace(tenant_id, agent_id).joinpath(*parts), exact_prefix_parts=3,
                directory_only=True))
        except FileNotFoundError:
            if parts:
                raise
            return {"files": [], "truncated_by_depth": False}
        try:
            walk(fd, parts, depth)
        except FileNotFoundError as exc:
            raise SnapshotChangedError("workspace changed during listing") from exc
    return {"files": sorted(rows, key=lambda row: row["path"]), "truncated_by_depth": truncated}


def _signature(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _sha256(parent, name, info):
    changed = "workspace file changed during stat"
    signature = _signature(info)
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(fd, "rb") as stream:
            if _signature(os.fstat(stream.fileno())) != signature:
                raise SnapshotChangedError(changed)
            digest, left = hashlib.sha256(), info.st_size
            while left:
                chunk = stream.read(min(left, 1 << 20))
                if not chunk:
                    raise SnapshotChangedError(changed)
                digest.update(chunk)
                left -= len(chunk)
            if (_signature(os.fstat(stream.fileno())) != signature
                    or _signature(os.stat(name, dir_fd=parent, follow_symlinks=False)) != signature):
                raise SnapshotChangedError(changed)
    except OSError as exc:
        if exc.errno in {errno.ENOENT, errno.ELOOP}:
            raise SnapshotChangedError(changed) from exc
        raise
    return digest.hexdigest()


def stat_workspace_files(paths, tenant_id, agent_id, values):
    root = _workspace(tenant_id, agent_id)
    remaining = MAX_STAT_BYTES
    result = {}
    for path in values:
        if path in result:
            continue
        parts = inspect_parts(path)
        missing = {"path": path, "exists": False, "type": None, "size": None, "sha256": None}
        try:
            with open_entry(paths.tenants_root, root.joinpath(*parts[:-1]),
                            exact_prefix_parts=3, directory_only=True) as parent:
                name = parts[-1]
                info = _visible_info(parent, name)
                if info is None:
                    result[path] = missing
                    continue
                row = {**_metadata(path, info), "exists": True, "sha256": None}
                if row["type"] == "file":
                    remaining -= info.st_size
                    if remaining < 0:
                        raise OverflowError("workspace stat exceeds hash byte limit")
                    row["sha256"] = _sha256(parent, name, info)
                result[path] = row
        except OSError as exc:
            if isinstance(exc, FileNotFoundError) or exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                result[path] = missing
            else:
                raise
    return [result[path] for path in values]

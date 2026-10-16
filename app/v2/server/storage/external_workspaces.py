"""Bounded, symlink-safe file imports for machine-owned Agent workspaces."""

from __future__ import annotations

import base64
import binascii
import os
import shutil
from pathlib import PurePosixPath
import stat

from app.v2.server.storage.paths import ServerPaths, identity_segment

MAX_FILES = 256
MAX_FILE_BYTES = 4 << 20
MAX_TOTAL_BYTES = 16 << 20


def workspace_parts(value: str) -> tuple[str, ...]:
    if not isinstance(value, str) or not value or len(value) > 4096 or "\\" in value or "\0" in value:
        raise ValueError("invalid workspace path")
    path = PurePosixPath(value)
    parts = path.parts
    if path.is_absolute() or not parts or len(parts) > 12 or any(
        part in {"", ".", ".."} or part.startswith(".") for part in parts
    ) or path.as_posix() != value:
        raise ValueError("invalid workspace path")
    return parts


def _directory(fd: int, parts: tuple[str, ...], paths: ServerPaths) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    current = os.dup(fd)
    try:
        for part in parts:
            try:
                os.mkdir(part, mode=0o755, dir_fd=current)
            except FileExistsError:
                pass
            child = os.open(part, flags, dir_fd=current)
            if paths.linux_execution_uid is not None and os.geteuid() == 0:
                os.fchown(child, paths.linux_execution_uid, paths.linux_execution_gid)
            os.close(current)
            current = child
        return current
    except BaseException:
        os.close(current)
        raise


def ensure_workspace_directory(paths: ServerPaths, tenant_id: str, agent_id: str, directory: str) -> None:
    parts = workspace_parts(directory)
    root = paths.workspace_dir(tenant_id, agent_id)
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        child = _directory(fd, parts, paths)
        os.close(child)
    finally:
        os.close(fd)


def import_workspace_files(paths: ServerPaths, tenant_id: str, agent_id: str,
                           directory: str, encoded_files: dict[str, str]) -> int:
    """Create missing files; retries accept identical files and reject conflicting data."""
    root_parts = workspace_parts(directory)
    if len(encoded_files) > MAX_FILES:
        raise ValueError("too many workspace files")
    decoded: dict[tuple[str, ...], bytes] = {}
    total = 0
    for name, encoded in encoded_files.items():
        parts = workspace_parts(name)
        if not isinstance(encoded, str) or len(encoded) > (MAX_FILE_BYTES * 4 // 3 + 8):
            raise ValueError("invalid workspace file")
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("invalid workspace file encoding") from exc
        total += len(data)
        if len(data) > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
            raise ValueError("workspace file quota exceeded")
        decoded[parts] = data
    root = paths.workspace_dir(tenant_id, agent_id)
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for parts, data in decoded.items():
            parent = _directory(fd, root_parts + parts[:-1], paths)
            try:
                name = parts[-1]
                try:
                    file_fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=parent)
                except FileExistsError:
                    existing = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                    try:
                        info = os.fstat(existing)
                        if not stat.S_ISREG(info.st_mode) or info.st_size != len(data):
                            raise FileExistsError("workspace file conflicts with existing data")
                        with os.fdopen(os.dup(existing), "rb") as stream:
                            if stream.read(len(data) + 1) != data:
                                raise FileExistsError("workspace file conflicts with existing data")
                    finally:
                        os.close(existing)
                    continue
                try:
                    if paths.linux_execution_uid is not None and os.geteuid() == 0:
                        os.fchown(file_fd, paths.linux_execution_uid, paths.linux_execution_gid)
                    with os.fdopen(os.dup(file_fd), "wb") as stream:
                        stream.write(data)
                finally:
                    os.close(file_fd)
            finally:
                os.close(parent)
        if not decoded:
            child = _directory(fd, root_parts, paths)
            os.close(child)
    finally:
        os.close(fd)
    return len(decoded)


def delete_workspace_path(paths: ServerPaths, tenant_id: str, agent_id: str,
                          path: str, *, recursive: bool = False) -> bool:
    """Delete relative to pinned directory descriptors; never follow symlinks.

    Missing targets succeed without creating a workspace. Symlink leaves are
    unlinked, including dangling links; symlink ancestors are rejected.
    """
    parts = workspace_parts(path)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(paths.tenants_root, flags)
    try:
        for part in (identity_segment(tenant_id), identity_segment(agent_id),
                     "workspace", *parts[:-1]):
            try:
                child = os.open(part, flags, dir_fd=fd)
            except FileNotFoundError:
                return False
            os.close(fd)
            fd = child
        name = parts[-1]
        try:
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            return False
        if stat.S_ISDIR(info.st_mode):
            if recursive:
                if not shutil.rmtree.avoids_symlink_attacks:
                    raise RuntimeError("symlink-safe directory deletion is unavailable")
                shutil.rmtree(name, dir_fd=fd)
            else:
                os.rmdir(name, dir_fd=fd)
        else:
            os.unlink(name, dir_fd=fd)
        return True
    finally:
        os.close(fd)

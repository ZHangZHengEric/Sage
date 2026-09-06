"""Descriptor-relative local I/O; never follow a mutable workspace symlink."""

import os
import stat
from contextlib import contextmanager


@contextmanager
def parent_fd(root, relative, *, create=False, uid=None, gid=None):
    parts = relative.parts
    if not parts or any(part in {"..", ""} for part in parts):
        raise PermissionError("invalid file path")
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            if create:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=fd)
                    if uid is not None and os.geteuid() == 0:
                        os.chown(part, uid, gid, dir_fd=fd, follow_symlinks=False)
                except FileExistsError:
                    pass
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
            )
            os.close(fd)
            fd = child
        yield fd, parts[-1]
    finally:
        os.close(fd)


def _regular(fd):
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise PermissionError("only regular files without hard links are allowed")
    return info


def read(root, relative, limit):
    with parent_fd(root, relative) as (parent, name):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(fd, "rb") as stream:
            if _regular(stream.fileno()).st_size > limit:
                raise ValueError("file exceeds max_file_bytes")
            data = stream.read(limit + 1)
            if len(data) > limit:
                raise ValueError("file exceeds max_file_bytes")
            return data


def write(root, relative, content, *, create, uid=None, gid=None):
    with parent_fd(root, relative, create=True, uid=uid, gid=gid) as (parent, name):
        flags = os.O_WRONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        if create:
            flags |= os.O_CREAT | os.O_EXCL
        fd = os.open(name, flags, mode=0o600, dir_fd=parent)
        with os.fdopen(fd, "wb") as stream:
            _regular(stream.fileno())
            os.ftruncate(stream.fileno(), 0)
            stream.write(content)
            if uid is not None and os.geteuid() == 0:
                os.fchown(stream.fileno(), uid, gid)


def delete(root, relative):
    with parent_fd(root, relative) as (parent, name):
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise PermissionError(
                "only regular files without hard links can be deleted"
            )
        os.unlink(name, dir_fd=parent)

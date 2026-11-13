"""Read and atomically replace the Claw USER.md for an external workspace."""

from __future__ import annotations

import fcntl
import hashlib
import os
import stat
from uuid import uuid4

from app.v2.server.storage.paths import ServerPaths

USER_PREFERENCES_FILE = "USER.md"
MAX_USER_PREFERENCES_BYTES = 32 << 10


def preferences_document(content: bytes | None) -> dict[str, str | None]:
    if content is None:
        return {"text": None, "revision": "missing"}
    return {"text": content.decode("utf-8"), "revision": hashlib.sha256(content).hexdigest()}


def _read(root: int) -> bytes | None:
    try:
        fd = os.open(USER_PREFERENCES_FILE,
                     os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("USER.md must be a regular workspace file")
        content = stream.read(MAX_USER_PREFERENCES_BYTES + 1)
        if len(content) > MAX_USER_PREFERENCES_BYTES:
            raise ValueError("USER.md exceeds size limit")
        return content


def user_preferences(paths: ServerPaths, tenant: str, agent: str, *,
                     text: str | None = None, revision: str | None = None):
    root = os.open(paths.workspace_dir(tenant, agent),
                   os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        if text is not None:
            fcntl.flock(root, fcntl.LOCK_EX)
        current = _read(root)
        document = preferences_document(current)
        if text is None:
            return document
        content = text.encode("utf-8")
        if len(content) > MAX_USER_PREFERENCES_BYTES:
            raise ValueError("USER.md exceeds size limit")
        if current == content:
            return document
        if revision != document["revision"]:
            raise FileExistsError("USER.md changed")
        temporary = ".user-preferences-" + uuid4().hex
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o644, dir_fd=root)
        try:
            with os.fdopen(fd, "wb") as stream:
                if paths.linux_execution_uid is not None and os.geteuid() == 0:
                    os.fchown(stream.fileno(), paths.linux_execution_uid, paths.linux_execution_gid)
                stream.write(content)
            if current is None:
                os.link(temporary, USER_PREFERENCES_FILE, src_dir_fd=root, dst_dir_fd=root,
                        follow_symlinks=False)
            else:
                os.replace(temporary, USER_PREFERENCES_FILE, src_dir_fd=root, dst_dir_fd=root)
        finally:
            try:
                os.unlink(temporary, dir_fd=root)
            except FileNotFoundError:
                pass
        return preferences_document(content)
    finally:
        os.close(root)

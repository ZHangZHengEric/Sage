from __future__ import annotations

import hashlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ServerPaths:
    data_root: Path
    runtime_root: Path
    sessions_root: Path
    tenants_root: Path
    linux_execution_uid: int | None = None
    linux_execution_gid: int | None = None

    def tenant_dir(self, user_id: str) -> Path:
        path = self.tenants_root / user_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def workspace_dir(self, user_id: str, *, private_run_id: str | None = None) -> Path:
        path = self.tenant_dir(user_id)
        parts = ["workspace"]
        if private_run_id is not None:
            parts.extend((".runs", hashlib.sha256(private_run_id.encode()).hexdigest()))
        if sys.platform != "linux" or self.linux_execution_uid is None:
            path = path.joinpath(*parts)
            path.mkdir(parents=True, exist_ok=True)
            return path

        # Only manage these directories, never recursively chown tenant files.
        # Open each component relative to its parent without following symlinks:
        # an Agent can create entries inside workspace, including .runs.
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        fd = os.open(path, flags)
        try:
            for part in parts:
                try:
                    os.mkdir(part, mode=0o755, dir_fd=fd)
                except FileExistsError:
                    pass
                child = os.open(part, flags, dir_fd=fd)
                os.close(fd)
                fd = child
                stat = os.fstat(fd)
                if (stat.st_uid, stat.st_gid) != (
                    self.linux_execution_uid, self.linux_execution_gid
                ):
                    if os.geteuid() != 0:
                        raise PermissionError(
                            "sandbox workspace ownership requires a root server or matching UID/GID"
                        )
                    os.fchown(fd, self.linux_execution_uid, self.linux_execution_gid)
                path = path / part
        finally:
            os.close(fd)
        return path


def prepare_server_v2_storage(
    data_root: Path,
    *,
    linux_execution_uid: int | None = None,
    linux_execution_gid: int | None = None,
) -> ServerPaths:
    root = data_root.expanduser().resolve()
    runtime = root / "runtime"
    sessions = runtime / "sessions"
    tenants = root / "tenants"
    skills = root / "skills"
    for path in (root, runtime, sessions, tenants, skills):
        path.mkdir(parents=True, exist_ok=True)
    return ServerPaths(
        data_root=root,
        runtime_root=runtime,
        sessions_root=sessions,
        tenants_root=tenants,
        linux_execution_uid=linux_execution_uid,
        linux_execution_gid=linux_execution_gid,
    )

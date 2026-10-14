from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote


def identity_segment(value: str) -> str:
    """Keep IDs readable; escape separators reversibly, never hash identities."""
    if not isinstance(value, str) or not value or "\0" in value:
        raise ValueError("invalid workspace identity")
    return "%2E" * len(value) if value in {".", ".."} else quote(value, safe="")


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

    def workspace_path(self, user_id: str, agent_id: str) -> Path:
        return self.tenants_root / identity_segment(user_id) / identity_segment(agent_id) / "workspace"

    def workspace_dir(self, user_id: str, agent_id: str, *, private_run_id: str | None = None) -> Path:
        path = self.tenants_root
        path.mkdir(parents=True, exist_ok=True)
        parts = [identity_segment(user_id), identity_segment(agent_id), "workspace"]
        if private_run_id is not None:
            parts.extend((".runs", identity_segment(private_run_id)))
        # Only manage these directories, never recursively chown tenant files.
        # Open each component relative to its parent without following symlinks:
        # an Agent can create entries inside workspace, including .runs.
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        fd = os.open(path, flags)
        try:
            for index, part in enumerate(parts):
                try:
                    os.mkdir(part, mode=0o755, dir_fd=fd)
                except FileExistsError:
                    pass
                child = os.open(part, flags, dir_fd=fd)
                os.close(fd)
                fd = child
                stat = os.fstat(fd)
                if index >= 2 and sys.platform == "linux" and self.linux_execution_uid is not None and (stat.st_uid, stat.st_gid) != (
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

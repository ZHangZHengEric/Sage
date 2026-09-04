from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ServerV2Paths:
    data_root: Path
    runtime_root: Path
    sessions_root: Path
    tenants_root: Path

    def tenant_dir(self, user_id: str) -> Path:
        path = self.tenants_root / user_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def workspace_dir(self, user_id: str) -> Path:
        path = self.tenant_dir(user_id) / "workspace"
        path.mkdir(parents=True, exist_ok=True)
        return path


def prepare_server_v2_storage(data_root: Path) -> ServerV2Paths:
    root = data_root.expanduser().resolve()
    runtime = root / "runtime"
    sessions = runtime / "sessions"
    tenants = root / "tenants"
    skills = root / "skills"
    for path in (root, runtime, sessions, tenants, skills):
        path.mkdir(parents=True, exist_ok=True)
    return ServerV2Paths(
        data_root=root,
        runtime_root=runtime,
        sessions_root=sessions,
        tenants_root=tenants,
    )

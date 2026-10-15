"""Replace complete Skill packages in existing workspaces of one Agent.

Catalog versions remain immutable. Old workspace packages are retained under
runtime/agent-skill-sync-* so a failed update can be recovered.
"""

from datetime import datetime, timezone
import os
from pathlib import Path
import stat
import uuid

from app.v2.server.skills.records import normalize_skill_name
from app.v2.server.storage.paths import identity_segment

_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def _child(parent: int, name: str, *, create: bool = False, owner: tuple[int, int] | None = None) -> int:
    if create:
        try:
            os.mkdir(name, mode=0o755, dir_fd=parent)
        except FileExistsError:
            pass
    fd = os.open(name, _FLAGS, dir_fd=parent)
    if owner is not None and os.geteuid() == 0:
        os.fchown(fd, *owner)
    return fd


def _read_tree(directory: int, prefix: str = "", budget: list[int] | None = None) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    if budget is None:
        budget = [0, 0]
    for name in sorted(os.listdir(directory)):
        info = os.stat(name, dir_fd=directory, follow_symlinks=False)
        relative = prefix + name
        if stat.S_ISDIR(info.st_mode):
            child = _child(directory, name)
            try:
                files.update(_read_tree(child, relative + "/", budget))
            finally:
                os.close(child)
        elif stat.S_ISREG(info.st_mode):
            budget[0] += 1
            budget[1] += info.st_size
            if budget[0] > 2_000 or budget[1] > 64 * 1024 * 1024:
                raise ValueError("workspace Skill exceeds package limits")
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            with os.fdopen(fd, "rb") as stream:
                content = stream.read(info.st_size + 1)
            if len(content) != info.st_size:
                raise ValueError("workspace Skill changed during synchronization")
            files[relative] = content
        else:
            raise ValueError("workspace Skill contains an unsafe file")
    return files


def _write_package(directory: int, files: dict[str, bytes], owner: tuple[int, int]) -> None:
    for relative, content in sorted(files.items()):
        parts = relative.split("/")
        if not parts or any(part in {"", ".", ".."} for part in parts):
            raise ValueError("invalid Skill package path")
        parent = os.dup(directory)
        try:
            for part in parts[:-1]:
                child = _child(parent, part, create=True, owner=owner)
                os.close(parent)
                parent = child
            fd = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o644, dir_fd=parent)
            with os.fdopen(fd, "wb") as stream:
                if os.geteuid() == 0:
                    os.fchown(stream.fileno(), *owner)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            os.close(parent)


def _remove_tree(parent: int, name: str) -> None:
    try:
        directory = _child(parent, name)
    except FileNotFoundError:
        return
    try:
        for item in os.listdir(directory):
            info = os.stat(item, dir_fd=directory, follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                _remove_tree(directory, item)
            else:
                os.unlink(item, dir_fd=directory)
    finally:
        os.close(directory)
    os.rmdir(name, dir_fd=parent)


def sync_workspaces(data_root: Path, agent_id: str,
                    packages: dict[str, dict[str, bytes]]) -> dict:
    """Sync complete packages; keep other Skills and immutable .catalog caches."""
    segment = identity_segment(agent_id)
    if not packages or len(packages) > 32:
        raise ValueError("Skill packages are required")
    for name, files in packages.items():
        normalize_skill_name(name)
        if "SKILL.md" not in files:
            raise ValueError("Skill package must contain SKILL.md")
    root = Path(data_root)
    backup = root / "runtime" / ("agent-skill-sync-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    workspaces = 0
    changed = 0
    rootfd = os.open(root, _FLAGS)
    try:
        try:
            tenants = _child(rootfd, "tenants")
        except FileNotFoundError:
            return {"workspaces": 0, "changed_workspaces": 0, "backup": None}
        try:
            for tenant in sorted(os.listdir(tenants)):
                tenantfd = _child(tenants, tenant)
                try:
                    try:
                        agentfd = _child(tenantfd, segment)
                    except FileNotFoundError:
                        continue
                    try:
                        try:
                            workspace = _child(agentfd, "workspace")
                        except FileNotFoundError:
                            continue
                        try:
                            info = os.fstat(workspace)
                            owner = (info.st_uid, info.st_gid)
                            skills = _child(workspace, "skills", create=True, owner=owner)
                            try:
                                workspaces += 1
                                for name, files in sorted(packages.items()):
                                    try:
                                        existing = _child(skills, name)
                                    except FileNotFoundError:
                                        old_files = None
                                    else:
                                        try:
                                            old_files = _read_tree(existing)
                                        finally:
                                            os.close(existing)
                                    if old_files == files:
                                        continue
                                    temporary = ".skill-sync-" + uuid.uuid4().hex
                                    staging = _child(skills, temporary, create=True, owner=owner)
                                    try:
                                        try:
                                            _write_package(staging, files, owner)
                                        finally:
                                            os.close(staging)
                                        saved = None
                                        if old_files is not None:
                                            saved = backup / tenant / name
                                            saved.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                                            os.rename(name, saved, src_dir_fd=skills)
                                        try:
                                            os.rename(temporary, name, src_dir_fd=skills, dst_dir_fd=skills)
                                        except Exception:
                                            if saved is not None:
                                                os.rename(saved, name, dst_dir_fd=skills)
                                            raise
                                        os.fsync(skills)
                                        changed += 1
                                    finally:
                                        _remove_tree(skills, temporary)
                            finally:
                                os.close(skills)
                        finally:
                            os.close(workspace)
                    finally:
                        os.close(agentfd)
                finally:
                    os.close(tenantfd)
        finally:
            os.close(tenants)
    finally:
        os.close(rootfd)
    return {"workspaces": workspaces, "changed_workspaces": changed,
            "backup": str(backup) if backup.exists() else None}

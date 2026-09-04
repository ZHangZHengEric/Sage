"""Skill catalog records, relative artifact paths, and bind/resolve rules.

MySQL stores only deployment-relative paths. Absolute paths are joined from
the Server data root at the edge (repository / runtime), never persisted.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sagents.v2.contracts.common import new_id

from app.server_v2.core.errors import ServerV2Error

SkillDimension = Literal["system", "user"]

SKILL_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,191}$")
_UNSAFE_RELATIVE = re.compile(r"(^|/)\.\.(/|$)")


def normalize_skill_name(name: str) -> str:
    value = str(name or "").strip()
    if not SKILL_NAME.fullmatch(value):
        raise ServerV2Error("validation", f"invalid skill name: {name!r}")
    return value


def normalize_skill_names(names: list[str] | tuple[str, ...] | None) -> list[str]:
    return list(dict.fromkeys(normalize_skill_name(name) for name in names or [] if str(name).strip()))


def artifact_relative_path(
    *,
    dimension: SkillDimension,
    owner_user_id: str,
    name: str,
    version_id: str,
) -> str:
    """Path stored in MySQL. Always relative to ``{data_root}/skills``."""

    skill_name = normalize_skill_name(name)
    version = str(version_id or "").strip()
    if not version or "/" in version or "\\" in version or version in {".", ".."}:
        raise ServerV2Error("validation", "invalid skill version id")
    if dimension == "system":
        return f"system/{skill_name}/{version}"
    owner = str(owner_user_id or "").strip()
    if not owner or "/" in owner or "\\" in owner:
        raise ServerV2Error("validation", "user skills require owner_user_id")
    return f"users/{owner}/{skill_name}/{version}"


def reject_absolute_artifact_path(relative: str) -> str:
    value = str(relative or "").strip().replace("\\", "/")
    if not value:
        raise ServerV2Error("validation", "artifact path is required")
    if value.startswith("/") or (len(value) > 1 and value[1] == ":"):
        raise ServerV2Error("validation", "artifact path must be relative")
    if _UNSAFE_RELATIVE.search(value) or value.startswith("../"):
        raise ServerV2Error("validation", "artifact path escapes the skill root")
    return value


def resolve_artifact_path(data_root: Path, relative: str) -> Path:
    """Join a stored relative path onto the deployment skill root."""

    safe = reject_absolute_artifact_path(relative)
    root = (Path(data_root) / "skills").resolve()
    target = (root / safe).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ServerV2Error("validation", "artifact path escapes the skill root") from exc
    return target


def workspace_skill_path(data_root: Path, user_id: str, name: str) -> Path:
    skill_name = normalize_skill_name(name)
    root = (Path(data_root) / "tenants" / user_id / "workspace").resolve()
    target = (root / "skills" / skill_name).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ServerV2Error("validation", "workspace skill path is invalid") from exc
    return target


@dataclass(frozen=True, slots=True)
class SkillRecord:
    skill_id: str
    version_id: str
    revision: int
    dimension: SkillDimension
    owner_user_id: str
    name: str
    description: str
    artifact_path: str
    skill_md_sha256: str
    package_sha256: str
    file_count: int
    total_bytes: int
    status: str = "active"

    def public_dict(self) -> dict[str, object]:
        return {
            "skill_id": self.skill_id,
            "version_id": self.version_id,
            "revision": self.revision,
            "dimension": self.dimension,
            "owner_user_id": self.owner_user_id or None,
            "name": self.name,
            "description": self.description,
            "artifact_path": self.artifact_path,
            "package_sha256": self.package_sha256,
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
            "status": self.status,
        }

    def absolute_path(self, data_root: Path) -> Path:
        return resolve_artifact_path(data_root, self.artifact_path)


@dataclass(frozen=True, slots=True)
class SkillPackage:
    name: str
    description: str
    files: dict[str, bytes]
    skill_md_sha256: str
    package_sha256: str
    file_count: int
    total_bytes: int


@dataclass(frozen=True, slots=True)
class AgentSkillBinding:
    owner_user_id: str
    agent_id: str
    skill_name: str
    source_skill_id: str | None
    position: int


def new_skill_id() -> str:
    return new_id("skill")


def new_version_id() -> str:
    return new_id("sver")


def inspect_skill_directory(source: Path) -> SkillPackage:
    root = Path(source)
    if not root.is_dir():
        raise ServerV2Error("validation", "skill package directory does not exist")
    skill_md = root / "SKILL.md"
    if not skill_md.is_file() or skill_md.is_symlink():
        raise ServerV2Error("validation", "skill package must contain SKILL.md")
    files: dict[str, bytes] = {}
    total = 0
    for candidate in sorted(root.rglob("*")):
        if any(part in {"__pycache__", "node_modules"} for part in candidate.parts):
            continue
        if candidate.is_symlink():
            raise ServerV2Error("validation", "skill package cannot contain symbolic links")
        if not candidate.is_file():
            continue
        relative = candidate.relative_to(root).as_posix()
        if relative in {".skill-manifest.json", ".materialized-skill.json"}:
            continue
        content = candidate.read_bytes()
        if len(files) >= 2_000 or total + len(content) > 64 * 1024 * 1024:
            raise ServerV2Error("validation", "skill package exceeds size limits")
        files[relative] = content
        total += len(content)
    return _package_from_files(files, fallback_name=root.name)


def inspect_skill_zip(payload: bytes, *, filename: str = "") -> SkillPackage:
    """Read one skill ZIP in memory. A wrapper folder around SKILL.md is allowed."""

    if not payload:
        raise ServerV2Error("validation", "zip is empty")
    if len(payload) > 32 * 1024 * 1024:
        raise ServerV2Error("validation", "zip exceeds size limits")
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise ServerV2Error("validation", "invalid zip file") from exc
    files: dict[str, bytes] = {}
    total = 0
    with archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            relative = _safe_zip_path(info.filename)
            if relative is None:
                continue
            if info.file_size > 64 * 1024 * 1024:
                raise ServerV2Error("validation", "skill package exceeds size limits")
            content = archive.read(info)
            if len(files) >= 2_000 or total + len(content) > 64 * 1024 * 1024:
                raise ServerV2Error("validation", "skill package exceeds size limits")
            files[relative] = content
            total += len(content)
    files = _unwrap_zip_root(files)
    fallback = Path(filename or "skill").stem
    return _package_from_files(files, fallback_name=fallback)


def _safe_zip_path(filename: str) -> str | None:
    relative = str(filename or "").replace("\\", "/").lstrip("./")
    if not relative or relative.endswith("/"):
        return None
    parts = [part for part in relative.split("/") if part not in {"", "."}]
    if not parts:
        return None
    if parts[0] == "__MACOSX" or parts[-1] in {".DS_Store"}:
        return None
    if any(part in {"__pycache__", "node_modules", ".."} for part in parts):
        if ".." in parts:
            raise ServerV2Error("validation", f"unsafe path in zip: {filename!r}")
        return None
    if relative.startswith("/") or (len(relative) > 1 and relative[1] == ":"):
        raise ServerV2Error("validation", f"unsafe path in zip: {filename!r}")
    if relative in {".skill-manifest.json", ".materialized-skill.json"}:
        return None
    return "/".join(parts)


def _unwrap_zip_root(files: dict[str, bytes]) -> dict[str, bytes]:
    if "SKILL.md" in files:
        return files
    prefixes = {
        path[: -len("SKILL.md")]
        for path in files
        if path.endswith("/SKILL.md")
    }
    if len(prefixes) != 1:
        return files
    prefix = next(iter(prefixes))
    if not prefix or not all(path.startswith(prefix) for path in files):
        return files
    return {path[len(prefix) :]: body for path, body in files.items() if path[len(prefix) :]}


def _package_from_files(files: dict[str, bytes], *, fallback_name: str) -> SkillPackage:
    if "SKILL.md" not in files:
        raise ServerV2Error("validation", "skill package must contain SKILL.md")
    digest = hashlib.sha256()
    total = 0
    for relative, content in sorted(files.items()):
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
        total += len(content)
    description = _description(files["SKILL.md"])
    name = _front_matter_name(files["SKILL.md"]) or fallback_name
    return SkillPackage(
        name=normalize_skill_name(name),
        description=description,
        files=files,
        skill_md_sha256=hashlib.sha256(files["SKILL.md"]).hexdigest(),
        package_sha256=f"sha256:{digest.hexdigest()}",
        file_count=len(files),
        total_bytes=total,
    )


def inspect_skill_markdown(*, name: str, content: str) -> SkillPackage:
    body = content if content.endswith("\n") else f"{content}\n"
    encoded = body.encode("utf-8")
    package = SkillPackage(
        name=normalize_skill_name(name),
        description=_description(encoded),
        files={"SKILL.md": encoded},
        skill_md_sha256=hashlib.sha256(encoded).hexdigest(),
        package_sha256="",
        file_count=1,
        total_bytes=len(encoded),
    )
    digest = hashlib.sha256()
    digest.update(b"SKILL.md\0")
    digest.update(encoded)
    digest.update(b"\0")
    return SkillPackage(
        name=package.name,
        description=package.description,
        files=package.files,
        skill_md_sha256=package.skill_md_sha256,
        package_sha256=f"sha256:{digest.hexdigest()}",
        file_count=1,
        total_bytes=len(encoded),
    )


def write_skill_package(destination: Path, package: SkillPackage) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ServerV2Error("conflict", "skill artifact already exists")
    staging = destination.parent / f".{destination.name}.staging"
    if staging.exists():
        _rmtree(staging)
    staging.mkdir(parents=True)
    try:
        for relative, content in package.files.items():
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        staging.replace(destination)
    except Exception:
        _rmtree(staging)
        raise


def copy_skill_tree(source: Path, destination: Path) -> None:
    if destination.exists():
        raise ServerV2Error("conflict", "workspace skill already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.parent / f".{destination.name}.staging"
    if staging.exists():
        _rmtree(staging)
    _copytree(source, staging)
    staging.replace(destination)


def package_sha256_of(path: Path) -> str:
    return inspect_skill_directory(path).package_sha256


def pick_visible_skill(
    candidates: list[SkillRecord],
    *,
    name: str,
    user_id: str,
) -> SkillRecord | None:
    """User-owned skill wins over the system skill of the same name."""

    user_hit = next(
        (
            item
            for item in candidates
            if item.name == name
            and item.dimension == "user"
            and item.owner_user_id == user_id
            and item.status == "active"
        ),
        None,
    )
    if user_hit is not None:
        return user_hit
    return next(
        (
            item
            for item in candidates
            if item.name == name and item.dimension == "system" and item.status == "active"
        ),
        None,
    )


def resolve_bound_skills(
    visible: list[SkillRecord],
    bindings: list[AgentSkillBinding],
) -> list[SkillRecord]:
    """Honor stored source_skill_id. A disabled bound source does not fall back."""

    by_id = {item.skill_id: item for item in visible if item.status == "active"}
    by_name = {item.name: item for item in visible if item.status == "active"}
    resolved: list[SkillRecord] = []
    for binding in sorted(bindings, key=lambda item: item.position):
        if binding.source_skill_id:
            match = by_id.get(binding.source_skill_id)
            if match is None or match.name != binding.skill_name:
                continue
            resolved.append(match)
            continue
        match = by_name.get(binding.skill_name)
        if match is not None:
            resolved.append(match)
    return resolved


def _description(skill_md: bytes) -> str:
    try:
        text = skill_md.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ServerV2Error("validation", "SKILL.md must be UTF-8") from exc
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for line in lines[1:]:
            stripped = line.strip()
            if stripped == "---":
                break
            key, separator, value = stripped.partition(":")
            if separator and key.strip() == "description":
                return value.strip().strip("'\"")[:500]
    body = lines
    if lines and lines[0].strip() == "---":
        closing = next(
            (
                index
                for index, line in enumerate(lines[1:], start=1)
                if line.strip() == "---"
            ),
            len(lines) - 1,
        )
        body = lines[closing + 1 :]
    for line in body:
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped[:500]
    return ""


def _front_matter_name(skill_md: bytes) -> str:
    try:
        text = skill_md.decode("utf-8")
    except UnicodeDecodeError:
        return ""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            break
        key, separator, value = stripped.partition(":")
        if separator and key.strip() == "name":
            return value.strip().strip("'\"")
    return ""


def _copytree(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True)
    for candidate in sorted(source.rglob("*")):
        if candidate.is_symlink():
            raise ServerV2Error("validation", "skill package cannot contain symbolic links")
        relative = candidate.relative_to(source)
        target = destination / relative
        if candidate.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if candidate.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(candidate.read_bytes())
            os.chmod(target, stat.S_IMODE(candidate.stat().st_mode))


def _rmtree(path: Path) -> None:
    if not path.exists():
        return
    for candidate in sorted(path.rglob("*"), reverse=True):
        if candidate.is_dir() and not candidate.is_symlink():
            candidate.rmdir()
        else:
            candidate.unlink(missing_ok=True)
    if path.exists():
        path.rmdir()

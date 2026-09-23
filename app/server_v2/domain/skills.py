"""Skill catalog records, relative artifact paths, and bind/resolve rules.

MySQL stores only deployment-relative paths. Absolute paths are joined from
the Server data root at the edge (repository / runtime), never persisted.
"""

from __future__ import annotations

import re
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


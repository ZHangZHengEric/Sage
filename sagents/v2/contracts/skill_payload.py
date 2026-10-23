"""Dependency-free Skill payload identities used by durable Run commands."""
from __future__ import annotations

import hashlib

from pydantic import Field, field_validator

from sagents.v2.contracts.common import Identifier, SkillName, StrictModel


class SkillDescriptor(StrictModel):
    """Level-1 metadata; discovering this object must never copy skill files."""

    name: SkillName
    description: str
    source_id: Identifier
    version: str | None = None
    metadata: dict = Field(default_factory=dict)


class SkillBundle(StrictModel):
    """Immutable Level-2 payload fetched only by an explicit load operation."""

    descriptor: SkillDescriptor
    files: dict[str, bytes]
    content_hash: str

    @field_validator("files")
    @classmethod
    def validate_paths(cls, files: dict[str, bytes]) -> dict[str, bytes]:
        if "SKILL.md" not in files:
            raise ValueError("skill bundle requires SKILL.md")
        for path in files:
            normalized = path.replace("\\", "/")
            if (
                not normalized
                or normalized.startswith("/")
                or normalized != path
                or any(part in {"", ".", ".."} for part in normalized.split("/"))
            ):
                raise ValueError(f"unsafe skill bundle path: {path!r}")
        return files


def files_digest(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for path, content in sorted(files.items()):
        digest.update(path.encode())
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"



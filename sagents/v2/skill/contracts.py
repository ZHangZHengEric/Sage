"""SAgents V2 module for skill/contracts.py."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

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


class LoadedSkill(StrictModel):
    run_id: Identifier
    descriptor: SkillDescriptor
    workspace_path: str
    content_hash: str
    instructions: str
    file_list: tuple[str, ...]
    loaded_at: datetime


class SkillCatalog(Protocol):
    async def list_skills(self, *, run_id: str) -> tuple[SkillDescriptor, ...]: ...
    async def get_skill(self, name: str, *, run_id: str) -> SkillDescriptor: ...


class SkillSource(Protocol):
    async def fetch(self, name: str, *, run_id: str) -> SkillBundle: ...


class SkillWorkspace(Protocol):
    async def materialize(
        self, bundle: SkillBundle, *, run_id: str, destination: str
    ) -> str: ...


class SkillActivationRepository(Protocol):
    async def list_loaded(self, *, run_id: str) -> tuple[LoadedSkill, ...]: ...
    async def put_loaded(self, value: LoadedSkill) -> None: ...
    async def replace_loaded(
        self, *, run_id: str, values: tuple[LoadedSkill, ...]
    ) -> None: ...

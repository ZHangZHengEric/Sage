from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class SkillPublishBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    content: str


class SkillUpdateBody(BaseModel):
    content: str


class SkillBindBody(BaseModel):
    names: list[str] = Field(default_factory=list)


class WorkspaceSkillBody(BaseModel):
    content: str


class SkillPublic(BaseModel):
    skill_id: str
    version_id: str
    revision: int
    owner_user_id: str
    name: str
    description: str
    artifact_path: str
    package_sha256: str
    file_count: int
    total_bytes: int
    status: str
    content: str | None = None
    workspace_status: str | None = None


class SkillFilePublic(BaseModel):
    path: str
    size: int


class SkillUploadItem(BaseModel):
    filename: str
    success: bool
    message: str
    skill: SkillPublic | None = None


class SkillUploadResult(BaseModel):
    results: list[SkillUploadItem] = Field(default_factory=list)
    success_count: int = 0
    failed_count: int = 0
    skills: list[SkillPublic] = Field(default_factory=list)


class SkillImportSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["zip_url", "skills_cli"]
    value: str = Field(min_length=1, max_length=4096)


class SkillImportSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=1024)
    package_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    expected_version_id: str = Field(default="", max_length=64)
    overwrite: bool = False


class SkillImportBody(SkillImportSource):
    revision: str = Field(pattern=r"^[0-9a-f]{40}([0-9a-f]{24})?$")
    items: list[SkillImportSelection] = Field(min_length=1, max_length=32)


class SkillImportCandidate(BaseModel):
    path: str
    name: str
    description: str
    file_count: int
    total_bytes: int
    package_sha256: str
    expected_version_id: str
    status: Literal["new", "unchanged", "conflict"]


class SkillImportPreview(BaseModel):
    revision: str
    candidates: list[SkillImportCandidate]

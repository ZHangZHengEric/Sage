from __future__ import annotations

from pydantic import BaseModel, Field

class SkillPublishBody(BaseModel):
    name: str
    content: str
    dimension: str = "user"

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
    dimension: str
    owner_user_id: str | None = None
    name: str
    description: str
    artifact_path: str
    package_sha256: str
    file_count: int
    total_bytes: int
    status: str
    content: str | None = None
    workspace_status: str | None = None

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


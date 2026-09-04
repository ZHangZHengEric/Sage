from __future__ import annotations

from typing import Generic, TypeVar

from ag_ui.core import RunAgentInput
from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    code: int = 0
    message: str = "success"
    data: T | None = None
    request_id: str = ""


class ErrorBody(BaseModel):
    code: int
    message: str
    data: None = None
    error_detail: str = ""
    request_id: str = ""


class LoginBody(BaseModel):
    username: str
    password: str


class RegisterBody(BaseModel):
    username: str
    password: str


class ModelBody(BaseModel):
    id: str | None = None
    protocol: str = "openai-chat-completions"
    base_url: str = "https://api.openai.com/v1"
    model: str
    api_key: str = ""
    is_default: bool = True


class AgentBody(BaseModel):
    id: str | None = None
    name: str
    description: str = ""
    instructions: str = ""
    model_id: str = ""
    tools: list[str] = Field(default_factory=list)


class AgentPublic(BaseModel):
    id: str
    name: str
    description: str = ""
    instructions: str = ""
    model_id: str | None = None
    tools: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)


class McpBody(BaseModel):
    name: str
    protocol: str = "stdio"
    url: str | None = None
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    api_key: str = ""
    disabled: bool = False
    description: str = ""


class McpPublic(BaseModel):
    name: str
    protocol: str
    url: str | None = None
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    disabled: bool = False
    description: str = ""
    tools: list[str] = Field(default_factory=list)
    has_api_key: bool = False


class AgentRunBody(BaseModel):
    threadId: str
    runId: str
    messages: list
    state: dict = Field(default_factory=dict)
    tools: list = Field(default_factory=list)
    context: list = Field(default_factory=list)
    forwardedProps: dict = Field(default_factory=dict)

    def to_agui(self) -> RunAgentInput:
        return RunAgentInput.model_validate(self.model_dump())


class HealthPayload(BaseModel):
    status: str
    protocol: str
    protocol_version: str
    runtime: str
    backends: dict[str, str] = Field(default_factory=dict)


class UserPublic(BaseModel):
    user_id: str
    username: str
    role: str


class TokenPayload(BaseModel):
    access_token: str
    expires_in: int
    user: UserPublic


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


class ModelPublic(BaseModel):
    id: str
    protocol: str
    base_url: str
    model: str
    is_default: bool


class ThreadPublic(BaseModel):
    thread_id: str
    user_id: str
    title: str
    updated_at: str


class AdminThreadPublic(ThreadPublic):
    username: str


class AdminModelPublic(ModelPublic):
    user_id: str
    username: str


AUTH_ERRORS = {
    401: {"model": ErrorBody, "description": "authentication required"},
}
ADMIN_ERRORS = {
    **AUTH_ERRORS,
    403: {"model": ErrorBody, "description": "admin required"},
}
VALIDATION_ERRORS = {
    422: {"model": ErrorBody, "description": "request validation failed"},
}

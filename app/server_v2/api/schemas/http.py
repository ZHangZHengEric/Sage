from __future__ import annotations

from typing import Any, Generic, Literal, TypeVar

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


class ToolPublic(BaseModel):
    name: str
    category: str = ""
    source: str = "official"
    default: bool = False


class McpBody(BaseModel):
    name: str
    protocol: Literal["sse", "streamable_http"] = "streamable_http"
    url: str | None = None
    api_key: str = ""
    disabled: bool = False
    description: str = ""


class McpPublic(BaseModel):
    name: str
    protocol: str
    url: str | None = None
    disabled: bool = False
    description: str = ""
    tools: list[str] = Field(default_factory=list)
    has_api_key: bool = False


class A2AAgentBody(BaseModel):
    """A remote A2A agent this tenant's Agents may delegate to.

    ``url`` is the peer's base URL. Its Agent Card, fetched from the well-known
    path under that base, is what names the skills and the RPC endpoint — so
    there is nothing else to configure and nothing here to keep in sync when
    the peer changes.
    """

    name: str
    url: str | None = None
    api_key: str = ""
    disabled: bool = False
    description: str = ""


class A2AAgentPublic(BaseModel):
    name: str
    url: str | None = None
    disabled: bool = False
    description: str = ""
    skills: list[str] = Field(default_factory=list)
    has_api_key: bool = False


class ApiKeyBody(BaseModel):
    agent_id: str = ""
    name: str = ""
    scopes: list[str] | None = None


class ApiKeyPublic(BaseModel):
    key_id: str
    agent_id: str = ""
    name: str = ""
    scopes: list[str] = Field(default_factory=list)
    created_at: str
    revoked_at: str | None = None


class ApiKeyCreated(ApiKeyPublic):
    """The only response that carries the token; it is not stored anywhere."""

    api_key: str


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


class ThreadResumeBody(BaseModel):
    """One answer to the question a thread is waiting on.

    There is no ``threadId``/``runId`` pair identifying the *suspended* Run: the
    thread already knows which of its Runs is waiting, and letting a client name
    it would let a stale tab answer a question that has since been resolved.
    ``runId`` names the AG-UI run identity of the stream this starts, which is
    the client's to choose exactly as it is when starting a Run.
    """

    runId: str
    decision: str
    payload: dict = Field(default_factory=dict)


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
    agent_id: str = ""
    updated_at: str


class ThreadEventPage(BaseModel):
    """One bounded window of AG-UI frames plus the source event count."""

    events: list[dict[str, Any]]
    total: int
    offset: int
    limit: int


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

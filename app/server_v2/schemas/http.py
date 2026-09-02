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

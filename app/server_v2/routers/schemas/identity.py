from __future__ import annotations

from pydantic import BaseModel, Field

class LoginBody(BaseModel):
    username: str
    password: str

class RegisterBody(BaseModel):
    username: str
    password: str

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

class UserPublic(BaseModel):
    user_id: str
    username: str
    role: str

class TokenPayload(BaseModel):
    access_token: str
    expires_in: int
    user: UserPublic


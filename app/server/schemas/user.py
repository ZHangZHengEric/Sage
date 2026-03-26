from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class RegisterPayload(BaseModel):
    username: str
    password: str
    email: Optional[str] = None
    phonenum: Optional[str] = None


class RegisterRequest(RegisterPayload):
    verification_code: str

class RegisterResponse(BaseModel):
    user_id: str


class RegisterVerificationCodeRequest(BaseModel):
    email: str


class RegisterVerificationCodeResponse(BaseModel):
    expires_in: int
    retry_after: int

class LoginRequest(BaseModel):
    username_or_email: str
    password: str

class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int

class UserInfoResponse(BaseModel):
    user: Dict[str, Any]
    has_provider: bool = False
    has_agent: bool = False

class UserDTO(BaseModel):
    user_id: str
    username: str
    email: Optional[str] = None
    phonenum: Optional[str] = None
    role: str
    created_at: str

class UserListResponse(BaseModel):
    items: List[UserDTO]
    total: int

class UserAddRequest(RegisterPayload):
    role: Optional[str] = "user"

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str

class UserConfigResponse(BaseModel):
    config: Dict[str, Any]

class UserConfigUpdateRequest(BaseModel):
    config: Dict[str, Any]

class UserDeleteRequest(BaseModel):
    user_id: str

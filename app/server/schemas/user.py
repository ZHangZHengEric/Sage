from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class RegisterRequest(BaseModel):
    username: str
    password: str
    email: Optional[str] = None
    phonenum: Optional[str] = None

class RegisterResponse(BaseModel):
    user_id: str

class LoginRequest(BaseModel):
    username_or_email: str
    password: str

class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int

class UserInfoResponse(BaseModel):
    user: Dict[str, Any]

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

class UserAddRequest(RegisterRequest):
    role: Optional[str] = "user"

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str

class UserDeleteRequest(BaseModel):
    user_id: str
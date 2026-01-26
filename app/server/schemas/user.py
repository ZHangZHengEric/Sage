from typing import Any, Dict, Optional

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

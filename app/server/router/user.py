from typing import Optional

from common.render import Response
from fastapi import APIRouter, Request
from pydantic import BaseModel
from service.user import login_user, register_user


class RegisterRequest(BaseModel):
    username: str
    password: str
    email: Optional[str] = None
    phonenum: Optional[str] = None


class LoginRequest(BaseModel):
    username_or_email: str
    password: str


user_router = APIRouter(prefix="/api/user", tags=["User"])


@user_router.post("/register")
async def register(req: RegisterRequest):
    user_id = await register_user(req.username, req.password, req.email, req.phonenum)
    return await Response.succ(data={"user_id": user_id}, message="注册成功")


@user_router.post("/login")
async def login(req: LoginRequest):
    access_token, refresh_token, expires_in = await login_user(
        req.username_or_email, req.password
    )
    return await Response.succ(
        data={
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": expires_in,
        },
        message="登录成功",
    )


@user_router.get("/check_login")
async def check_login(request: Request):
    claims = getattr(request.state, "user_claims", None)
    if not claims:
        return await Response.error(
            code=401, message="未登录", error_detail="no claims"
        )
    return await Response.succ(data={"user": claims}, message="登录成功")

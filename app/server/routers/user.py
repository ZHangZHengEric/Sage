from typing import Optional

from ..core.render import Response
from fastapi import APIRouter, Request
from ..schemas.base import BaseResponse
from ..schemas.user import (
    RegisterRequest, 
    RegisterResponse, 
    LoginRequest, 
    LoginResponse, 
    UserInfoResponse
)
from ..service.user import login_user, register_user


user_router = APIRouter(prefix="/api/user", tags=["User"])


@user_router.post("/register", response_model=BaseResponse[RegisterResponse])
async def register(req: RegisterRequest):
    user_id = await register_user(req.username, req.password, req.email, req.phonenum)
    return await Response.succ(data=RegisterResponse(user_id=user_id), message="注册成功")


@user_router.post("/login", response_model=BaseResponse[LoginResponse])
async def login(req: LoginRequest):
    access_token, refresh_token, expires_in = await login_user(
        req.username_or_email, req.password
    )
    return await Response.succ(
        data=LoginResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
        ),
        message="登录成功",
    )


@user_router.get("/check_login", response_model=BaseResponse[UserInfoResponse])
async def check_login(request: Request):
    claims = getattr(request.state, "user_claims", None)
    if not claims:
        return await Response.error(
            code=401, message="未登录", error_detail="no claims"
        )
    return await Response.succ(data=UserInfoResponse(user=claims), message="登录成功")

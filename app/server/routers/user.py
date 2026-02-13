from fastapi import APIRouter, Request

from ..core.render import Response
from ..schemas.base import BaseResponse
from ..schemas.user import (
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    RegisterResponse,
    UserInfoResponse,
    UserListResponse,
    UserDTO,
    UserDeleteRequest,
    UserAddRequest, 
    ChangePasswordRequest,
)
from ..services.user import (
    login_user,
    register_user,
    get_user_list,
    delete_user,
    add_user,
    change_password,
    get_user_options,
)

user_router = APIRouter(prefix="/api/user", tags=["User"])


@user_router.get("/options", response_model=BaseResponse[list])
async def user_options(request: Request):
    """
    Get simplified user list for selection dropdowns.
    Authenticated users only.
    """
    claims = getattr(request.state, "user_claims", None)
    if not claims:
        return await Response.error(
            code=401, message="未登录", error_detail="no claims"
        )
    
    options = await get_user_options()
    return await Response.succ(data=options, message="获取用户列表成功")


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


@user_router.post("/change-password", response_model=BaseResponse[dict])
async def update_password(request: Request, req: ChangePasswordRequest):
    claims = getattr(request.state, "user_claims", None)
    if not claims:
        return await Response.error(
            code=401, message="未登录", error_detail="no claims"
        )
    
    user_id = claims.get("userid")
    # For admin/config user, userid is 'admin'
    
    await change_password(user_id, req.old_password, req.new_password)
    return await Response.succ(data={}, message="密码修改成功")


@user_router.get("/list", response_model=BaseResponse[UserListResponse])
async def list_users(request: Request, page: int = 1, page_size: int = 20):
    claims = getattr(request.state, "user_claims", {}) or {}
    role = claims.get("role")
    if role != "admin":
        return await Response.error(code=403, message="权限不足", error_detail="permission denied")
    
    users, total = await get_user_list(page, page_size)
    items = [
        UserDTO(
            user_id=u.user_id,
            username=u.username,
            email=u.email,
            phonenum=u.phonenum,
            role=u.role,
            created_at=u.created_at.isoformat() if u.created_at else ""
        ) for u in users
    ]
    return await Response.succ(data=UserListResponse(items=items, total=total))


@user_router.post("/delete", response_model=BaseResponse[dict])
async def remove_user(request: Request, req: UserDeleteRequest):
    claims = getattr(request.state, "user_claims", {}) or {}
    role = claims.get("role")
    if role != "admin":
        return await Response.error(code=403, message="权限不足", error_detail="permission denied")
    
    await delete_user(req.user_id)
    return await Response.succ(data={}, message="用户删除成功")


@user_router.post("/add", response_model=BaseResponse[RegisterResponse])
async def create_user(request: Request, req: UserAddRequest):
    claims = getattr(request.state, "user_claims", {}) or {}
    role = claims.get("role")
    if role != "admin":
        return await Response.error(code=403, message="权限不足", error_detail="permission denied")
    
    user_id = await add_user(req.username, req.password, req.role, req.email, req.phonenum)
    return await Response.succ(data=RegisterResponse(user_id=user_id), message="用户添加成功")

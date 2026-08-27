from fastapi import APIRouter, Request

from common.core.render import Response
from common.models.agent import AgentConfigDao
from common.models.llm_provider import LLMProviderDao
from common.models.user import UserConfigDao
from common.services.auth import clear_auth_session
from common.schemas.base import (
    BaseResponse,
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    RegisterResponse,
    UserAddRequest,
    UserConfigResponse,
    UserConfigUpdateRequest,
    UserDTO,
    UserDeleteRequest,
    UserInfoResponse,
    UserListResponse,
)
from ..services.user import (
    authenticate_user,
    build_user_claims,
    create_login_tokens,
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
            code=401, message="auth.not_logged_in", error_detail="no claims"
        )

    options = await get_user_options()
    return await Response.succ(data=options, message="user.options_loaded")


@user_router.post("/register", response_model=BaseResponse[RegisterResponse])
async def register(req: RegisterRequest):
    user_id = await register_user(req.username, req.password)
    return await Response.succ(
        data=RegisterResponse(user_id=user_id), message="auth.register_success"
    )


@user_router.post("/login", response_model=BaseResponse[LoginResponse])
async def login(request: Request, req: LoginRequest):
    user = await authenticate_user(req.username, req.password)
    access_token, refresh_token, expires_in = create_login_tokens(user)
    request.session["user_claims"] = build_user_claims(user)
    return await Response.succ(
        data=LoginResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
        ),
        message="auth.login_success",
    )


@user_router.post("/logout", response_model=BaseResponse[dict])
async def logout(request: Request):
    clear_auth_session(request)
    return await Response.succ(data={}, message="auth.logout_success")


@user_router.get("/check_login", response_model=BaseResponse[UserInfoResponse])
async def check_login(request: Request):
    claims = getattr(request.state, "user_claims", None)
    if not claims:
        return await Response.error(
            code=401, message="auth.not_logged_in", error_detail="no claims"
        )

    user_id = claims.get("userid")
    # Check Provider
    provider_dao = LLMProviderDao()
    providers = await provider_dao.get_list(user_id=user_id)
    has_provider = bool(providers)

    # Check Agent
    agent_dao = AgentConfigDao()
    agents = await agent_dao.get_list(user_id=user_id)
    has_agent = bool(agents)

    return await Response.succ(
        data=UserInfoResponse(
            user=claims, has_provider=has_provider, has_agent=has_agent
        ),
        message="auth.login_success",
    )


@user_router.post("/change-password", response_model=BaseResponse[dict])
async def update_password(request: Request, req: ChangePasswordRequest):
    claims = getattr(request.state, "user_claims", None)
    if not claims:
        return await Response.error(
            code=401, message="auth.not_logged_in", error_detail="no claims"
        )

    user_id = claims.get("userid")
    # For admin/config user, userid is 'admin'

    await change_password(user_id, req.old_password, req.new_password)
    return await Response.succ(data={}, message="user.password_changed")


@user_router.get("/list", response_model=BaseResponse[UserListResponse])
async def list_users(request: Request, page: int = 1, page_size: int = 20):
    claims = getattr(request.state, "user_claims", {}) or {}
    role = claims.get("role")
    if role != "admin":
        return await Response.error(
            code=403,
            message="common.permission_denied",
            error_detail="permission denied",
        )

    users, total = await get_user_list(page, page_size)
    items = [
        UserDTO(
            user_id=u.user_id,
            username=u.username,
            email=u.email,
            phonenum=u.phonenum,
            role=u.role,
            created_at=u.created_at.isoformat() if u.created_at else "",
        )
        for u in users
    ]
    return await Response.succ(data=UserListResponse(items=items, total=total))


@user_router.post("/delete", response_model=BaseResponse[dict])
async def remove_user(request: Request, req: UserDeleteRequest):
    claims = getattr(request.state, "user_claims", {}) or {}
    role = claims.get("role")
    if role != "admin":
        return await Response.error(
            code=403,
            message="common.permission_denied",
            error_detail="permission denied",
        )

    await delete_user(req.user_id)
    return await Response.succ(data={}, message="user.deleted")


@user_router.post("/add", response_model=BaseResponse[RegisterResponse])
async def create_user(request: Request, req: UserAddRequest):
    claims = getattr(request.state, "user_claims", {}) or {}
    role = claims.get("role")
    if role != "admin":
        return await Response.error(
            code=403,
            message="common.permission_denied",
            error_detail="permission denied",
        )

    user_id = await add_user(
        req.username,
        req.password,
        req.role,  # pyright: ignore[reportArgumentType]
        req.email,
        req.phonenum,  # pyright: ignore[reportArgumentType]
    )
    return await Response.succ(
        data=RegisterResponse(user_id=user_id), message="user.created"
    )


@user_router.get("/config", response_model=BaseResponse[UserConfigResponse])
async def get_config(request: Request):
    claims = getattr(request.state, "user_claims", {}) or {}
    user_id = claims.get("userid")
    if not user_id:
        return await Response.error(
            code=401, message="auth.not_logged_in", error_detail="no claims"
        )

    dao = UserConfigDao()
    config = await dao.get_config(user_id)
    return await Response.succ(
        data=UserConfigResponse(config=config), message="user.config_loaded"
    )


@user_router.post("/config", response_model=BaseResponse[UserConfigResponse])
async def update_config(request: Request, req: UserConfigUpdateRequest):
    claims = getattr(request.state, "user_claims", {}) or {}
    user_id = claims.get("userid")
    if not user_id:
        return await Response.error(
            code=401, message="auth.not_logged_in", error_detail="no claims"
        )

    dao = UserConfigDao()
    config = await dao.update_config(user_id, req.config)
    return await Response.succ(
        data=UserConfigResponse(config=config), message="user.config_updated"
    )

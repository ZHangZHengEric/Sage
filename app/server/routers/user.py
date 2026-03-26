from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import RedirectResponse

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
    UserConfigResponse,
    UserConfigUpdateRequest,
    UserDeleteRequest,
    UserAddRequest,
    ChangePasswordRequest,
)
from ..models.user import UserConfigDao
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
from ..services.auth.external_oauth import (
    build_oauth_authorize_url,
    clear_auth_session,
    complete_oauth_login,
    get_auth_providers,
    get_default_oidc_provider,
    is_local_auth_enabled,
)
from ..models.llm_provider import LLMProviderDao
from ..models.agent import AgentConfigDao

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
    if not is_local_auth_enabled():
        return await Response.error(
            code=400,
            message="当前服务未启用本地账号注册",
            error_detail="local auth disabled",
        )
    user_id = await register_user(req.username, req.password, req.email, req.phonenum)
    return await Response.succ(data=RegisterResponse(user_id=user_id), message="注册成功")


@user_router.post("/login", response_model=BaseResponse[LoginResponse])
async def login(request: Request, req: LoginRequest):
    if not is_local_auth_enabled():
        return await Response.error(
            code=400,
            message="当前服务未启用本地账号密码登录",
            error_detail="local auth disabled",
        )
    user = await authenticate_user(req.username_or_email, req.password)
    access_token, refresh_token, expires_in = create_login_tokens(user)
    request.session["user_claims"] = build_user_claims(user)
    return await Response.succ(
        data=LoginResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
        ),
        message="登录成功",
    )


@user_router.get("/auth-providers", response_model=BaseResponse[list])
async def auth_providers():
    return await Response.succ(
        data=get_auth_providers(include_internal=False),
        message="获取认证 Providers 成功",
    )


@user_router.get("/oauth/login/{provider_id}")
async def oauth_login(
    request: Request,
    provider_id: str = Path(...),
    next: str = Query(default="/agent/chat"),
    redirect_uri: str | None = Query(default=None),
):
    authorize_url = await build_oauth_authorize_url(
        request=request,
        provider_id=provider_id,
        next_url=next,
        redirect_uri=redirect_uri,
    )
    return RedirectResponse(url=authorize_url, status_code=302)


@user_router.get("/oauth/login")
async def oauth_login_default(
    request: Request,
    next: str = Query(default="/agent/chat"),
    redirect_uri: str | None = Query(default=None),
):
    provider = get_default_oidc_provider()
    if not provider:
        return await Response.error(
            code=404,
            message="未配置可用的 OAuth Provider",
            error_detail="no oauth provider configured",
        )
    authorize_url = await build_oauth_authorize_url(
        request=request,
        provider_id=provider["id"],
        next_url=next,
        redirect_uri=redirect_uri,
    )
    return RedirectResponse(url=authorize_url, status_code=302)


@user_router.get("/oauth/callback/{provider_id}")
async def oauth_callback(
    request: Request,
    provider_id: str = Path(...),
    code: str = Query(...),
    state: str = Query(...),
):
    try:
        _, next_url = await complete_oauth_login(request, provider_id, code, state)
        return RedirectResponse(url=next_url, status_code=302)
    except Exception:
        clear_auth_session(request)
        raise


@user_router.post("/logout", response_model=BaseResponse[dict])
async def logout(request: Request):
    clear_auth_session(request)
    return await Response.succ(data={}, message="退出成功")


@user_router.get("/check_login", response_model=BaseResponse[UserInfoResponse])
async def check_login(request: Request):
    claims = getattr(request.state, "user_claims", None)
    if not claims:
        return await Response.error(
            code=401, message="未登录", error_detail="no claims"
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
            user=claims,
            has_provider=has_provider,
            has_agent=has_agent
        ), 
        message="登录成功"
    )


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

@user_router.get("/config", response_model=BaseResponse[UserConfigResponse])
async def get_config(request: Request):
    claims = getattr(request.state, "user_claims", {}) or {}
    user_id = claims.get("userid")
    if not user_id:
        return await Response.error(code=401, message="未登录", error_detail="no claims")
    
    dao = UserConfigDao()
    config = await dao.get_config(user_id)
    return await Response.succ(data=UserConfigResponse(config=config), message="获取配置成功")

@user_router.post("/config", response_model=BaseResponse[UserConfigResponse])
async def update_config(request: Request, req: UserConfigUpdateRequest):
    claims = getattr(request.state, "user_claims", {}) or {}
    user_id = claims.get("userid")
    if not user_id:
        return await Response.error(code=401, message="未登录", error_detail="no claims")
    
    dao = UserConfigDao()
    config = await dao.update_config(user_id, req.config)
    return await Response.succ(data=UserConfigResponse(config=config), message="更新配置成功")

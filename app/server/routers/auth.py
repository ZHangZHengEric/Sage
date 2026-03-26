from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import RedirectResponse

from ..core.render import Response
from ..models.agent import AgentConfigDao
from ..models.llm_provider import LLMProviderDao
from ..schemas.base import BaseResponse
from ..schemas.user import LoginRequest, LoginResponse, RegisterRequest, RegisterResponse, UserInfoResponse
from ..services.auth.external_oauth import (
    build_oauth_authorize_url,
    clear_auth_session,
    complete_oauth_login,
    get_auth_providers,
    get_default_oidc_provider,
    is_local_auth_enabled,
)
from ..services.user import authenticate_user, build_user_claims, create_login_tokens, register_user

auth_router = APIRouter(prefix="/api/auth", tags=["Auth"])


@auth_router.post("/register", response_model=BaseResponse[RegisterResponse])
async def register(req: RegisterRequest):
    if not is_local_auth_enabled():
        return await Response.error(
            code=400,
            message="当前服务未启用本地账号注册",
            error_detail="local auth disabled",
        )
    user_id = await register_user(req.username, req.password, req.email, req.phonenum)
    return await Response.succ(data=RegisterResponse(user_id=user_id), message="注册成功")


@auth_router.post("/login", response_model=BaseResponse[LoginResponse])
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


@auth_router.get("/providers", response_model=BaseResponse[list])
async def auth_providers():
    return await Response.succ(
        data=get_auth_providers(include_internal=False),
        message="获取认证 Providers 成功",
    )


@auth_router.get("/upstream/login/{provider_id}")
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


@auth_router.get("/upstream/login")
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


@auth_router.get("/upstream/callback/{provider_id}")
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


@auth_router.post("/logout", response_model=BaseResponse[dict])
async def logout(request: Request):
    clear_auth_session(request)
    return await Response.succ(data={}, message="退出成功")


@auth_router.get("/session", response_model=BaseResponse[UserInfoResponse])
async def session_info(request: Request):
    claims = getattr(request.state, "user_claims", None)
    if not claims:
        return await Response.error(
            code=401, message="未登录", error_detail="no claims"
        )

    user_id = claims.get("userid")
    provider_dao = LLMProviderDao()
    providers = await provider_dao.get_list(user_id=user_id)
    has_provider = bool(providers)

    agent_dao = AgentConfigDao()
    agents = await agent_dao.get_list(user_id=user_id)
    has_agent = bool(agents)

    return await Response.succ(
        data=UserInfoResponse(
            user=claims,
            has_provider=has_provider,
            has_agent=has_agent,
        ),
        message="登录成功",
    )

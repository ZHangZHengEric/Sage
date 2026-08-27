from fastapi import APIRouter, Request

from common.models.agent import AgentConfigDao
from common.models.llm_provider import LLMProviderDao
from common.core.render import Response
from common.services.auth import clear_auth_session
from common.schemas.base import (
    BaseResponse,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    RegisterResponse,
    UserInfoResponse,
)
from ..services.user import (
    authenticate_user,
    build_user_claims,
    create_login_tokens,
    register_user,
)

auth_router = APIRouter(prefix="/api/auth", tags=["Auth"])


@auth_router.post("/register", response_model=BaseResponse[RegisterResponse])
async def register(req: RegisterRequest):
    user_id = await register_user(req.username, req.password)
    return await Response.succ(
        data=RegisterResponse(user_id=user_id), message="auth.register_success"
    )


@auth_router.post("/login", response_model=BaseResponse[LoginResponse])
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


@auth_router.post("/logout", response_model=BaseResponse[dict])
async def logout(request: Request):
    clear_auth_session(request)
    return await Response.succ(data={}, message="auth.logout_success")


@auth_router.get("/session", response_model=BaseResponse[UserInfoResponse])
async def session_info(request: Request):
    claims = getattr(request.state, "user_claims", None)
    if not claims:
        return await Response.error(
            code=401, message="auth.not_logged_in", error_detail="no claims"
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
        message="auth.login_success",
    )

from fastapi import APIRouter, Request, Response
from app.v2.server.runtime.policy import ExecutionPolicy

from app.v2.server.routers.deps import ReadUser, CurrentUser, HostDep, IdentityDep
from app.v2.server.identity.http import CSRF_COOKIE, SESSION_COOKIE, validate_auth_origin
from app.v2.server.routers.schemas.common import AUTH_ERRORS, VALIDATION_ERRORS, ApiResponse, ErrorBody
from app.v2.server.routers.schemas.identity import LoginBody, RegisterBody, TokenPayload, UserPublic
from app.v2.server.routers.render import success

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=ApiResponse[UserPublic],
    responses={
        409: {"model": ErrorBody, "description": "username already exists"},
        **VALIDATION_ERRORS,
    },
)
async def register(body: RegisterBody, service: IdentityDep, request: Request, host: HostDep):
    validate_auth_origin(request, host.settings.public_base_url)
    user = await service.register(body.username, body.password)
    return success(user.public_dict())


@router.post(
    "/login",
    response_model=ApiResponse[TokenPayload],
    responses={
        401: {"model": ErrorBody, "description": "invalid username or password"},
        **VALIDATION_ERRORS,
    },
)
async def login(body: LoginBody, service: IdentityDep, response: Response, request: Request, host: HostDep):
    validate_auth_origin(request, host.settings.public_base_url)
    user = await service.authenticate(body.username, body.password)
    token, expires_in = await service.issue_token(user)
    response.headers["Cache-Control"] = "no-store"
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=expires_in,
        httponly=True,
        secure=host.settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(CSRF_COOKIE, service.sessions.csrf_token(token), max_age=expires_in,
                        secure=host.settings.cookie_secure, samesite="lax", path="/")
    return success(
        {
            "access_token": token,
            "expires_in": expires_in,
            "user": user.public_dict(),
        }
    )


@router.get(
    "/session",
    response_model=ApiResponse[UserPublic],
    responses=AUTH_ERRORS,
)
async def session(user: CurrentUser, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return success(user.public_dict())


@router.get("/execution-policy", response_model=ApiResponse[ExecutionPolicy], responses=AUTH_ERRORS)
async def execution_policy(user: ReadUser):
    return success(user.execution_policy.model_dump())


@router.put("/execution-policy", response_model=ApiResponse[ExecutionPolicy], responses=AUTH_ERRORS)
async def update_execution_policy(body: ExecutionPolicy, user: CurrentUser, service: IdentityDep):
    updated = await service.set_execution_policy(user.user_id, body)
    return success(updated.execution_policy.model_dump())


@router.post("/logout", response_model=ApiResponse[None], responses=AUTH_ERRORS)
async def logout(response: Response, request: Request, user: CurrentUser, service: IdentityDep, host: HostDep):
    authorization = request.headers.get("authorization", "")
    token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else request.cookies.get(SESSION_COOKIE, "")
    await service.sessions.revoke(token)
    response.headers["Cache-Control"] = "no-store"
    response.delete_cookie(SESSION_COOKIE, path="/", secure=host.settings.cookie_secure, httponly=True, samesite="lax")
    response.delete_cookie(CSRF_COOKIE, path="/", secure=host.settings.cookie_secure, samesite="lax")
    return success()

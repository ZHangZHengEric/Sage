from fastapi import APIRouter, Response
from app.v2.server.runtime.policy import ExecutionPolicy

from app.v2.server.routers.deps import CurrentUser, IdentityDep
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
async def register(body: RegisterBody, service: IdentityDep):
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
async def login(body: LoginBody, service: IdentityDep, response: Response):
    user = await service.authenticate(body.username, body.password)
    token, expires_in = service.issue_token(user)
    response.set_cookie(
        "sage_server_v2",
        token,
        max_age=expires_in,
        httponly=True,
        samesite="lax",
        path="/",
    )
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
async def session(user: CurrentUser):
    return success(user.public_dict())


@router.get("/execution-policy", response_model=ApiResponse[ExecutionPolicy], responses=AUTH_ERRORS)
async def execution_policy(user: CurrentUser):
    return success(user.execution_policy.model_dump())


@router.put("/execution-policy", response_model=ApiResponse[ExecutionPolicy], responses=AUTH_ERRORS)
async def update_execution_policy(body: ExecutionPolicy, user: CurrentUser, service: IdentityDep):
    updated = await service.set_execution_policy(user.user_id, body)
    return success(updated.execution_policy.model_dump())


@router.post("/logout", response_model=ApiResponse[None])
async def logout(response: Response):
    response.delete_cookie("sage_server_v2", path="/")
    return success()

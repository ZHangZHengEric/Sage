from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.server_v2.bootstrap import ServerHost
from app.server_v2.identity.jwt import decode_access_token
from app.server_v2.identity.users import UserRecord
from app.server_v2.packages.management import ServerAgentManagement
from app.server_v2.packages.queries import ServerPackageQueries
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.principals import RequestContext

_bearer = HTTPBearer(auto_error=False)
_COOKIE = "sage_server_v2"


def get_service(request: Request) -> ServerHost:
    service = getattr(request.app.state, "service", None)
    if service is None:
        raise RuntimeError("Server v2 service is not attached")
    return service


ServiceDep = Annotated[ServerHost, Depends(get_service)]


def get_packages(host: ServiceDep) -> ServerAgentManagement:
    management = host.agent_management
    if management is None:
        raise RuntimeError("package management is not started")
    return management


def get_package_queries(host: ServiceDep) -> ServerPackageQueries:
    queries = host.package_queries
    if queries is None:
        raise RuntimeError("package queries are not started")
    return queries


PackageDep = Annotated[ServerAgentManagement, Depends(get_packages)]
PackageQueriesDep = Annotated[ServerPackageQueries, Depends(get_package_queries)]


def _token_from(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
) -> str:
    if credentials is not None and credentials.credentials.strip():
        return credentials.credentials.strip()
    return (request.cookies.get(_COOKIE) or "").strip()


async def get_optional_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    service: ServiceDep,
) -> UserRecord | None:
    token = _token_from(request, credentials)
    if not token:
        return None
    try:
        claims = decode_access_token(token, secret=service.settings.jwt_secret)
    except SageV2Error:
        return None
    return await service.identity.users.get_by_id(str(claims.get("userid") or ""))


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    service: ServiceDep,
) -> UserRecord:
    token = _token_from(request, credentials)
    if not token:
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.routers.deps.unauthenticated",
                category=ErrorCategory.AUTHENTICATION,
                message="authentication required",
            )
        )
    claims = decode_access_token(token, secret=service.settings.jwt_secret)
    user = await service.identity.users.get_by_id(str(claims["userid"]))
    if user is None:
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.routers.deps.unauthenticated",
                category=ErrorCategory.AUTHENTICATION,
                message="authentication required",
            )
        )
    return user


CurrentUser = Annotated[UserRecord, Depends(get_current_user)]
OptionalUser = Annotated[UserRecord | None, Depends(get_optional_user)]


def get_package_context(user: CurrentUser, host: ServiceDep) -> RequestContext:
    return host.contexts.for_user(user.user_id)


PackageContextDep = Annotated[RequestContext, Depends(get_package_context)]


def require_admin(user: CurrentUser) -> UserRecord:
    if user.role != "admin":
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.routers.deps.forbidden",
                category=ErrorCategory.AUTHORIZATION,
                message="admin required",
            )
        )
    return user


AdminUser = Annotated[UserRecord, Depends(require_admin)]

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.server_v2.core.errors import ServerV2Error
from app.server_v2.core.jwt import decode_access_token
from app.server_v2.services.runtime import ServerV2Service
from app.server_v2.domain.users import UserRecord

_bearer = HTTPBearer(auto_error=False)
_COOKIE = "sage_server_v2"


def get_service(request: Request) -> ServerV2Service:
    service = getattr(request.app.state, "service", None)
    if service is None:
        raise RuntimeError("Server v2 service is not attached")
    return service


ServiceDep = Annotated[ServerV2Service, Depends(get_service)]


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
    except ServerV2Error:
        return None
    return await service.users.get_by_id(str(claims.get("userid") or ""))


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    service: ServiceDep,
) -> UserRecord:
    token = _token_from(request, credentials)
    if not token:
        raise ServerV2Error("unauthenticated", "authentication required")
    claims = decode_access_token(token, secret=service.settings.jwt_secret)
    user = await service.users.get_by_id(str(claims["userid"]))
    if user is None:
        raise ServerV2Error("unauthenticated", "authentication required")
    return user


CurrentUser = Annotated[UserRecord, Depends(get_current_user)]
OptionalUser = Annotated[UserRecord | None, Depends(get_optional_user)]


def require_admin(user: CurrentUser) -> UserRecord:
    if user.role != "admin":
        raise ServerV2Error("forbidden", "admin required")
    return user


AdminUser = Annotated[UserRecord, Depends(require_admin)]

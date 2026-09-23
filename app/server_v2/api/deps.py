from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.server_v2.application.admin import AdminService
from app.server_v2.application.catalog import CatalogService
from app.server_v2.application.conversations import ConversationService
from app.server_v2.application.credentials import CredentialService
from app.server_v2.application.identity import IdentityService
from app.server_v2.application.skills import SkillCatalogService
from app.server_v2.bootstrap.host import ServerV2Service
from app.server_v2.core.errors import ServerV2Error
from app.server_v2.core.jwt import decode_access_token
from app.server_v2.domain.users import UserRecord

_bearer = HTTPBearer(auto_error=False)
_COOKIE = "sage_server_v2"


def get_service(request: Request) -> ServerV2Service:
    service = getattr(request.app.state, "service", None)
    if service is None:
        raise RuntimeError("Server v2 service is not attached")
    return service


ServiceDep = Annotated[ServerV2Service, Depends(get_service)]


def get_catalog(host: ServiceDep) -> CatalogService:
    return host.catalog


def get_identity(host: ServiceDep) -> IdentityService:
    return host.identity


def get_credentials(host: ServiceDep) -> CredentialService:
    return host.credentials


def get_conversations(host: ServiceDep) -> ConversationService:
    return host.conversations


def get_skills(host: ServiceDep) -> SkillCatalogService:
    return host.skill_catalog


def get_admin(host: ServiceDep) -> AdminService:
    return host.admin


CatalogDep = Annotated[CatalogService, Depends(get_catalog)]
IdentityDep = Annotated[IdentityService, Depends(get_identity)]
CredentialDep = Annotated[CredentialService, Depends(get_credentials)]
ConversationDep = Annotated[ConversationService, Depends(get_conversations)]
SkillDep = Annotated[SkillCatalogService, Depends(get_skills)]
AdminDep = Annotated[AdminService, Depends(get_admin)]


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
    return await service.identity.get_by_id(str(claims.get("userid") or ""))


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    service: ServiceDep,
) -> UserRecord:
    token = _token_from(request, credentials)
    if not token:
        raise ServerV2Error("unauthenticated", "authentication required")
    claims = decode_access_token(token, secret=service.settings.jwt_secret)
    user = await service.identity.get_by_id(str(claims["userid"]))
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

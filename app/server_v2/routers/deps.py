from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.server_v2.bootstrap import ServerHost
from app.server_v2.admin.service import AdminService
from app.server_v2.catalog.service import CatalogService
from app.server_v2.conversations.a2a.service import A2AService
from app.server_v2.conversations.agui.service import ConversationService
from app.server_v2.identity.credentials import CredentialService
from app.server_v2.identity.service import IdentityService
from app.server_v2.skills.service import SkillCatalogService
from app.server_v2.identity.users import UserRecord
from app.server_v2.packages.management import ServerAgentManagement
from app.server_v2.packages.queries import ServerPackageQueries
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.principals import RequestContext

_bearer = HTTPBearer(auto_error=False)
_COOKIE = "sage_server_v2"


def get_host(request: Request) -> ServerHost:
    host = getattr(request.app.state, "service", None)
    if host is None:
        raise RuntimeError("Server v2 host is not attached")
    return host


HostDep = Annotated[ServerHost, Depends(get_host)]


def get_identity(host: HostDep) -> IdentityService:
    return host.identity


def get_credentials(host: HostDep) -> CredentialService:
    return host.credentials


def get_catalog(host: HostDep) -> CatalogService:
    return host.catalog


def get_skills(host: HostDep) -> SkillCatalogService:
    return host.skill_catalog


def get_conversations(host: HostDep) -> ConversationService:
    if host.conversations is None:
        raise RuntimeError("conversation service is not started")
    return host.conversations


def get_admin(host: HostDep) -> AdminService:
    if host.admin is None:
        raise RuntimeError("admin service is not started")
    return host.admin


def get_a2a(host: HostDep) -> A2AService:
    if host.a2a is None:
        raise RuntimeError("A2A service is not started")
    return host.a2a


IdentityDep = Annotated[IdentityService, Depends(get_identity)]
CredentialDep = Annotated[CredentialService, Depends(get_credentials)]
CatalogDep = Annotated[CatalogService, Depends(get_catalog)]
SkillDep = Annotated[SkillCatalogService, Depends(get_skills)]
ConversationDep = Annotated[ConversationService, Depends(get_conversations)]
AdminDep = Annotated[AdminService, Depends(get_admin)]
A2ADep = Annotated[A2AService, Depends(get_a2a)]


def get_packages(host: HostDep) -> ServerAgentManagement:
    management = host.agent_management
    if management is None:
        raise RuntimeError("package management is not started")
    return management


def get_package_queries(host: HostDep) -> ServerPackageQueries:
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
    service: IdentityDep,
) -> UserRecord | None:
    token = _token_from(request, credentials)
    if not token:
        return None
    try:
        return await service.from_token(token)
    except SageV2Error:
        return None


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    service: IdentityDep,
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
    user = await service.from_token(token)
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


def get_package_context(user: CurrentUser, host: HostDep) -> RequestContext:
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

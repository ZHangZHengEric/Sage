from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.v2.server.bootstrap import ServerHost
from app.v2.server.admin.service import AdminService
from app.v2.server.catalog.service import CatalogService
from app.v2.server.conversations.a2a.service import A2AService
from app.v2.server.conversations.agui.service import ConversationService
from app.v2.server.identity.credentials import CredentialService
from app.v2.server.identity.service import IdentityService
from app.v2.server.skills.service import SkillCatalogService
from app.v2.server.identity.users import UserRecord
from app.v2.server.packages.management import ServerAgentManagement
from app.v2.server.packages.queries import ServerPackageQueries
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
    if request.headers.get("X-Sage-View-User") is not None and request.method != "GET":
        raise SageV2Error(RuntimeErrorInfo(
            code="server.routers.deps.forbidden",
            category=ErrorCategory.AUTHORIZATION,
            message="admin data viewing is read-only",
        ))
    return user


CurrentUser = Annotated[UserRecord, Depends(get_current_user)]
OptionalUser = Annotated[UserRecord | None, Depends(get_optional_user)]


async def get_read_user(
    request: Request,
    user: CurrentUser,
    service: IdentityDep,
    view_user: Annotated[str | None, Header(alias="X-Sage-View-User", min_length=1, max_length=128)] = None,
) -> UserRecord:
    """Resolve an explicitly requested read scope without changing the caller identity."""
    if view_user is None:
        return user
    if user.role != "admin" or request.method != "GET":
        raise SageV2Error(RuntimeErrorInfo(
            code="server.routers.deps.forbidden",
            category=ErrorCategory.AUTHORIZATION,
            message="only admin can view another user's data",
        ))
    owner = await service.get_by_id(view_user)
    if owner is None:
        raise SageV2Error(RuntimeErrorInfo(
            code="server.routers.deps.not_found",
            category=ErrorCategory.VALIDATION,
            message="user not found",
        ))
    return owner


ReadUser = Annotated[UserRecord, Depends(get_read_user)]


def get_package_read_context(user: ReadUser, host: HostDep) -> RequestContext:
    return host.contexts.for_user(user.user_id)


PackageReadContextDep = Annotated[RequestContext, Depends(get_package_read_context)]


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


class ChatCaller:
    def __init__(self, user_id: str, agent_id: str | None = None, api_key=None):
        self.user_id = user_id
        self.agent_id = agent_id
        self.api_key = api_key


async def get_chat_caller(
    request: Request,
    host: HostDep,
    user: OptionalUser,
    agent_id: Annotated[str | None, Header(alias="SAGE-AGENT-ID", min_length=1, max_length=128)] = None,
    user_id: Annotated[str | None, Header(alias="SAGE-TENANT-ID", min_length=1, max_length=128)] = None,
) -> ChatCaller:
    if agent_id is not None or user_id is not None:
        if not agent_id or not user_id or not agent_id.strip() or not user_id.strip():
            raise SageV2Error(RuntimeErrorInfo(code="server.chat.invalid_identity",
                category=ErrorCategory.VALIDATION, message="SAGE-AGENT-ID and SAGE-TENANT-ID headers are required together"))
        from app.v2.server.identity.external import authorize_external_agent
        key = await authorize_external_agent(request, host, agent_id)
        return ChatCaller(user_id, agent_id, key)
    if user is None:
        raise SageV2Error(RuntimeErrorInfo(code="server.chat.unauthenticated",
            category=ErrorCategory.AUTHENTICATION, message="authentication required"))
    return ChatCaller(user.user_id)


ChatCallerDep = Annotated[ChatCaller, Depends(get_chat_caller)]

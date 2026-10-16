"""Authenticate machine callers before accepting their end-user identity."""
from app.v2.server.identity.keys import SCOPE_APPROVE, SCOPE_INVOKE, SCOPE_READ, require_scope
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error


async def authorize_external_agent(request, host, agent_id):
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise SageV2Error(RuntimeErrorInfo(
            code="server.external.unauthenticated", category=ErrorCategory.AUTHENTICATION,
            message="Agent API key required in Authorization: Bearer",
        ))
    key = await host.credentials.authenticate(token.strip())
    owner = await host.catalog.agent_owner(agent_id)
    if (key.agent_id != agent_id or owner != key.owner_user_id
            or await host.users.get_by_id(key.owner_user_id) is None):
        raise SageV2Error(RuntimeErrorInfo(
            code="server.external.forbidden", category=ErrorCategory.AUTHORIZATION,
            message="API key is not authorized for this Agent",
        ))
    scope = SCOPE_READ if request.method in {"GET", "HEAD"} else SCOPE_INVOKE
    if request.url.path.endswith("/reply"):
        scope = SCOPE_APPROVE
    require_scope(key, scope)
    return key

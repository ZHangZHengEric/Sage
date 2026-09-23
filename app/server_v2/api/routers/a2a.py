from __future__ import annotations

import json
from typing import Annotated

from a2a.server.routes.jsonrpc_dispatcher import JsonRpcDispatcher
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from google.protobuf.json_format import MessageToDict

from app.server_v2.adapters.a2a.card import RPC_PATH
from app.server_v2.adapters.a2a.context import REQUEST_ATTR, SageCallContextBuilder
from app.server_v2.adapters.a2a.handler import SageRequestHandler
from app.server_v2.api.deps import CredentialDep, ServiceDep
from app.server_v2.core.errors import ServerV2Error
from app.server_v2.domain.api_keys import (
    SCOPE_INVOKE,
    SCOPE_READ,
    ApiKeyRecord,
    require_scope,
)

router = APIRouter(tags=["a2a"])

_bearer = HTTPBearer(auto_error=False)

# Which scope each JSON-RPC method needs. Authorization is settled here, at the
# HTTP layer, because A2A's JSON-RPC error set has no code for "forbidden" —
# answering a denied call with -32004 would read as "this agent cannot do that"
# rather than "this key may not".
_METHOD_SCOPES = {
    "SendMessage": SCOPE_INVOKE,
    "SendStreamingMessage": SCOPE_INVOKE,
    "CancelTask": SCOPE_INVOKE,
    "CreateTaskPushNotificationConfig": SCOPE_INVOKE,
    "DeleteTaskPushNotificationConfig": SCOPE_INVOKE,
    "GetTask": SCOPE_READ,
    "ListTasks": SCOPE_READ,
    "SubscribeToTask": SCOPE_READ,
    "GetTaskPushNotificationConfig": SCOPE_READ,
    "ListTaskPushNotificationConfigs": SCOPE_READ,
    "GetExtendedAgentCard": SCOPE_READ,
}


async def a2a_key(
    request: Request,
    bearer: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    keys: CredentialDep,
) -> ApiKeyRecord:
    """Authenticate the caller and pin the credential to this request.

    The A2A dispatcher builds its call context synchronously, so the key must
    already be resolved by the time it runs — hence a dependency rather than
    work inside ``SageCallContextBuilder``.
    """

    token = (bearer.credentials.strip() if bearer is not None else "")
    if not token:
        raise ServerV2Error("unauthenticated", "api key required")
    key = await keys.authenticate(token)
    setattr(request.state, REQUEST_ATTR, key)
    return key


KeyDep = Annotated[ApiKeyRecord, Depends(a2a_key)]


@router.post(RPC_PATH)
async def jsonrpc(request: Request, key: KeyDep, service: ServiceDep) -> Response:
    await _authorize_method(request, key)
    dispatcher = JsonRpcDispatcher(
        SageRequestHandler(service.a2a),
        context_builder=SageCallContextBuilder(),
    )
    return await dispatcher.handle_requests(request)


@router.get("/.well-known/agent-card.json")
@router.get(f"{RPC_PATH}/card")
async def agent_card(request: Request, key: KeyDep, service: ServiceDep) -> Response:
    """Serve the card for the Agent this key is bound to.

    A2A puts the card at a well-known unauthenticated path, which assumes one
    agent per origin. A Sage host serves many tenants from one origin, so the
    card is authenticated instead: an anonymous card here could only describe
    some arbitrary tenant's Agent, or nothing at all.
    """

    require_scope(key, SCOPE_READ)
    card = await service.a2a.card(key, base_url=_base_url(request, service))
    return JSONResponse(MessageToDict(card, preserving_proto_field_name=False))


async def _authorize_method(request: Request, key: ApiKeyRecord) -> None:
    """Check the key's scopes against the method before dispatching.

    The body is read here and again by the dispatcher; Starlette caches it, so
    this costs one parse and no extra read of the socket.
    """

    try:
        body = json.loads(await request.body() or b"{}")
    except ValueError:
        # Malformed JSON is the dispatcher's to report, with a JSON-RPC
        # -32700, not something to turn into an authorization failure.
        return
    method = body.get("method") if isinstance(body, dict) else None
    scope = _METHOD_SCOPES.get(str(method or ""))
    if scope is not None:
        require_scope(key, scope)


def _base_url(request: Request, service) -> str:
    return service.settings.public_base_url or str(request.base_url).rstrip("/")

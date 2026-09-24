from __future__ import annotations

from a2a.auth.user import User
from a2a.extensions.common import HTTP_EXTENSION_HEADER, get_requested_extensions
from a2a.server.context import ServerCallContext
from a2a.server.routes.common import ServerCallContextBuilder
from starlette.requests import Request

from app.server_v2.core.errors import ServerError
from app.server_v2.domain.api_keys import ApiKeyRecord

# Where the authenticated credential lives on the request and on the context.
# The dependency writes the first, this builder copies it to the second.
REQUEST_ATTR = "a2a_key"
STATE_KEY = "sage.api_key"
BASE_URL_KEY = "sage.base_url"


class ApiKeyUser(User):
    """The A2A principal for one Sage API key."""

    def __init__(self, key: ApiKeyRecord) -> None:
        self._key = key

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def user_name(self) -> str:
        return self._key.key_id


class SageCallContextBuilder(ServerCallContextBuilder):
    """Carry the already-authenticated key into the A2A call context.

    ``build`` is synchronous but resolving an API key is a database read, so
    authentication happens in a FastAPI dependency and this builder only moves
    the result across. It deliberately does not populate ``tenant``: the
    dispatcher overwrites that field with whatever the *request body* says
    immediately after calling us, so anything written here would be a lie.
    Handlers read the tenant from the key via :func:`key_from`.
    """

    def build(self, request: Request) -> ServerCallContext:
        key = getattr(request.state, REQUEST_ATTR, None)
        if not isinstance(key, ApiKeyRecord):
            raise ServerError("unauthenticated", "authentication required")
        return ServerCallContext(
            user=ApiKeyUser(key),
            state={
                STATE_KEY: key,
                BASE_URL_KEY: str(request.base_url).rstrip("/"),
                "headers": dict(request.headers),
            },
            requested_extensions=get_requested_extensions(
                request.headers.getlist(HTTP_EXTENSION_HEADER)
            ),
        )


def key_from(context: ServerCallContext | None) -> ApiKeyRecord:
    """Return the credential this call was made with.

    This is the only admissible source of tenant identity on the A2A surface.
    ``context.tenant`` is attacker-controlled — the dispatcher assigns it from
    the request body — so a handler that trusted it would let any valid key
    read any tenant's Tasks.
    """

    key = None if context is None else context.state.get(STATE_KEY)
    if not isinstance(key, ApiKeyRecord):
        raise ServerError("unauthenticated", "authentication required")
    return key


def base_url_from(context: ServerCallContext | None, fallback: str = "") -> str:
    value = "" if context is None else str(context.state.get(BASE_URL_KEY) or "")
    return value or fallback

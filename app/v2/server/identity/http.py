"""HTTP-only session transport and CSRF checks; no account or provider logic."""

import hmac
from urllib.parse import urlsplit

from fastapi import Request

from app.v2.server.identity.service import IdentityService
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error

SESSION_COOKIE = "sage_server_v2"
CSRF_COOKIE = "sage_server_v2_csrf"


def _forbidden() -> SageV2Error:
    return SageV2Error(
        RuntimeErrorInfo(
            code="server.identity.http.forbidden",
            category=ErrorCategory.AUTHORIZATION,
            message="request origin or CSRF token is invalid",
        )
    )


def validate_auth_origin(request: Request, public_base_url: str) -> None:
    origin = request.headers.get("origin")
    if origin is None:
        return  # Non-browser clients authenticate explicitly.
    allowed = {str(request.base_url).rstrip("/")}
    if public_base_url:
        parsed = urlsplit(public_base_url)
        allowed.add(f"{parsed.scheme}://{parsed.netloc}")
    if origin not in allowed:
        raise _forbidden()


def validate_cookie_write(
    request: Request, token: str, service: IdentityService
) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    supplied = request.headers.get("X-CSRF-Token", "")
    if not supplied or not hmac.compare_digest(
        supplied.encode(), service.sessions.csrf_token(token).encode()
    ):
        raise _forbidden()

from __future__ import annotations

from urllib.parse import quote, urlparse

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response

from app.server_v2.api.deps import AdminUser, OptionalUser

router = APIRouter(prefix="/api/observability", tags=["observability"])


def _public_jaeger_url(request: Request, path_suffix: str = "/", query: str = "") -> str:
    base = (request.app.state.service.settings.jaeger_public_url or "").rstrip("/")
    suffix = "/" + (path_suffix or "/").lstrip("/")
    url = f"{base}{suffix}"
    if query:
        url = f"{url}?{query}"
    return url


def _next_path(request: Request) -> str:
    next_url = request.query_params.get("next")
    if next_url:
        parsed = urlparse(next_url)
        if parsed.scheme or parsed.netloc:
            return "/"
        return next_url if next_url.startswith("/") else "/"
    return "/"


@router.get("/jaeger/login")
async def login_jaeger(request: Request, user: OptionalUser):
    next_path = _next_path(request)
    if user is not None and user.role == "admin":
        return RedirectResponse(url=next_path, status_code=302)
    return RedirectResponse(
        url=f"/login?next={quote(next_path, safe='/?:#=&')}",
        status_code=302,
    )


@router.get("/jaeger/auth")
async def auth_jaeger(user: AdminUser):
    return Response(
        status_code=204,
        headers={
            "X-Sage-UserId": user.user_id,
            "X-Sage-Username": user.username,
            "X-Sage-Role": user.role,
        },
    )


@router.get("/jaeger")
async def redirect_jaeger_root(request: Request):
    return RedirectResponse(url=_public_jaeger_url(request), status_code=307)


@router.api_route(
    "/jaeger/{full_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    include_in_schema=False,
)
async def redirect_jaeger_path(request: Request, full_path: str):
    return RedirectResponse(
        url=_public_jaeger_url(request, full_path, request.url.query),
        status_code=307,
    )

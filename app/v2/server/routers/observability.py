from __future__ import annotations

from urllib.parse import quote, urlparse
import asyncio
from datetime import datetime, timedelta, timezone
import sqlite3
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Request, Query, HTTPException
from fastapi.responses import RedirectResponse, Response

from app.v2.server.routers.deps import AdminUser, OptionalUser
from app.v2.server.routers.deps import HostDep
from app.v2.server.routers.render import success

router = APIRouter(prefix="/api/observability", tags=["observability"])


def _public_jaeger_url(
    request: Request, path_suffix: str = "/", query: str = ""
) -> str:
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


console_router = APIRouter(prefix="/api/observability", tags=["observability"])
performance_router = APIRouter(prefix="/api/observability", tags=["observability"])


@performance_router.get("/performance")
async def performance(
    _: AdminUser,
    host: HostDep,
    start: datetime | None = None,
    end: datetime | None = None,
    agent_id: str = Query(default="", max_length=256),
    bucket: str = Query(default="hour", pattern="^(hour|day)$"),
    timezone_name: str = Query(default="Asia/Shanghai", max_length=64),
):
    from app.v2.server.observability.performance import report

    end = end or datetime.now(timezone.utc)
    start = start or end - timedelta(hours=24)
    if (
        start.tzinfo is None
        or end.tzinfo is None
        or not timedelta(0) < end - start <= timedelta(days=31)
    ):
        raise HTTPException(422, "选择带时区的起止时间，范围不超过 31 天")
    try:
        ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise HTTPException(422, "无效时区") from exc
    diagnostics = host.diagnostics
    if diagnostics is None or not diagnostics.available:
        raise HTTPException(503, "性能记录暂不可用")
    try:
        result = await asyncio.to_thread(
            report,
            diagnostics.path,
            start=start.timestamp(),
            end=end.timestamp(),
            agent_id=agent_id,
            bucket=bucket,
            timezone_name=timezone_name,
        )
    except (OSError, sqlite3.Error) as exc:
        raise HTTPException(503, "性能记录暂不可用") from exc
    result["capture_failures"] = diagnostics.capture_failures
    return success(result)


@console_router.get("/console")
async def open_trace_console(request: Request, user: AdminUser):
    return RedirectResponse(
        url=request.app.state.service.settings.trace_console_url, status_code=307
    )

from __future__ import annotations

from urllib.parse import quote, urlparse
import asyncio
from datetime import datetime, timedelta, timezone
import sqlite3
import httpx
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Request, Query, Path, HTTPException
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


def _trace_console(host):
    sink = host.application.service("observability.trace-sink")
    settings = host.settings
    plugin = getattr(sink, "plugin_id", "")
    if plugin == "sage.trace.phoenix":
        return {"id": "phoenix", "label": "运行性能", "href": "/performance", "external": False}
    elif plugin == "sage.trace.langfuse":
        entry = ("langfuse", "Langfuse", settings.langfuse_public_url or settings.langfuse_base_url)
    elif plugin == "sage.trace.otlp" and settings.jaeger_url and not settings.trace_otlp_endpoint:
        entry = ("jaeger", "Jaeger", settings.jaeger_public_url)
    else:
        return None
    service_id, label, url = entry
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username is not None:
        return None
    return {"id": service_id, "label": label, "href": url, "external": True}


@performance_router.get("/services")
async def observability_services(_: AdminUser, host: HostDep):
    links = []
    if host.diagnostics is not None and host.diagnostics.available:
        links.append({"id": "performance", "label": "运行性能", "href": "/performance", "external": False})
    if (console := _trace_console(host)) and console["external"]:
        links.append(console)
    return success(links)


def _phoenix_dashboard(host):
    from app.v2.server.observability.external import ExternalDiagnostics
    from app.v2.server.observability.phoenix_dashboard import PhoenixDashboard

    source = host.diagnostics
    if not isinstance(source, ExternalDiagnostics) or source.backend != "phoenix":
        raise HTTPException(404, "未启用 Phoenix")
    return PhoenixDashboard(source)


def _trace_range(start, end):
    end = end or datetime.now(timezone.utc)
    start = start or end - timedelta(hours=24)
    if (start.tzinfo is None or end.tzinfo is None
            or not timedelta(0) < end - start <= timedelta(days=31)):
        raise HTTPException(422, "选择带时区的起止时间，范围不超过 31 天")
    return dict(start=start.isoformat(), end=end.isoformat())


async def _phoenix_result(operation):
    try:
        async with asyncio.timeout(30):
            return success(await operation)
    except (httpx.HTTPError, ValueError, KeyError, TypeError, TimeoutError) as exc:
        raise HTTPException(503, "调用链数据暂不可用") from exc


@performance_router.get("/traces/summary")
async def trace_summary(_: AdminUser, host: HostDep, start: datetime | None = None,
                        end: datetime | None = None,
                        agent_id: str = Query(default="", max_length=256),
                        session_id: str = Query(default="", max_length=256)):
    dashboard = _phoenix_dashboard(host)
    return await _phoenix_result(dashboard.summary(**_trace_range(start, end), agent_id=agent_id, session_id=session_id))


@performance_router.get("/trace-spans")
async def trace_spans(_: AdminUser, host: HostDep, start: datetime | None = None,
                      end: datetime | None = None,
                      agent_id: str = Query(default="", max_length=256),
                      session_id: str = Query(default="", max_length=256),
                      kind: str = Query(default="AGENT", pattern="^(AGENT|LLM|TOOL|ALL)$"),
                      status: str = Query(default="", pattern="^(|OK|ERROR|UNSET)$"),
                      cursor: str | None = Query(default=None, max_length=4096)):
    dashboard = _phoenix_dashboard(host)
    return await _phoenix_result(dashboard.spans(**_trace_range(start, end), agent_id=agent_id,
                                               session_id=session_id, kind=kind, status=status, cursor=cursor))


@performance_router.get("/traces/{trace_id}/spans")
async def trace_tree(_: AdminUser, host: HostDep,
                     trace_id: str = Path(pattern="^[a-fA-F0-9]{32}$"),
                     cursor: str | None = Query(default=None, max_length=4096)):
    return await _phoenix_result(_phoenix_dashboard(host).spans(trace_id=trace_id, cursor=cursor))


@performance_router.get("/trace-spans/{span_id}")
async def trace_span(_: AdminUser, host: HostDep,
                     span_id: str = Path(pattern="^[a-fA-F0-9]{16}$")):
    async def read():
        result = await _phoenix_dashboard(host).span(span_id)
        if result is None:
            raise HTTPException(404, "调用记录不存在")
        return result
    return await _phoenix_result(read())


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
        from app.v2.server.observability.external import ExternalDiagnostics

        options = dict(start=start.timestamp(), end=end.timestamp(), agent_id=agent_id,
                       bucket=bucket, timezone_name=timezone_name)
        if isinstance(diagnostics, ExternalDiagnostics):
            async with asyncio.timeout(30):
                result = await diagnostics.report(**options)
        else:
            result = await asyncio.to_thread(report, diagnostics.path, **options)
            result["source"] = "local"
    except (OSError, sqlite3.Error, httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(503, "性能记录暂不可用") from exc
    result["capture_failures"] = diagnostics.capture_failures
    return success(result)


@console_router.get("/console")
async def open_trace_console(_: AdminUser, host: HostDep):
    console = _trace_console(host)
    if console is None:
        raise HTTPException(404, "未启用观测控制台")
    return RedirectResponse(url=console["href"], status_code=307)

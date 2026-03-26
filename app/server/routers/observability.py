from urllib.parse import quote, urlparse

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response

from ..core import config
from ..core.exceptions import SageHTTPException
from ..models.user import User, UserDao
from ..services.auth.external_oauth import is_local_auth_enabled

observability_router = APIRouter(prefix="/api/observability", tags=["Observability"])


def _build_public_jaeger_url(
    cfg: config.StartupConfig,
    path_suffix: str = "/",
    query: str = "",
) -> str:
    base = (cfg.trace_jaeger_public_url or "").rstrip("/")
    suffix = "/" + (path_suffix or "/").lstrip("/")
    url = f"{base}{suffix}"
    if query:
        url = f"{url}?{query}"
    return url


async def _get_current_user(request: Request) -> User | None:
    claims = getattr(request.state, "user_claims", None) or {}
    user_id = (claims.get("userid") or "").strip()
    if not user_id:
        return None
    return await UserDao().get_by_id(user_id)


def _build_request_next_path(request: Request, default: str = "/") -> str:
    next_url = request.query_params.get("next")
    if next_url:
        parsed = urlparse(next_url)
        if parsed.scheme or parsed.netloc:
            candidate = parsed.path or "/"
            if parsed.query:
                candidate = f"{candidate}?{parsed.query}"
            if parsed.fragment:
                candidate = f"{candidate}#{parsed.fragment}"
            return candidate if candidate.startswith("/") else default
        return next_url if next_url.startswith("/") else default
    original_uri = (request.headers.get("x-original-uri") or "").strip()
    if original_uri.startswith("/"):
        return original_uri
    if request.url.query:
        return f"{request.url.path}?{request.url.query}"
    return request.url.path or default


def _build_web_login_path(cfg: config.StartupConfig, next_path: str) -> str:
    base = (cfg.web_base_path or "/sage").rstrip("/")
    return f"{base}/login?next={quote(next_path, safe='/?:#=&')}&local_only=1"


@observability_router.get("/jaeger/login")
async def login_jaeger(request: Request):
    cfg = config.get_startup_config()
    next_path = _build_request_next_path(request)
    user = await _get_current_user(request)
    if user:
        if user.role != "admin":
            raise SageHTTPException(
                status_code=403,
                detail="权限不足",
                error_detail="observability requires admin role",
            )
        return RedirectResponse(url=next_path, status_code=302)

    if is_local_auth_enabled():
        return RedirectResponse(
            url=_build_web_login_path(cfg, next_path),
            status_code=302,
        )

    raise SageHTTPException(
        status_code=503,
        detail="Jaeger 仅支持本地管理员登录",
        error_detail="local auth required for observability",
    )


@observability_router.get("/jaeger/auth")
async def auth_jaeger(request: Request):
    user = await _get_current_user(request)
    if not user:
        return Response(status_code=401)
    if user.role != "admin":
        return Response(status_code=403)
    return Response(
        status_code=204,
        headers={
            "X-Sage-UserId": user.user_id,
            "X-Sage-Username": user.username,
            "X-Sage-Role": user.role,
        },
    )


@observability_router.get("/jaeger")
async def redirect_jaeger_root(request: Request):
    cfg = config.get_startup_config()
    return RedirectResponse(url=_build_public_jaeger_url(cfg), status_code=307)


@observability_router.api_route(
    "/jaeger/{full_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
async def proxy_jaeger(request: Request, full_path: str):
    cfg = config.get_startup_config()
    target_url = _build_public_jaeger_url(cfg, full_path, request.url.query)
    return RedirectResponse(url=target_url, status_code=307)

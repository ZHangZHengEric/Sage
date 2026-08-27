"""
中间件模块
"""

import re
from typing import Tuple

from fastapi import Request
from fastapi.responses import JSONResponse
from loguru import logger

from common.core import config
from common.core.exceptions import SageHTTPException
from common.core.i18n import locale_from_request, translate_if_key
from common.core.middleware import (
    register_cors_middleware,
    register_request_logging_middleware,
)
from common.core.render import Response
from app.server.services.prometheus_metrics import (
    finish_http_request,
    start_http_request,
)
from .auth import get_session_claims, parse_access_token

# 白名单 API 路径
WHITELIST_API_PATHS = frozenset(
    {
        "/api/health",
        "/api/system/info",
        "/api/auth/register",
        "/api/auth/login",
        "/api/user/login",
        "/api/user/register",
        "/api/observability/jaeger",
        "/api/observability/jaeger/login",
        "/api/observability/jaeger/auth",
        "/api/observability/jaeger/{full_path:path}",
        "/api/observability/metrics",
        "/api/stream",
        "/api/chat",
        "/api/sessions/{session_id}/interrupt",
        "/api/system/version/check",
        "/api/system/version/latest",
        "/api/share/conversations/{conversation_id}/messages",
        "/api/mcp/anytool/AnyTool",
        "/api/token-usage/stats",
    }
)


def _compile_whitelist_regex(paths: frozenset[str]) -> Tuple[re.Pattern, ...]:
    """将带参数的路径转换为正则"""
    return tuple(
        re.compile("^" + re.sub(r"\{[^}]+\}", r"[^/]+", p) + "$")
        for p in paths
        if "{" in p
    )


WHITELIST_API_REGEXES = _compile_whitelist_regex(WHITELIST_API_PATHS)
PROMETHEUS_HTTP_METRICS_IGNORED_PATHS = frozenset(
    {
        "/",
        "/active",
        "/api/health",
        "/api/observability/metrics",
    }
)


def _is_whitelisted(path: str) -> bool:
    """判断路径是否在白名单"""
    return path in WHITELIST_API_PATHS or any(
        r.match(path) for r in WHITELIST_API_REGEXES
    )


def _should_record_prometheus_http_metrics(path: str) -> bool:
    return path not in PROMETHEUS_HTTP_METRICS_IGNORED_PATHS


async def _unauthorized_response(
    request: Request,
    status_code: int,
    detail: str,
    error_detail: str,
    message_params: dict | None = None,
):
    """统一返回未授权响应"""
    locale = locale_from_request(request)
    return JSONResponse(
        status_code=status_code,
        content=(
            await Response.error(
                status_code,
                translate_if_key(detail, locale, message_params),
                error_detail,
            )
        ).model_dump(),
    )


def register_middlewares(app):
    cfg = config.get_startup_config()

    register_cors_middleware(app)

    @app.middleware("http")
    async def prometheus_metrics_middleware(request: Request, call_next):
        if not _should_record_prometheus_http_metrics(request.url.path):
            return await call_next(request)
        started_at, method, path = start_http_request(request.method, request.url.path)
        status_code: int | str = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            finish_http_request(started_at, method, path, status_code)

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        path = request.url.path
        if path.startswith("/api"):
            if request.method == "OPTIONS":
                return await call_next(request)
            is_whitelisted = _is_whitelisted(path)
            auth = request.headers.get("Authorization", "")
            auth_error = None

            if auth.lower().startswith("bearer "):
                token = auth.split(" ", 1)[1]
                try:
                    request.state.user_claims = parse_access_token(token)
                except SageHTTPException as e:
                    auth_error = (
                        e.status_code,
                        e.message_key or str(e.detail),
                        e.error_detail,
                        e.message_params,
                    )
                except Exception as e:
                    auth_error = (401, "auth.invalid_token", str(e), None)

            if not getattr(request.state, "user_claims", None):
                session_claims = get_session_claims(request)
                if session_claims:
                    request.state.user_claims = session_claims

            if not getattr(request.state, "user_claims", None) and not is_whitelisted:
                if auth_error:
                    return await _unauthorized_response(request, *auth_error)
                return await _unauthorized_response(
                    request, 401, "auth.unauthorized", "missing auth session"
                )

        return await call_next(request)

    register_request_logging_middleware(app)

    # SessionMiddleware 必须包在鉴权中间件外层，才能在鉴权阶段读取 session claims。
    try:
        from starlette.middleware.sessions import SessionMiddleware
    except ImportError:
        logger.warning("SessionMiddleware 依赖未安装，跳过 session 中间件初始化")
        return

    app.add_middleware(
        SessionMiddleware,
        secret_key=cfg.session_secret or cfg.jwt_key,
        session_cookie=cfg.session_cookie_name,
        same_site=cfg.session_cookie_same_site,
        https_only=cfg.session_cookie_secure,
    )

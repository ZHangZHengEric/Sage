"""
中间件模块
"""

import ipaddress
import re
from typing import Tuple

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from common.core import config
from common.core.exceptions import SageHTTPException
from common.core.middleware import register_cors_middleware, register_request_logging_middleware
from common.core.render import Response
from .auth import get_session_claims, parse_access_token

# 白名单 API 路径
WHITELIST_API_PATHS = frozenset(
    {
        "/api/health",
        "/api/system/info",
        "/api/auth/register",
        "/api/auth/register/send-code",
        "/api/auth/login",
        "/api/auth/providers",
        "/api/auth/upstream/login",
        "/api/auth/upstream/login/{provider_id}",
        "/api/auth/upstream/callback/{provider_id}",
        "/api/user/login",
        "/api/user/register",
        "/api/user/register/send-code",
        "/api/user/auth-providers",
        "/api/user/oauth/login",
        "/api/user/oauth/login/{provider_id}",
        "/api/user/oauth/callback",
        "/api/user/oauth/callback/{provider_id}",
        "/api/oauth2/metadata",
        "/api/oauth2/authorize",
        "/api/oauth2/token",
        "/api/oauth2/userinfo",
        "/api/observability/jaeger",
        "/api/observability/jaeger/login",
        "/api/observability/jaeger/auth",
        "/api/observability/jaeger/{full_path:path}",
        "/api/stream",
        "/api/chat",
        "/api/system/version/check",
        "/api/system/version/latest",
        "/api/share/conversations/{conversation_id}/messages",
        "/api/mcp/anytool/AnyTool"
    }
)


def _compile_whitelist_regex(paths: frozenset[str]) -> Tuple[re.Pattern, ...]:
    """将带参数的路径转换为正则"""
    return tuple(re.compile("^" + re.sub(r"\{[^}]+\}", r"[^/]+", p) + "$") for p in paths if "{" in p)


WHITELIST_API_REGEXES = _compile_whitelist_regex(WHITELIST_API_PATHS)


def _is_whitelisted(path: str) -> bool:
    """判断路径是否在白名单"""
    return path in WHITELIST_API_PATHS or any(r.match(path) for r in WHITELIST_API_REGEXES)


def _is_trusted_identity_proxy(host: str | None, trusted_proxy_ips: list[str] | None) -> bool:
    """Trust identity passthrough only from configured proxy IPs/CIDRs."""
    if not host:
        return False
    if not trusted_proxy_ips:
        return False

    try:
        host_ip = ipaddress.ip_address(host)
    except ValueError:
        return False

    for entry in trusted_proxy_ips:
        try:
            if "/" in entry:
                if host_ip in ipaddress.ip_network(entry, strict=False):
                    return True
            elif host_ip == ipaddress.ip_address(entry):
                return True
        except ValueError:
            continue
    return False


async def _unauthorized_response(status_code: int, detail: str, error_detail: str):
    """统一返回未授权响应"""
    return JSONResponse(
        status_code=status_code,
        content=(await Response.error(status_code, detail, error_detail)).model_dump(),
    )


def register_middlewares(app):
    cfg = config.get_startup_config()

    register_cors_middleware(app)

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        path = request.url.path
        if path.startswith("/api"):
            if request.method == "OPTIONS":
                return await call_next(request)
            client_host = request.client.host if request.client else None
            is_trusted_proxy_client = _is_trusted_identity_proxy(client_host, cfg.trusted_identity_proxy_ips)
            is_whitelisted = _is_whitelisted(path)
            auth = request.headers.get("Authorization", "")
            auth_error = None

            if auth.lower().startswith("bearer "):
                token = auth.split(" ", 1)[1]
                try:
                    request.state.user_claims = parse_access_token(token)
                except SageHTTPException as e:
                    auth_error = (e.status_code, e.detail, e.error_detail)
                except Exception as e:
                    auth_error = (401, "Token非法", str(e))

            if not getattr(request.state, "user_claims", None):
                session_claims = get_session_claims(request)
                if session_claims:
                    request.state.user_claims = session_claims

            internal_user_id = request.headers.get("X-Sage-Internal-UserId")
            if not getattr(request.state, "user_claims", None) and internal_user_id and is_trusted_proxy_client:
                userid = internal_user_id.strip()
                if userid:
                    request.state.user_claims = {
                        "userid": userid,
                        "username": userid,
                        "nickname": userid,
                        "role": "user",
                    }      
                return await call_next(request)

            if not getattr(request.state, "user_claims", None) and not is_whitelisted:
                if auth_error:
                    return await _unauthorized_response(*auth_error)
                return await _unauthorized_response(401, "未授权", "missing auth session")

        return await call_next(request)

    register_request_logging_middleware(app)

    # SessionMiddleware 必须包在鉴权中间件外层，才能在鉴权阶段读取 session claims。
    app.add_middleware(
        SessionMiddleware,
        secret_key=cfg.session_secret or cfg.jwt_key,
        session_cookie=cfg.session_cookie_name,
        same_site=cfg.session_cookie_same_site,
        https_only=cfg.session_cookie_secure,
    )

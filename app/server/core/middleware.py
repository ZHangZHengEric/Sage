"""
中间件模块
"""

import re
import uuid
from typing import Tuple

from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.middleware.sessions import SessionMiddleware

from . import config
from .context import set_request_context
from .auth import get_session_claims, parse_access_token
from .exceptions import SageHTTPException
from .render import Response

# 白名单 API 路径
WHITELIST_API_PATHS = frozenset(
    {
        "/api/health",
        "/api/system/info",
        "/api/user/login",
        "/api/user/register",
        "/api/user/auth-providers",
        "/api/user/oauth/login",
        "/api/user/oauth/login/{provider_id}",
        "/api/user/oauth/callback",
        "/api/user/oauth/callback/{provider_id}",
        "/api/observability/jaeger",
        "/api/observability/jaeger/login",
        "/api/observability/jaeger/auth",
        "/api/observability/jaeger/{full_path:path}",
        "/api/stream",
        "/api/chat",
        "/api/system/version/check",
        "/api/system/version/latest",
        "/api/share/conversations/{conversation_id}/messages",
    }
)


def _compile_whitelist_regex(paths: frozenset[str]) -> Tuple[re.Pattern, ...]:
    """将带参数的路径转换为正则"""
    return tuple(re.compile("^" + re.sub(r"\{[^}]+\}", r"[^/]+", p) + "$") for p in paths if "{" in p)


WHITELIST_API_REGEXES = _compile_whitelist_regex(WHITELIST_API_PATHS)


def _is_whitelisted(path: str) -> bool:
    """判断路径是否在白名单"""
    return path in WHITELIST_API_PATHS or any(r.match(path) for r in WHITELIST_API_REGEXES)


async def _unauthorized_response(status_code: int, detail: str, error_detail: str):
    """统一返回未授权响应"""
    return JSONResponse(
        status_code=status_code,
        content=(await Response.error(status_code, detail, error_detail)).model_dump(),
    )


def register_middlewares(app):
    cfg = config.get_startup_config()

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        path = request.url.path
        if path.startswith("/api"):
            # Internal request bypass
            internal_user_id = request.headers.get("X-Sage-Internal-UserId")
            if internal_user_id:
                client_host = request.client.host
                # Allow localhost/127.0.0.1 or same network calls
                if client_host in ("127.0.0.1", "localhost", "::1"):
                    userid = internal_user_id
                    request.state.user_claims = {"userid": userid, "username": "Internal System"}
                    return await call_next(request)
                else:
                    logger.warning(f"Blocked internal request from external IP: {client_host}")

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

            if not getattr(request.state, "user_claims", None) and not is_whitelisted:
                if auth_error:
                    return await _unauthorized_response(*auth_error)
                return await _unauthorized_response(401, "未授权", "missing auth session")

        return await call_next(request)

    @app.middleware("http")
    async def request_logging_middleware(request: Request, call_next):
        """请求日志中间件，记录请求信息和用户名称"""
        # 生成请求ID
        request_id = f"{uuid.uuid4().hex[:12]}"

        # 使用bind创建带有上下文的logger实例，避免全局状态污染
        request_logger = logger.bind(request_id=request_id)

        # 设置请求上下文到ContextVar中，确保线程安全
        set_request_context(request_id, request_logger)

        # 将request_logger存储到request.state中，供后续使用（兼容性保留）
        request.state.logger = request_logger
        request.state.request_id = request_id

        # 处理请求
        response = await call_next(request)

        return response

    # SessionMiddleware 必须包在鉴权中间件外层，才能在鉴权阶段读取 session claims。
    app.add_middleware(
        SessionMiddleware,
        secret_key=cfg.session_secret or cfg.jwt_key,
        session_cookie=cfg.session_cookie_name,
        same_site=cfg.session_cookie_same_site,
        https_only=cfg.session_cookie_secure,
    )

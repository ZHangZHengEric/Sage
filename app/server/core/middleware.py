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

from .context import set_request_context
from .auth import parse_access_token
from .config import get_startup_config
from .exceptions import SageHTTPException
from .render import Response

# 白名单 API 路径
WHITELIST_API_PATHS = frozenset(
    {
        "/api/health",
        "/api/stream/task_messages",
        "/api/user/login",
        "/api/user/register",
        "/api/stream",
        "/api/files/workspace",
        "/api/files/workspace/download",
        "/api/files/workspace/preview",
        "/api/files/logs",
        "/api/files/logs/download",
        "/api/files/logs/preview",
        "/api/conversations",
        "/api/conversations/{conversation_id}",
        "/api/conversations/{conversation_id}/messages",
        "/api/sessions/{session_id}/interrupt",
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


def _is_whitelisted(path: str) -> bool:
    """判断路径是否在白名单"""
    return path in WHITELIST_API_PATHS or any(
        r.match(path) for r in WHITELIST_API_REGEXES
    )


async def _unauthorized_response(status_code: int, detail: str, error_detail: str):
    """统一返回未授权响应"""
    return JSONResponse(
        status_code=status_code,
        content=(await Response.error(status_code, detail, error_detail)).model_dump(),
    )


def register_middlewares(app):
    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

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

    cfg = get_startup_config()
    if cfg and cfg.no_auth:
        return

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        path = request.url.path
        if path.startswith("/api") and not _is_whitelisted(path):
            auth = request.headers.get("Authorization", "")

            if not auth.lower().startswith("bearer "):
                return await _unauthorized_response(
                    401, "未授权", "missing bearer token"
                )

            token = auth.split(" ", 1)[1]
            try:
                request.state.user_claims = parse_access_token(token)
            except SageHTTPException as e:
                return await _unauthorized_response(
                    e.status_code, e.detail, e.error_detail
                )
            except Exception as e:
                return await _unauthorized_response(401, "Token非法", str(e))

        return await call_next(request)

"""
中间件模块
"""

from fastapi.middleware.cors import CORSMiddleware
from fastapi import Request
from fastapi.responses import JSONResponse
from .render import Response
from .exceptions import SageHTTPException
from service.user import parse_access_token

import config

WHITELIST_API_PATHS = frozenset(
    {
        "/api/health",
        "/api/stream",
        "/api/user/login",
        "/api/user/register",
        "/api/files/workspace",
        "/api/files/workspace/download",
        "/api/files/workspace/preview",
        "/api/files/logs",
        "/api/files/logs/download",
        "/api/files/logs/preview",
    }
)


def register_middlewares(app):
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    cfg = config.get_startup_config()
    if cfg and cfg.no_auth:
        return

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        path = request.url.path
        if path.startswith("/api") and path not in WHITELIST_API_PATHS:
            auth = request.headers.get("Authorization", "")

            if not (auth.startswith("Bearer ") or auth.startswith("bearer ")):
                return JSONResponse(
                    status_code=401,
                    content=(
                        await Response.error(401, "未授权", "missing bearer token")
                    ).model_dump(),
                )

            token = auth.split(" ", 1)[1]
            try:
                request.state.user_claims = parse_access_token(token)
            except SageHTTPException as e:
                return JSONResponse(
                    status_code=e.status_code,
                    content=(
                        await Response.error(e.status_code, e.detail, e.error_detail)
                    ).model_dump(),
                )
            except Exception as e:
                return JSONResponse(
                    status_code=401,
                    content=(
                        await Response.error(401, "Token非法", str(e))
                    ).model_dump(),
                )

        return await call_next(request)

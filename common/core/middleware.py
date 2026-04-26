from __future__ import annotations

import os
import uuid
from typing import Any

from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from common.core import config
from .context import set_request_context

# Tauri / WebView2 may send different Origin values by platform & dev vs prod.
# Keep an explicit list (fast path) plus a regex for localhost / dev server ports.
_DESKTOP_CORS_ALLOW_ORIGINS = (
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
)
# fullmatch: Starlette CORSMiddleware uses re.fullmatch on the Origin header.
_DESKTOP_CORS_ORIGIN_REGEX = (
    r"^https?://(localhost|127\.0\.0\.1|tauri\.localhost)(:\d+)?$"
    r"|^tauri://.+$"
    r"|^chrome-extension://.+$"
)


def _get_config() -> config.StartupConfig:
    cfg = config.get_startup_config()
    if cfg is None:
        raise RuntimeError("Startup config is not initialized.")
    return cfg


def register_cors_middleware(app: Any) -> None:
    """注册跨端共享的 CORS 策略。"""
    cfg = _get_config()

    # Prefer StartupConfig; SAGE_INTERNAL_DESKTOP_PROCESS is set by app.desktop.core.main
    # so the sidecar never falls through to server CORS (empty allow_origins) if cfg drifts.
    is_desktop = (cfg.app_mode == "desktop") or (
        os.environ.get("SAGE_INTERNAL_DESKTOP_PROCESS") == "1"
    )

    if is_desktop:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(_DESKTOP_CORS_ALLOW_ORIGINS),
            allow_origin_regex=_DESKTOP_CORS_ORIGIN_REGEX,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        return

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_allowed_origins or [],
        allow_credentials=cfg.cors_allow_credentials,
        allow_methods=cfg.cors_allow_methods or ["*"],
        allow_headers=cfg.cors_allow_headers or ["*"],
        expose_headers=cfg.cors_expose_headers or [],
        max_age=int(cfg.cors_max_age or 600),
    )


def register_request_logging_middleware(app: Any) -> None:
    """注册请求上下文与 request_id 注入中间件。"""

    @app.middleware("http")
    async def request_logging_middleware(request: Request, call_next):
        request_id = uuid.uuid4().hex[:12]
        request_logger = logger.bind(request_id=request_id)

        set_request_context(request_id, request_logger)
        request.state.logger = request_logger
        request.state.request_id = request_id

        return await call_next(request)


__all__ = ["register_cors_middleware", "register_request_logging_middleware"]

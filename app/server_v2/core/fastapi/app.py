from __future__ import annotations

from fastapi import FastAPI

from app.server_v2.core.http.exceptions import register_exception_handlers


def install_core_exception_handlers(app: FastAPI) -> None:
    register_exception_handlers(app)

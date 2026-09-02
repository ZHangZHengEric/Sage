from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError

from app.server_v2.core.errors import ServerV2Error, error_response
from app.server_v2.core.failures import DependencyUnavailableError


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ServerV2Error)
    async def handle_server_error(_request: Request, error: ServerV2Error):
        return error_response(
            status_code=error.status_code,
            message=error.message,
            detail=error.detail,
        )

    @app.exception_handler(HTTPException)
    async def handle_http_error(_request: Request, error: HTTPException):
        detail = error.detail
        message = detail if isinstance(detail, str) else str(detail)
        return error_response(status_code=error.status_code, message=message)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, error: RequestValidationError
    ):
        return error_response(
            status_code=422,
            message="invalid request",
            detail="request validation failed",
        )

    @app.exception_handler(DependencyUnavailableError)
    async def handle_dependency_unavailable(
        _request: Request, error: DependencyUnavailableError
    ):
        return error_response(
            status_code=503,
            message="dependency is temporarily unavailable",
            detail=error.dependency,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_request: Request, error: Exception):
        from loguru import logger

        logger.opt(exception=error).error("unhandled application exception")
        return error_response(
            status_code=500,
            message="internal server error",
        )

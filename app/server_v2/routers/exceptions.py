from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError

from sagents.v2.contracts.errors import SageV2Error
from app.server_v2.routers.render import (
    detail_for_error,
    error_response,
    status_for_error,
)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(SageV2Error)
    async def handle_sage_error(_request: Request, error: SageV2Error):
        return error_response(
            status_code=status_for_error(error.info),
            message=error.info.message,
            detail=detail_for_error(error.info),
        )

    @app.exception_handler(HTTPException)
    async def handle_http_error(_request: Request, error: HTTPException):
        detail = error.detail
        message = detail if isinstance(detail, str) else str(detail)
        return error_response(status_code=error.status_code, message=message)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_request: Request, error: RequestValidationError):
        return error_response(
            status_code=422,
            message="invalid request",
            detail="request validation failed",
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_request: Request, error: Exception):
        from app.server_v2.observability.logging import get_logger

        get_logger(__name__).exception(
            "http.unhandled_exception", "unhandled application exception", error
        )
        return error_response(
            status_code=500,
            message="internal server error",
        )

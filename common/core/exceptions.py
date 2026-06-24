"""
全局异常定义
"""

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from loguru import logger

from common.core.i18n import locale_from_request, t, translate_if_key
from common.core.render import Response


class SageHTTPException(HTTPException):
    """自定义 HTTP 异常，支持更多错误信息。"""

    def __init__(
        self,
        status_code: int = 500,
        detail: str = "Internal Server Error",
        error_detail: str = "",
        message_key: str | None = None,
        message_params: dict | None = None,
    ):
        if message_key and detail == "Internal Server Error":
            detail = t(message_key, locale=None, params=message_params)
        super().__init__(status_code=status_code, detail=detail)
        self.error_detail = error_detail
        self.message_key = message_key
        self.message_params = message_params or {}


def register_exception_handlers(app):
    async def handle_sage(request: Request, exc: SageHTTPException):
        locale = locale_from_request(request)
        message = (
            t(exc.message_key, locale=locale, params=exc.message_params)
            if exc.message_key
            else translate_if_key(str(exc.detail), locale=locale)
        )
        resp = await Response.error(
            code=exc.status_code, message=message, error_detail=exc.error_detail
        )
        return JSONResponse(status_code=exc.status_code, content=resp.model_dump())

    async def handle_http(request: Request, exc: HTTPException):
        locale = locale_from_request(request)
        resp = await Response.error(
            code=exc.status_code, message=translate_if_key(str(exc.detail), locale)
        )
        return JSONResponse(status_code=exc.status_code, content=resp.model_dump())

    async def handle_general(request: Request, exc: Exception):
        logger.error(f"未处理异常: {exc}")
        locale = locale_from_request(request)
        resp = await Response.error(
            code=500, message=t("error.internal_server", locale), error_detail=str(exc)
        )
        return JSONResponse(status_code=500, content=resp.model_dump())

    app.add_exception_handler(SageHTTPException, handle_sage)
    app.add_exception_handler(HTTPException, handle_http)
    app.add_exception_handler(Exception, handle_general)

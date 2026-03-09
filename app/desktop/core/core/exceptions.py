"""
全局异常定义
"""

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from loguru import logger

from .render import Response


class SageHTTPException(HTTPException):
    """自定义HTTP异常，支持更多错误信息"""

    def __init__(self, status_code: int, detail: str, error_detail: str = None):
        super().__init__(status_code=status_code, detail=detail)
        self.error_detail = error_detail


def register_exception_handlers(app):
    async def handle_sage(request: Request, exc: SageHTTPException):
        resp = await Response.error(exc.status_code, exc.detail, exc.error_detail)
        return JSONResponse(status_code=exc.status_code, content=resp.model_dump())

    async def handle_http(request: Request, exc: HTTPException):
        resp = await Response.error(exc.status_code, exc.detail)
        return JSONResponse(status_code=exc.status_code, content=resp.model_dump())

    async def handle_general(request: Request, exc: Exception):
        logger.error(f"未处理异常: {exc}")
        resp = await Response.error(500, "内部服务器错误", str(exc))
        return JSONResponse(status_code=500, content=resp.model_dump())

    app.add_exception_handler(SageHTTPException, handle_sage)
    app.add_exception_handler(HTTPException, handle_http)
    app.add_exception_handler(Exception, handle_general)

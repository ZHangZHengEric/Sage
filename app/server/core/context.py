from contextvars import ContextVar
from typing import Optional

# 使用ContextVar来存储请求上下文，确保线程安全
request_context: ContextVar[Optional[dict]] = ContextVar("request_context", default=None)


def set_request_context(request_id: str, request_logger):
    """设置请求上下文"""
    context = {"request_id": request_id, "logger": request_logger}
    request_context.set(context)


def get_request_id() -> str:
    """获取当前请求ID"""
    context = request_context.get()
    if context:
        return context.get("request_id", "background")
    return "background"

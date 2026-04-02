from contextvars import ContextVar
from typing import Any, Optional

# 使用 ContextVar 存储请求上下文，确保异步请求隔离。
request_context: ContextVar[Optional[dict[str, Any]]] = ContextVar("request_context", default=None)


def set_request_context(request_id: str, request_logger: Any) -> None:
    """设置当前请求上下文。"""
    request_context.set({"request_id": request_id, "logger": request_logger})


def get_request_id() -> str:
    """获取当前请求 ID。"""
    context = request_context.get()
    if context:
        return context.get("request_id", "background")
    return "background"


__all__ = ["request_context", "set_request_context", "get_request_id"]

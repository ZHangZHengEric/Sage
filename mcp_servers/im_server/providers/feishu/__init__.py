"""Feishu (Lark) provider package."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .websocket import FeishuWebSocketClient as FeishuWebSocketClient

from .provider import FeishuProvider

__all__ = [
    "FeishuProvider",
    "FeishuWebSocketClient",
]


def __getattr__(name: str):
    if name == "FeishuWebSocketClient":
        from .websocket import FeishuWebSocketClient

        return FeishuWebSocketClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

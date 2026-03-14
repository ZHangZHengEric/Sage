"""WeChat Work (企业微信) provider package.

企业微信智能机器人长连接模式 Provider
"""

from .provider import WeChatWorkProvider
from .websocket_client import WeChatWorkWebSocketClient

__all__ = [
    "WeChatWorkProvider",
    "WeChatWorkWebSocketClient",
]

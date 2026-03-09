"""IM Providers module."""

from .base import IMProviderBase

# Feishu provider
try:
    from .feishu import FeishuProvider
    FEISHU_AVAILABLE = True
except ImportError:
    FEISHU_AVAILABLE = False

# DingTalk provider
try:
    from .dingtalk import DingTalkProvider
    DINGTALK_AVAILABLE = True
except ImportError:
    DINGTALK_AVAILABLE = False

# iMessage is only available on macOS
try:
    import platform
    if platform.system() == "Darwin":
        from .imessage import iMessageProvider
        IMESSAGE_AVAILABLE = True
    else:
        IMESSAGE_AVAILABLE = False
except ImportError:
    IMESSAGE_AVAILABLE = False

__all__ = [
    "IMProviderBase",
]

if FEISHU_AVAILABLE:
    __all__.append("FeishuProvider")

if DINGTALK_AVAILABLE:
    __all__.append("DingTalkProvider")

if IMESSAGE_AVAILABLE:
    __all__.append("iMessageProvider")

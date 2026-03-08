"""iMessage provider package for macOS."""

from .provider import iMessageProvider
from .listener import iMessageNotificationListener, iMessageDatabasePoller
from .manager import iMessageManager, get_imessage_manager

__all__ = [
    "iMessageProvider",
    "iMessageNotificationListener",
    "iMessageDatabasePoller",
    "iMessageManager",
    "get_imessage_manager",
]
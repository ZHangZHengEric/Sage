"""DingTalk provider package."""

from .provider import DingTalkProvider

__all__ = [
    "DingTalkProvider",
    "DingTalkStreamClient",
]


def __getattr__(name: str):
    if name == "DingTalkStreamClient":
        from .stream import DingTalkStreamClient

        return DingTalkStreamClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

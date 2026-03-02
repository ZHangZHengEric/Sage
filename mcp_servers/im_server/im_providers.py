"""Factory for IM providers."""

import platform
from typing import Dict, Any

from .providers.base import IMProviderBase
from .providers.feishu import FeishuProvider
from .providers.dingtalk import DingTalkProvider
from .providers.wechat_work import WeChatWorkProvider

# iMessage is only available on macOS
if platform.system() == "Darwin":
    try:
        from .providers.imessage import iMessageProvider
        IMESSAGE_AVAILABLE = True
    except ImportError:
        IMESSAGE_AVAILABLE = False
else:
    IMESSAGE_AVAILABLE = False


PROVIDER_MAP: Dict[str, type] = {
    "feishu": FeishuProvider,
    "dingtalk": DingTalkProvider,
    "wechat_work": WeChatWorkProvider,
}

# Add iMessage if available
if IMESSAGE_AVAILABLE:
    PROVIDER_MAP["imessage"] = iMessageProvider


def get_im_provider(provider_type: str, config: Dict[str, Any]) -> IMProviderBase:
    """Factory function to get IM provider instance."""
    provider_class = PROVIDER_MAP.get(provider_type.lower())
    if not provider_class:
        raise ValueError(f"Unsupported IM provider: {provider_type}")

    return provider_class(config)


def list_supported_providers() -> list:
    """List all supported IM providers."""
    return list(PROVIDER_MAP.keys())

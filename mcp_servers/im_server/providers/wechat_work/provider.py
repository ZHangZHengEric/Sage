"""WeChat Work provider (placeholder - not implemented yet)."""

import logging
from typing import Dict, Any, Optional

from ..base import IMProviderBase

logger = logging.getLogger("WeChatWorkProvider")


class WeChatWorkProvider(IMProviderBase):
    """WeChat Work provider - not implemented yet."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.enabled = config.get("enabled", False)
        logger.warning("WeChat Work provider is not implemented yet")

    async def send_message(
        self,
        content: str,
        chat_id: Optional[str] = None,
        user_id: Optional[str] = None,
        msg_type: str = "text"
    ) -> bool:
        """Send message - not implemented."""
        logger.error("WeChat Work send_message is not implemented")
        return False

    async def get_user_info(self, user_id: str) -> Dict[str, Any]:
        """Get user info - not implemented."""
        logger.error("WeChat Work get_user_info is not implemented")
        return {}

    def health_check(self) -> Dict[str, Any]:
        """Health check - not implemented."""
        return {
            "status": "not_implemented",
            "message": "WeChat Work provider is not implemented yet"
        }

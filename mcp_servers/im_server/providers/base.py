"""Base class for IM providers."""

from typing import Optional, Dict, Any
from abc import ABC, abstractmethod


class IMProviderBase(ABC):
    """Base class for IM providers."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config

    @abstractmethod
    async def send_message(
        self,
        content: str,
        chat_id: Optional[str] = None,
        user_id: Optional[str] = None,
        msg_type: str = "text",
    ) -> Dict[str, Any]:
        """Send a message to the IM platform."""
        pass

    @abstractmethod
    async def verify_webhook(self, request_body: bytes, signature: str) -> bool:
        """Verify webhook request signature."""
        pass

    @abstractmethod
    def parse_incoming_message(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Parse incoming message from webhook."""
        pass

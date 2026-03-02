"""DingTalk IM provider."""

import hmac
import hashlib
import base64
import time
from typing import Optional, Dict, Any

import httpx

from .base import IMProviderBase


class DingTalkProvider(IMProviderBase):
    """DingTalk IM provider."""

    BASE_URL = "https://oapi.dingtalk.com"
    PROVIDER_NAME = "dingtalk"

    def _generate_sign(self, timestamp: str, secret: str) -> str:
        """Generate DingTalk signature."""
        string_to_sign = f"{timestamp}\n{secret}"
        hmac_code = hmac.new(
            secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        return base64.b64encode(hmac_code).decode("utf-8")

    async def send_message(
        self,
        content: str,
        chat_id: Optional[str] = None,
        user_id: Optional[str] = None,
        msg_type: str = "text",
    ) -> Dict[str, Any]:
        """Send message via DingTalk."""
        webhook_url = self.config.get("webhook_url")
        if not webhook_url:
            return {"success": False, "error": "No webhook_url configured"}

        timestamp = str(round(time.time() * 1000))
        secret = self.config.get("app_secret", "")

        if msg_type == "text":
            payload = {"msgtype": "text", "text": {"content": content}}
        elif msg_type == "markdown":
            payload = {
                "msgtype": "markdown",
                "markdown": {"title": "Message", "text": content},
            }
        else:
            payload = {"msgtype": "text", "text": {"content": content}}

        # Add signature
        if secret:
            sign = self._generate_sign(timestamp, secret)
            payload["timestamp"] = timestamp
            payload["sign"] = sign

        async with httpx.AsyncClient() as client:
            resp = await client.post(webhook_url, json=payload)
            data = resp.json()
            if data.get("errcode") == 0:
                return {"success": True}
            return {"success": False, "error": data.get("errmsg", "Unknown error")}

    async def verify_webhook(self, request_body: bytes, signature: str) -> bool:
        """Verify DingTalk webhook signature."""
        app_secret = self.config.get("app_secret", "")
        if not app_secret:
            return True

        expected_sign = hmac.new(
            app_secret.encode("utf-8"),
            request_body,
            digestmod=hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected_sign, signature)

    def parse_incoming_message(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Parse DingTalk incoming message."""
        # Handle different message types
        msg_type = data.get("msgtype")
        if not msg_type:
            return None

        content = ""
        if msg_type == "text":
            content = data.get("text", {}).get("content", "")
        elif msg_type == "markdown":
            content = data.get("markdown", {}).get("text", "")

        return {
            "type": "message",
            "content": content,
            "chat_id": data.get("conversationId"),
            "user_id": data.get("senderStaffId"),
            "user_name": data.get("senderNick"),
            "msg_type": msg_type,
            "provider": self.PROVIDER_NAME,
        }

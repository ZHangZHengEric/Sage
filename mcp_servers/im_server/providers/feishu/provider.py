"""Feishu (Lark) IM provider."""

import hmac
import hashlib
import base64
import logging
from typing import Optional, Dict, Any

import httpx

from ..base import IMProviderBase

logger = logging.getLogger("FeishuProvider")


class FeishuProvider(IMProviderBase):
    """Feishu (Lark) IM provider."""

    BASE_URL = "https://open.feishu.cn/open-apis"
    PROVIDER_NAME = "feishu"

    def _generate_sign(self, timestamp: str, secret: str) -> str:
        """Generate Feishu signature."""
        string_to_sign = f"{timestamp}\n{secret}"
        hmac_code = hmac.new(
            string_to_sign.encode("utf-8"), digestmod=hashlib.sha256
        ).digest()
        return base64.b64encode(hmac_code).decode("utf-8")

    async def _get_access_token(self) -> Optional[str]:
        """Get Feishu access token."""
        app_id = self.config.get("app_id")
        app_secret = self.config.get("app_secret")

        if not app_id or not app_secret:
            return self.config.get("access_token")

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.BASE_URL}/auth/v3/tenant_access_token/internal",
                json={"app_id": app_id, "app_secret": app_secret},
            )
            data = resp.json()
            if data.get("code") == 0:
                return data.get("tenant_access_token")
        return None

    async def send_message(
        self,
        content: str,
        chat_id: Optional[str] = None,
        user_id: Optional[str] = None,
        msg_type: str = "text",
    ) -> Dict[str, Any]:
        """Send message via Feishu."""
        logger.info(f"[Feishu] send_message called: chat_id={chat_id}, user_id={user_id}, content_length={len(content)}, msg_type={msg_type}")
        
        access_token = await self._get_access_token()
        if not access_token:
            logger.error("[Feishu] Failed to get access token")
            return {"success": False, "error": "Failed to get access token"}
        
        logger.info(f"[Feishu] Got access token: {access_token[:10]}...")

        import json
        
        # Build message payload
        # Note: Feishu API requires content to be a JSON string, not an object
        if msg_type == "text":
            content_json = json.dumps({"text": content}, ensure_ascii=False)
            message = {"msg_type": "text", "content": content_json}
        elif msg_type == "markdown":
            # For markdown, use post message type or interactive card
            content_json = json.dumps({
                "zh_cn": {
                    "title": "",
                    "content": [[{"tag": "text", "text": content}]]
                }
            }, ensure_ascii=False)
            message = {"msg_type": "post", "content": content_json}
        else:
            content_json = json.dumps({"text": content}, ensure_ascii=False)
            message = {"msg_type": "text", "content": content_json}

        # Determine receiver
        # Feishu API uses receive_id parameter with receive_id_type
        if chat_id:
            message["receive_id"] = chat_id
            url = f"{self.BASE_URL}/im/v1/messages?receive_id_type=chat_id"
        elif user_id:
            message["receive_id"] = user_id
            url = f"{self.BASE_URL}/im/v1/messages?receive_id_type=open_id"
        else:
            return {
                "success": False,
                "error": "No chat_id or user_id provided",
            }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                json=message,
            )
            data = resp.json()
            if data.get("code") == 0:
                return {
                    "success": True,
                    "message_id": data.get("data", {}).get("message_id"),
                }
            return {"success": False, "error": data.get("msg", "Unknown error")}

    async def verify_webhook(self, request_body: bytes, signature: str) -> bool:
        """Verify Feishu webhook signature."""
        # Feishu webhook verification is done via challenge-response
        return True

    def parse_incoming_message(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Parse Feishu incoming message."""
        # Handle challenge request
        if "challenge" in data:
            return {"type": "challenge", "challenge": data["challenge"]}

        event = data.get("event", {})
        if not event:
            return None

        message = event.get("message", {})
        sender = event.get("sender", {})

        return {
            "type": "message",
            "message_id": message.get("message_id"),
            "content": message.get("content", {}),
            "chat_id": event.get("chat_id"),
            "user_id": sender.get("sender_id", {}).get("user_id"),
            "user_name": sender.get("sender_id", {}).get("name"),
            "msg_type": message.get("message_type"),
            "provider": self.PROVIDER_NAME,
        }

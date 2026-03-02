"""DingTalk IM provider."""

import hmac
import hashlib
import base64
import json
import time
from typing import Optional, Dict, Any

import httpx

from ..base import IMProviderBase


class DingTalkProvider(IMProviderBase):
    """DingTalk IM provider."""

    BASE_URL = "https://oapi.dingtalk.com"
    API_URL = "https://api.dingtalk.com"
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

    async def _get_access_token(self) -> Optional[str]:
        """Get DingTalk access token using app_key and app_secret."""
        app_key = self.config.get("app_key") or self.config.get("client_id")
        app_secret = self.config.get("app_secret") or self.config.get("client_secret")

        if not app_key or not app_secret:
            return None

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.BASE_URL}/gettoken",
                params={"appkey": app_key, "appsecret": app_secret},
            )
            data = resp.json()
            if data.get("errcode") == 0:
                return data.get("access_token")
        return None

    async def send_message(
        self,
        content: str,
        chat_id: Optional[str] = None,
        user_id: Optional[str] = None,
        msg_type: str = "text",
    ) -> Dict[str, Any]:
        """Send message via DingTalk."""
        # Try webhook first (if configured)
        webhook_url = self.config.get("webhook_url")
        if webhook_url:
            return await self._send_webhook(webhook_url, content, msg_type)

        # Otherwise use API
        access_token = await self._get_access_token()
        if not access_token:
            return {"success": False, "error": "Failed to get access token. Check app_key and app_secret."}

        # Build message payload
        if msg_type == "text":
            msg = {"msgtype": "text", "text": {"content": content}}
        elif msg_type == "markdown":
            msg = {
                "msgtype": "markdown",
                "markdown": {"title": "Message", "text": content},
            }
        else:
            msg = {"msgtype": "text", "text": {"content": content}}

        # Send to specific user or chat
        if user_id:
            # Send to user via API
            url = f"{self.API_URL}/v1.0/robot/oToMessages/batchSend"
            payload = {
                "robotCode": self.config.get("app_key") or self.config.get("client_id"),
                "userIds": [user_id],
                "msgKey": "sampleText",
                "msgParam": json.dumps(msg["text"]) if msg_type == "text" else json.dumps(msg["markdown"])
            }
        elif chat_id:
            # Send to group chat
            url = f"{self.API_URL}/v1.0/robot/groupMessages/send"
            payload = {
                "robotCode": self.config.get("app_key") or self.config.get("client_id"),
                "openConversationId": chat_id,
                "msgKey": "sampleText",
                "msgParam": json.dumps(msg["text"]) if msg_type == "text" else json.dumps(msg["markdown"])
            }
        else:
            return {"success": False, "error": "No user_id or chat_id provided"}

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                headers={"x-acs-dingtalk-access-token": access_token},
                json=payload
            )
            data = resp.json()
            if data.get("code") == "0" or data.get("success"):
                return {"success": True, "message_id": data.get("data", {}).get("processQueryKey")}
            return {"success": False, "error": data.get("message", "Unknown error")}

    async def _send_webhook(self, webhook_url: str, content: str, msg_type: str) -> Dict[str, Any]:
        """Send message via webhook (legacy mode)."""
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

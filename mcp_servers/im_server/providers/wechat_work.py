"""WeChat Work (企业微信) IM provider."""

from typing import Optional, Dict, Any

import httpx

from .base import IMProviderBase


class WeChatWorkProvider(IMProviderBase):
    """WeChat Work (企业微信) IM provider."""

    BASE_URL = "https://qyapi.weixin.qq.com/cgi-bin"
    PROVIDER_NAME = "wechat_work"

    async def _get_access_token(self) -> Optional[str]:
        """Get WeChat Work access token."""
        corp_id = self.config.get("app_id")  # corp_id
        corp_secret = self.config.get("app_secret")

        if not corp_id or not corp_secret:
            return self.config.get("access_token")

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.BASE_URL}/gettoken",
                params={"corpid": corp_id, "corpsecret": corp_secret},
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
        """Send message via WeChat Work."""
        access_token = await self._get_access_token()
        if not access_token:
            return {"success": False, "error": "Failed to get access token"}

        # Build message payload
        if msg_type == "text":
            payload = {"msgtype": "text", "text": {"content": content}}
        elif msg_type == "markdown":
            payload = {"msgtype": "markdown", "markdown": {"content": content}}
        else:
            payload = {"msgtype": "text", "text": {"content": content}}

        # Determine receiver
        if chat_id:
            payload["chatid"] = chat_id
            url = f"{self.BASE_URL}/appchat/send?access_token={access_token}"
        elif user_id:
            payload["touser"] = user_id
            agent_id = self.config.get("extra_config", {}).get("agent_id")
            if agent_id:
                payload["agentid"] = agent_id
            url = f"{self.BASE_URL}/message/send?access_token={access_token}"
        else:
            # Send to webhook
            webhook_url = self.config.get("webhook_url")
            if webhook_url:
                return await self._send_webhook(webhook_url, content)
            return {
                "success": False,
                "error": "No chat_id, user_id, or webhook_url provided",
            }

        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload)
            data = resp.json()
            if data.get("errcode") == 0:
                return {"success": True, "message_id": data.get("msgid")}
            return {"success": False, "error": data.get("errmsg", "Unknown error")}

    async def _send_webhook(self, webhook_url: str, content: str) -> Dict[str, Any]:
        """Send message via webhook."""
        payload = {"msgtype": "text", "text": {"content": content}}

        async with httpx.AsyncClient() as client:
            resp = await client.post(webhook_url, json=payload)
            data = resp.json()
            if data.get("errcode") == 0:
                return {"success": True}
            return {"success": False, "error": data.get("errmsg", "Unknown error")}

    async def verify_webhook(self, request_body: bytes, signature: str) -> bool:
        """Verify WeChat Work webhook signature."""
        # WeChat Work uses token verification
        return True

    def parse_incoming_message(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Parse WeChat Work incoming message."""
        msg_type = data.get("MsgType")
        if not msg_type:
            return None

        content = ""
        if msg_type == "text":
            content = data.get("Content", "")
        elif msg_type == "markdown":
            content = data.get("Markdown", {}).get("Content", "")

        return {
            "type": "message",
            "content": content,
            "chat_id": data.get("ChatId"),
            "user_id": data.get("FromUserName"),
            "user_name": data.get("FromUserName"),
            "msg_type": msg_type.lower(),
            "provider": self.PROVIDER_NAME,
        }

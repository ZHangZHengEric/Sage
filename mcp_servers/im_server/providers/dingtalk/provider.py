"""DingTalk IM provider."""

import hmac
import hashlib
import base64
import json
import time
import logging
from typing import Optional, Dict, Any

import httpx

from ..base import IMProviderBase

logger = logging.getLogger("DingTalkProvider")


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

        logger.info(f"[DingTalk] Getting access token: app_key={app_key}, has_secret={bool(app_secret)}")

        if not app_key or not app_secret:
            logger.error("[DingTalk] Missing app_key or app_secret in config")
            return None

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self.BASE_URL}/gettoken",
                    params={"appkey": app_key, "appsecret": app_secret},
                )
                data = resp.json()
                logger.info(f"[DingTalk] gettoken response: {data}")
                if data.get("errcode") == 0:
                    return data.get("access_token")
                else:
                    logger.error(f"[DingTalk] gettoken failed: errcode={data.get('errcode')}, errmsg={data.get('errmsg')}")
        except Exception as e:
            logger.error(f"[DingTalk] gettoken exception: {e}", exc_info=True)
        return None

    async def send_message(
        self,
        content: str,
        chat_id: Optional[str] = None,
        user_id: Optional[str] = None,
        msg_type: str = "markdown",
        session_webhook: Optional[str] = None,
        sender_staff_id: Optional[str] = None,
        session_webhook_expired_time: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Send message via DingTalk.
        
        Args:
            content: Message content
            chat_id: Chat/Group ID (optional)
            user_id: User ID (optional)
            msg_type: Message type (text or markdown)
            session_webhook: Webhook URL from incoming message (preferred method)
            sender_staff_id: Sender's staff ID for @ mention
        """
        logger.info(f"[DingTalk] send_message called: chat_id={chat_id}, user_id={user_id}, content_length={len(content)}")
        
        # Use session_webhook if available (simplest method, no access token needed)
        if session_webhook:
            logger.info(f"[DingTalk] Using session_webhook: {session_webhook[:50]}...")
            # Default to markdown for better formatting
            actual_msg_type = msg_type or "markdown"
            return await self._send_via_session_webhook(
                session_webhook, content, actual_msg_type, sender_staff_id,
                session_webhook_expired_time=session_webhook_expired_time
            )
        
        # Try configured webhook (legacy mode)
        webhook_url = self.config.get("webhook_url")
        if webhook_url:
            logger.info(f"[DingTalk] Using configured webhook: {webhook_url}")
            return await self._send_webhook(webhook_url, content, msg_type)

        # Otherwise use API (requires access token)
        logger.info("[DingTalk] Using API to send message")
        access_token = await self._get_access_token()
        if not access_token:
            logger.error("[DingTalk] Failed to get access token")
            return {"success": False, "error": "Failed to get access token. Check app_key and app_secret."}
        
        logger.info(f"[DingTalk] Got access token: {access_token[:10]}...")

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

    async def _send_via_session_webhook(
        self, 
        session_webhook: str, 
        content: str, 
        msg_type: str,
        sender_staff_id: Optional[str] = None,
        session_webhook_expired_time: Optional[int] = None
    ) -> Dict[str, Any]:
        """Send message via session webhook (from incoming message).
        
        This is the simplest method - no access token needed.
        Note: session_webhook can be used multiple times until expired.
        """
        import time
        
        # Check if webhook is expired
        if session_webhook_expired_time:
            now_ms = int(time.time() * 1000)
            if now_ms >= session_webhook_expired_time:
                logger.warning(f"[DingTalk] session_webhook expired at {session_webhook_expired_time}, now={now_ms}")
                return {"success": False, "error": "Session webhook expired"}
            else:
                remaining_ms = session_webhook_expired_time - now_ms
                logger.info(f"[DingTalk] session_webhook valid, remaining={remaining_ms/1000:.0f}s")
        
        logger.info(f"[DingTalk] Sending via session_webhook, msg_type={msg_type}")
        
        if msg_type == "text":
            payload = {
                "msgtype": "text", 
                "text": {"content": content},
            }
        elif msg_type == "markdown":
            payload = {
                "msgtype": "markdown",
                "markdown": {"title": "Message", "text": content},
            }
        else:
            payload = {
                "msgtype": "text", 
                "text": {"content": content},
            }
        
        # @ the sender if staff_id is available
        if sender_staff_id:
            payload["at"] = {"atUserIds": [sender_staff_id]}
        
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    session_webhook, 
                    json=payload,
                    headers={"Content-Type": "application/json"}
                )
                data = resp.json()
                logger.info(f"[DingTalk] session_webhook response: {data}")
                
                if data.get("errcode") == 0:
                    return {"success": True}
                return {"success": False, "error": data.get("errmsg", "Unknown error")}
        except Exception as e:
            logger.error(f"[DingTalk] session_webhook failed: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

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

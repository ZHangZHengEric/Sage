"""WeChat Personal (iLink) provider for Sage.

Based on iLink Bot API, uses HTTP long polling to receive messages.
"""

import asyncio
import base64
import logging
import secrets
import threading
import time
import uuid
from typing import Callable, Dict, Any, Optional

import httpx

from ..base import IMProviderBase

logger = logging.getLogger("WeChatPersonalProvider")


class WeChatPersonalPoller:
    """Poll iLink API for new messages from WeChat Personal."""

    def __init__(
        self,
        message_handler: Callable[[Dict[str, Any]], None],
        bot_token: str,
        base_url: str = "https://ilinkai.weixin.qq.com"
    ):
        self.message_handler = message_handler
        self.bot_token = bot_token
        self.base_url = base_url
        self.running = False
        self.poller_thread: Optional[threading.Thread] = None
        self._get_updates_buf = ""  # Message cursor

    def _random_wechat_uin(self) -> str:
        """Generate random X-WECHAT-UIN."""
        uint32 = secrets.randbits(32)
        return base64.b64encode(str(uint32).encode()).decode()

    def _build_headers(self) -> Dict[str, str]:
        """Build request headers."""
        return {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "Authorization": f"Bearer {self.bot_token}",
            "X-WECHAT-UIN": self._random_wechat_uin(),
        }

    def start(self):
        """Start polling for messages."""
        if self.running:
            return

        self.running = True
        self.poller_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.poller_thread.start()
        logger.info("[WeChatPersonal] Poller started")

    def stop(self):
        """Stop polling."""
        self.running = False
        logger.info("[WeChatPersonal] Poller stopped")

    def _poll_loop(self):
        """Main polling loop."""
        logger.info("[WeChatPersonal] Starting poll loop")

        while self.running:
            try:
                # Run async poll in sync context
                asyncio.run(self._async_poll())
            except Exception as e:
                logger.error(f"[WeChatPersonal] Poll error: {e}")
                time.sleep(3)  # Wait before retry

    async def _async_poll(self):
        """Async poll for messages."""
        try:
            async with httpx.AsyncClient(timeout=38.0) as client:
                payload = {
                    "get_updates_buf": self._get_updates_buf,
                    "base_info": {"channel_version": "1.0.2"}
                }

                response = await client.post(
                    f"{self.base_url}/ilink/bot/getupdates",
                    headers=self._build_headers(),
                    json=payload
                )

                if response.status_code == 200:
                    data = response.json()

                    # Update cursor (may be present even if ret != 0)
                    if "get_updates_buf" in data:
                        self._get_updates_buf = data["get_updates_buf"]

                    # Process messages (check msgs regardless of ret value)
                    msgs = data.get("msgs", [])
                    if msgs:
                        logger.info(f"[WeChatPersonal] Received {len(msgs)} messages")
                        for msg in msgs:
                            self._handle_message(msg)
                    
                    # Log API errors but don't stop processing
                    if data.get("ret") != 0:
                        logger.debug(f"[WeChatPersonal] API ret={data.get('ret')}, but messages may still be present")
                else:
                    logger.error(f"[WeChatPersonal] HTTP error: {response.status_code}")

        except httpx.TimeoutException:
            # Long polling timeout is normal
            pass
        except Exception as e:
            logger.error(f"[WeChatPersonal] Async poll error: {e}")

    def _handle_message(self, msg: Dict[str, Any]):
        """Handle incoming message."""
        try:
            # Only process user messages (message_type = 1)
            if msg.get("message_type") != 1:
                return

            # Extract text content
            text = ""
            item_list = msg.get("item_list", [])
            if item_list:
                item = item_list[0]
                if item.get("type") == 1:  # Text
                    text = item.get("text_item", {}).get("text", "")

            if not text:
                return

            # Create standardized message format
            message_data = {
                "user_id": msg.get("from_user_id"),
                "sender": msg.get("from_user_id"),  # For compatibility
                "content": text,
                "chat_id": msg.get("context_token"),
                "context_token": msg.get("context_token"),
                "timestamp": msg.get("create_time"),
                "provider": "wechat_personal",
                "raw_message": msg
            }

            logger.info(f"[WeChatPersonal] New message from {message_data['user_id']}: {text[:50]}...")

            # Handle async message handler in a separate thread with its own event loop
            def run_async_handler():
                try:
                    asyncio.run(self.message_handler(message_data))
                except Exception as e:
                    logger.error(f"[WeChatPersonal] Handler error: {e}")
            
            threading.Thread(target=run_async_handler, daemon=True).start()

        except Exception as e:
            logger.error(f"[WeChatPersonal] Error handling message: {e}", exc_info=True)


class WeChatPersonalProvider(IMProviderBase):
    """WeChat Personal (iLink) Provider for sending messages."""

    PROVIDER_NAME = "wechat_personal"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.bot_token = config.get("bot_token", "")
        self.bot_id = config.get("bot_id", "")
        self.base_url = config.get("base_url", "https://ilinkai.weixin.qq.com")
        self.enabled = config.get("enabled", False)

    def _random_wechat_uin(self) -> str:
        """Generate random X-WECHAT-UIN."""
        uint32 = secrets.randbits(32)
        return base64.b64encode(str(uint32).encode()).decode()

    def _build_headers(self) -> Dict[str, str]:
        """Build request headers."""
        return {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "Authorization": f"Bearer {self.bot_token}",
            "X-WECHAT-UIN": self._random_wechat_uin(),
        }

    async def send_message(
        self,
        content: str,
        chat_id: Optional[str] = None,
        user_id: Optional[str] = None,
        msg_type: str = "text",
    ) -> Dict[str, Any]:
        """Send message via iLink API.
        
        Args:
            content: Message content
            chat_id: Context token (required for iLink)
            user_id: Recipient user ID
            msg_type: Message type (text)
            
        Returns:
            Send result
        """
        if not chat_id:
            return {"success": False, "error": "chat_id (context_token) is required"}
        
        if not user_id:
            return {"success": False, "error": "user_id is required"}

        try:
            client_id = f"msg-{uuid.uuid4()}"
            
            payload = {
                "msg": {
                    "from_user_id": "",  # Let system fill this
                    "to_user_id": user_id,
                    "client_id": client_id,
                    "message_type": 2,  # BOT message
                    "message_state": 2,  # FINISH
                    "context_token": chat_id,  # Required!
                    "item_list": [{
                        "type": 1,  # Text
                        "text_item": {"text": content}
                    }]
                },
                "base_info": {
                    "channel_version": "1.0.2"
                }
            }

            async with httpx.AsyncClient(timeout=10.0) as client:
                logger.info(f"[WeChatPersonal] Sending request to {self.base_url}/ilink/bot/sendmessage")
                logger.info(f"[WeChatPersonal] Headers: {self._build_headers()}")
                logger.info(f"[WeChatPersonal] Payload: {payload}")
                
                response = await client.post(
                    f"{self.base_url}/ilink/bot/sendmessage",
                    headers=self._build_headers(),
                    json=payload
                )

                logger.info(f"[WeChatPersonal] Response status: {response.status_code}")
                logger.info(f"[WeChatPersonal] Response body: {response.text}")

                if response.status_code == 200:
                    try:
                        data = response.json()
                    except Exception as e:
                        logger.error(f"[WeChatPersonal] Failed to parse JSON: {e}")
                        return {"success": False, "error": f"Invalid JSON response: {response.text}"}
                    
                    ret = data.get("ret")
                    if ret == 0 or data == {}:
                        # ret=0 or empty response both mean success
                        logger.info(f"[WeChatPersonal] Message sent to {user_id}")
                        return {"success": True, "message_id": client_id}
                    elif ret == 10001:
                        # Token expired or invalid context
                        error_msg = "会话已过期，请用户重新发送消息"
                        logger.error(f"[WeChatPersonal] Context token expired: {data}")
                        return {"success": False, "error": error_msg}
                    else:
                        error_msg = data.get("errmsg") or data.get("error") or f"API error (ret={ret}): {data}"
                        logger.error(f"[WeChatPersonal] Send failed: {error_msg}")
                        return {"success": False, "error": error_msg}
                else:
                    logger.error(f"[WeChatPersonal] HTTP error: {response.status_code}, body: {response.text}")
                    return {"success": False, "error": f"HTTP {response.status_code}: {response.text[:200]}"}

        except Exception as e:
            logger.error(f"[WeChatPersonal] Send error: {e}")
            return {"success": False, "error": str(e)}

    async def verify_webhook(self, request_body: bytes, signature: str) -> bool:
        """iLink doesn't use webhooks, so this always returns True."""
        return True

    def parse_incoming_message(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Parse incoming iLink message."""
        try:
            if data.get("message_type") != 1:  # Not user message
                return None

            text = ""
            item_list = data.get("item_list", [])
            if item_list:
                item = item_list[0]
                if item.get("type") == 1:
                    text = item.get("text_item", {}).get("text", "")

            return {
                "user_id": data.get("from_user_id"),
                "content": text,
                "chat_id": data.get("context_token"),
                "timestamp": data.get("create_time"),
                "provider": "wechat_personal"
            }
        except Exception as e:
            logger.error(f"[WeChatPersonal] Parse error: {e}")
            return None

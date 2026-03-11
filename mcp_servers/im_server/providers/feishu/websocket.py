"""Feishu WebSocket client using official lark-oapi SDK."""

import asyncio
import logging
import threading
from typing import Optional, Callable, Dict, Any

import lark_oapi as lark
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1

logger = logging.getLogger("FeishuWebSocket")


class FeishuWebSocketClient:
    """Feishu WebSocket client using official SDK."""

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        message_handler: Callable[[Dict[str, Any]], None]
    ):
        """
        Initialize Feishu WebSocket client.

        Args:
            app_id: Feishu app ID
            app_secret: Feishu app secret
            message_handler: Callback for incoming messages
        """
        self.app_id = app_id
        self.app_secret = app_secret
        self.message_handler = message_handler
        self.client: Optional[lark.ws.Client] = None
        self._thread: Optional[threading.Thread] = None

    def _handle_message(self, data: P2ImMessageReceiveV1) -> None:
        """Handle incoming message event."""
        # ===== 最开始的调试日志 =====
        logger.info("[Feishu] ========== _handle_message CALLED ==========")
        logger.info(f"[Feishu] data type: {type(data)}")
        logger.info(f"[Feishu] data dir: {dir(data)}")
        logger.info(f"[Feishu] data: {data}")
        # =============================
        
        try:
            import json

            event = data.event
            message = event.message
            sender = event.sender

            # Parse message content
            content = message.content
            if isinstance(content, str):
                try:
                    content = json.loads(content)
                except Exception:
                    content = {"text": content}

            # Get user_id from sender
            user_id = None
            if sender.sender_id:
                # UserId object has 'union_id', 'user_id', 'open_id' attributes
                # For sending messages, we need open_id (app-specific), not union_id (cross-app)
                user_id = sender.sender_id.open_id or sender.sender_id.user_id or sender.sender_id.union_id

            # Try to get user_name from raw data if available
            user_name = None
            if hasattr(data, 'raw_data') and data.raw_data:
                raw_event = data.raw_data.get('event', {})
                raw_sender = raw_event.get('sender', {})
                # Try to find name in various places
                user_name = raw_sender.get('name') or raw_sender.get('user_name')

            parsed_message = {
                "type": "message",
                "message_id": message.message_id,
                "content": content,
                "chat_id": message.chat_id,
                "user_id": user_id,
                "user_name": user_name,  # May be None if not provided by Feishu
                "msg_type": message.message_type,
                "provider": "feishu"
            }

            logger.info(f"[Feishu] Received message from user_id={user_id}, user_name={user_name}: {parsed_message['content']}")

            # Call handler - handle async message handler
            try:
                result = self.message_handler(parsed_message)
                if asyncio.iscoroutine(result):
                    # Create event loop if needed
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            loop.create_task(result)
                        else:
                            loop.run_until_complete(result)
                    except RuntimeError:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        loop.run_until_complete(result)
                        loop.close()
            except Exception as e:
                logger.error(f"[Feishu] Error in message_handler: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"[Feishu] Error handling message: {e}", exc_info=True)

    def start(self):
        """Start WebSocket client in a background thread."""

        def run_client():
            """Run client with its own event loop."""
            # Create event handler
            event_handler = lark.EventDispatcherHandler.builder("", "") \
                .register_p2_im_message_receive_v1(self._handle_message) \
                .build()

            # Create WebSocket client
            self.client = lark.ws.Client(
                self.app_id,
                self.app_secret,
                event_handler=event_handler,
                log_level=lark.LogLevel.INFO
            )

            logger.info(f"[Feishu] Starting WebSocket client with app_id: {self.app_id}")

            # Start client - SDK handles connection and reconnection
            # Note: This may raise "event loop already running" initially,
            # but SDK will auto-reconnect and work correctly
            try:
                self.client.start()
            except RuntimeError as e:
                if "already running" in str(e):
                    logger.warning(f"[Feishu] Initial connection issue (will auto-reconnect): {e}")
                else:
                    raise

        # Run in a new thread
        self._thread = threading.Thread(target=run_client, daemon=True)
        self._thread.start()
        logger.info("[Feishu] WebSocket client started in background thread")

    def stop(self):
        """Stop WebSocket client."""
        logger.info("[Feishu] WebSocket client stopping...")
        # Note: lark-oapi client doesn't have explicit stop method
        # It will stop when the process exits

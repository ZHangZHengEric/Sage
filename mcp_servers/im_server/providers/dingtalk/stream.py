"""DingTalk Stream client for receiving messages without webhook.

This uses DingTalk's Stream Mode, which doesn't require public IP.
Reference: https://github.com/open-dingtalk/dingtalk-stream-sdk-python
"""

import json
import logging
import asyncio
import threading
from typing import Callable, Optional, Dict, Any

try:
    import dingtalk_stream
    DINGTALK_SDK_AVAILABLE = True
except ImportError:
    DINGTALK_SDK_AVAILABLE = False

logger = logging.getLogger("DingTalkStream")


class DingTalkStreamClient:
    """DingTalk Stream client for real-time message receiving."""
    
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        message_handler: Callable[[Dict[str, Any]], None]
    ):
        """
        Initialize DingTalk Stream client.
        
        Args:
            client_id: DingTalk app client_id (app_key)
            client_secret: DingTalk app client_secret (app_secret)
            message_handler: Callback for received messages
        """
        if not DINGTALK_SDK_AVAILABLE:
            raise ImportError("dingtalk-stream SDK not installed. Run: pip install dingtalk-stream")
        
        self.client_id = client_id
        self.client_secret = client_secret
        self.message_handler = message_handler
        self.running = False
        self.client: Optional[dingtalk_stream.DingTalkStreamClient] = None
        self.ws_thread: Optional[threading.Thread] = None
        
    def start(self):
        """Start Stream client in background thread."""
        if self.running:
            return
        
        self.running = True
        self.ws_thread = threading.Thread(target=self._run_client, daemon=True)
        self.ws_thread.start()
        logger.info("DingTalk Stream client started")
    
    def stop(self):
        """Stop Stream client."""
        self.running = False
        if self.client:
            try:
                # The SDK doesn't have a direct stop method, 
                # but we can stop the thread
                pass
            except:
                pass
        if self.ws_thread:
            self.ws_thread.join(timeout=5)
        logger.info("DingTalk Stream client stopped")
    
    def _run_client(self):
        """Run DingTalk Stream client in separate thread."""
        try:
            # Create credential
            credential = dingtalk_stream.Credential(
                self.client_id,
                self.client_secret
            )
            
            # Create client
            self.client = dingtalk_stream.DingTalkStreamClient(credential)
            
            # Register message handler
            handler = _DingTalkMessageHandler(self.message_handler)
            self.client.register_callback_handler(
                dingtalk_stream.ChatbotMessage.TOPIC,
                handler
            )
            
            # Start client (blocking)
            self.client.start_forever()
            
        except Exception as e:
            logger.error(f"DingTalk Stream error: {e}")
            self.running = False


class _DingTalkMessageHandler(dingtalk_stream.ChatbotHandler):
    """Internal handler for DingTalk messages."""
    
    def __init__(self, message_handler: Callable[[Dict[str, Any]], None]):
        super().__init__()
        self.message_handler = message_handler
    
    async def process(self, callback: dingtalk_stream.CallbackMessage):
        """Process incoming message."""
        try:
            # Parse message
            message = dingtalk_stream.ChatbotMessage.from_dict(callback.data)
            
            # Extract info
            parsed_message = {
                "type": "message",
                "message_id": message.message_id,
                "content": {"text": message.text.content if message.text else ""},
                "chat_id": message.conversation_id,
                "user_id": message.sender_staff_id,
                "user_name": message.sender_nick,
                "msg_type": "text",
                "provider": "dingtalk"
            }
            
            # Call handler
            self.message_handler(parsed_message)
            
            # Acknowledge message
            return dingtalk_stream.AckMessage.STATUS_OK, 'OK'
            
        except Exception as e:
            logger.error(f"Error processing DingTalk message: {e}")
            return dingtalk_stream.AckMessage.STATUS_OK, 'OK'

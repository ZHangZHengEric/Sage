"""DingTalk Stream client for receiving messages without webhook.

This uses DingTalk's Stream Mode, which doesn't require public IP.
Reference: https://github.com/open-dingtalk/dingtalk-stream-sdk-python
"""

import json
import logging
import asyncio
import threading
from typing import Callable, Optional, Dict, Any

logger = logging.getLogger("DingTalkStream")

# Runtime imports with fallback
try:
    import dingtalk_stream
    from dingtalk_stream import Credential, DingTalkStreamClient as _DingTalkStreamClient
    from dingtalk_stream import ChatbotHandler, CallbackMessage, ChatbotMessage, AckMessage
    DINGTALK_SDK_AVAILABLE = True
except ImportError:
    DINGTALK_SDK_AVAILABLE = False
    dingtalk_stream = None
    # Define dummy classes for type hints
    class Credential:
        pass
    class _DingTalkStreamClient:
        pass
    class ChatbotHandler:
        pass
    class CallbackMessage:
        pass
    class ChatbotMessage:
        TOPIC = ""
        @classmethod
        def from_dict(cls, data):
            return None
    class AckMessage:
        STATUS_OK = "OK"


class DingTalkStreamClient:
    """DingTalk Stream client for real-time message receiving."""
    
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        message_handler: Callable[[Dict[str, Any]], None]
    ):
        """Initialize DingTalk Stream client.
        
        Args:
            client_id: Client ID (App Key)
            client_secret: Client Secret (App Secret)
            message_handler: Callback function for received messages
        """
        if not DINGTALK_SDK_AVAILABLE:
            raise ImportError("dingtalk-stream SDK not installed. Run: pip install dingtalk-stream")
        
        self.client_id = client_id
        self.client_secret = client_secret
        self.message_handler = message_handler
        self.running = False
        self.client: Optional[Any] = None
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
        """Run DingTalk Stream client in separate thread with reconnection."""
        retry_count = 0
        max_retries = 10
        base_delay = 5  # seconds
        
        while self.running and retry_count < max_retries:
            loop = None
            try:
                # Create new event loop for this thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                # Run the async client setup
                loop.run_until_complete(self._run_client_async())
                
                # If we get here, the client stopped normally
                logger.info("DingTalk Stream client stopped normally")
                break
                
            except Exception as e:
                retry_count += 1
                error_msg = str(e)
                
                # Check if it's a network error
                if "no close frame received or sent" in error_msg or "network" in error_msg.lower():
                    logger.warning(f"[DingTalk Stream] Network error (attempt {retry_count}/{max_retries}): {e}")
                else:
                    logger.error(f"[DingTalk Stream] Error (attempt {retry_count}/{max_retries}): {e}")
                
                if retry_count < max_retries and self.running:
                    # Exponential backoff with max 60 seconds
                    delay = min(base_delay * (2 ** (retry_count - 1)), 60)
                    logger.info(f"[DingTalk Stream] Reconnecting in {delay} seconds...")
                    
                    # Sleep without blocking the loop
                    import time
                    time.sleep(delay)
                else:
                    logger.error("[DingTalk Stream] Max retries reached, giving up")
                    self.running = False
                    
            finally:
                if loop:
                    try:
                        loop.close()
                    except:
                        pass
        
        if not self.running:
            logger.info("[DingTalk Stream] Client stopped")
    
    async def _run_client_async(self):
        """Async method to run DingTalk Stream client."""
        # Create credential
        credential = Credential(
            self.client_id,
            self.client_secret
        )
        
        # Create client
        self.client = _DingTalkStreamClient(credential)
        
        # Register message handler
        handler = _DingTalkMessageHandler(self.message_handler)
        self.client.register_callback_handler(
            ChatbotMessage.TOPIC,
            handler
        )
        
        # Start client (blocks until stopped)
        logger.info("Connecting to DingTalk Stream...")
        
        try:
            await self.client.start()
            logger.info("DingTalk client.start() returned normally")
        except Exception as e:
            logger.error(f"DingTalk client.start() exception: {e}", exc_info=True)


class _DingTalkMessageHandler(ChatbotHandler):
    """Internal handler for DingTalk messages."""
    
    def __init__(self, message_handler: Callable[[Dict[str, Any]], None]):
        self.message_handler = message_handler
    
    async def process(self, callback: CallbackMessage):
        """Process incoming message."""
        # ===== 最开始的调试日志 =====
        logger.info(f"[DingTalk] ========== process() CALLED ==========")
        logger.info(f"[DingTalk] callback.data: {callback.data}")
        # =============================
        
        try:
            # Parse message
            message = ChatbotMessage.from_dict(callback.data)
            
            logger.info(f"[DingTalk] Parsed message: {message}")
            
            # Extract relevant info including session_webhook for reply
            msg_data = {
                "user_id": message.sender_staff_id,
                "user_name": message.sender_nick,
                "content": {"text": message.text.content},
                "chat_id": message.conversation_id,
                "msg_type": "text",
                "session_webhook": message.session_webhook,  # Save for reply
                "session_webhook_expired_time": message.session_webhook_expired_time,
                "sender_staff_id": message.sender_staff_id,
                "conversation_type": message.conversation_type,
            }
            
            logger.info(f"[DingTalk] Calling message_handler with: {msg_data}")
            
            # Call handler
            self.message_handler(msg_data)
            
            return AckMessage.STATUS_OK, 'OK'
            
        except Exception as e:
            logger.error(f"Error processing DingTalk message: {e}", exc_info=True)
            return AckMessage.STATUS_OK, 'OK'

"""DingTalk Stream client for receiving messages without webhook.

This uses DingTalk's Stream Mode, which doesn't require public IP.
Reference: https://github.com/open-dingtalk/dingtalk-stream-sdk-python
"""

import logging
import asyncio
import threading
import time
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
        message_handler: Callable[[Dict[str, Any]], None],
        heartbeat_interval: int = 60
    ):
        """Initialize DingTalk Stream client.
        
        Args:
            client_id: Client ID (App Key)
            client_secret: Client Secret (App Secret)
            message_handler: Callback function for received messages
            heartbeat_interval: Heartbeat check interval in seconds (default: 60)
        """
        if not DINGTALK_SDK_AVAILABLE:
            raise ImportError("dingtalk-stream SDK not installed. Run: pip install dingtalk-stream")
        
        self.client_id = client_id
        self.client_secret = client_secret
        self.message_handler = message_handler
        self.running = False
        self.client: Optional[Any] = None
        self.ws_thread: Optional[threading.Thread] = None
        
        # Heartbeat tracking - track if _run_client thread is alive
        self.heartbeat_interval = heartbeat_interval
        self._last_message_time: float = 0
        self._heartbeat_lock = threading.Lock()
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._ws_thread_lock = threading.Lock()
        
    def start(self):
        """Start Stream client in background thread."""
        if self.running:
            return
        
        self.running = True
        self._last_message_time = time.time()
        self._start_ws_thread()
        
        # Start heartbeat monitor
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_monitor, daemon=True)
        self._heartbeat_thread.start()
        
        logger.info("DingTalk Stream client started with heartbeat monitoring")
    
    def _start_ws_thread(self):
        """Start the WebSocket client thread."""
        with self._ws_thread_lock:
            if self.ws_thread and self.ws_thread.is_alive():
                logger.debug("[DingTalk] WS thread already running")
                return
            
            self.ws_thread = threading.Thread(target=self._run_client, daemon=True)
            self.ws_thread.start()
            logger.info("[DingTalk] WS thread started")
    
    def stop(self):
        """Stop Stream client."""
        self.running = False
        if self.client:
            try:
                # The SDK doesn't have a direct stop method,
                # but we can stop the thread
                pass
            except Exception:
                pass
        if self.ws_thread:
            self.ws_thread.join(timeout=5)
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=2)
        logger.info("DingTalk Stream client stopped")
    
    def update_last_message_time(self):
        """Update the last message received time - called when message is received."""
        with self._heartbeat_lock:
            self._last_message_time = time.time()
    
    def get_last_message_time(self) -> float:
        """Get the last message received time."""
        with self._heartbeat_lock:
            return self._last_message_time
    
    def _heartbeat_monitor(self):
        """Monitor connection health and restart if thread is dead."""
        logger.info(f"[DingTalk Heartbeat] Monitor started (interval={self.heartbeat_interval}s)")
        
        while self.running:
            try:
                time.sleep(self.heartbeat_interval)
                
                if not self.running:
                    break
                
                # Check if the WS thread is still alive
                with self._ws_thread_lock:
                    is_alive = self.ws_thread and self.ws_thread.is_alive()
                
                if not is_alive:
                    logger.warning("[DingTalk Heartbeat] WS thread is dead, restarting...")
                    self._start_ws_thread()
                else:
                    # Also check last message time for logging purposes
                    last_time = self.get_last_message_time()
                    elapsed = time.time() - last_time
                    logger.debug(f"[DingTalk Heartbeat] WS thread alive, last message {elapsed:.0f}s ago")
                    
            except Exception as e:
                logger.error(f"[DingTalk Heartbeat] Monitor error: {e}")
                time.sleep(5)
        
        logger.info("[DingTalk Heartbeat] Monitor stopped")
    
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
                    except Exception:
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
        
        # Register message handler - pass client reference for heartbeat updates
        handler = _DingTalkMessageHandler(self.message_handler, self)
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
            logger.error(f"DingTalk client.start() exception: {e}")


class _DingTalkMessageHandler(ChatbotHandler):
    """Internal handler for DingTalk messages."""
    
    def __init__(self, message_handler: Callable[[Dict[str, Any]], None], client: Optional['DingTalkStreamClient'] = None):
        self.message_handler = message_handler
        self._client = client
    
    async def process(self, callback: CallbackMessage):
        """Process incoming message."""
        # Update heartbeat time when message is received
        if self._client:
            self._client.update_last_message_time()
            logger.debug("[DingTalk Heartbeat] Message received, heartbeat time updated")
        
        # ===== 最开始的调试日志 =====
        logger.info("[DingTalk] ========== process() CALLED ==========")
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

            # Call handler - it may be async, so we need to handle both cases
            try:
                result = self.message_handler(msg_data)
                # If result is a coroutine, we need to run it
                if asyncio.iscoroutine(result):
                    # Create a new event loop for this thread if needed
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            # If loop is running, create a task
                            loop.create_task(result)
                        else:
                            loop.run_until_complete(result)
                    except RuntimeError:
                        # No event loop in this thread, create one
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        loop.run_until_complete(result)
                        loop.close()
            except Exception as handler_error:
                logger.error(f"[DingTalk] Error in message_handler: {handler_error}", exc_info=True)

            return AckMessage.STATUS_OK, 'OK'
            
        except Exception as e:
            logger.error(f"Error processing DingTalk message: {e}", exc_info=True)
            return AckMessage.STATUS_OK, 'OK'

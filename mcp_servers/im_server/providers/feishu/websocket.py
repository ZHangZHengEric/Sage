"""Feishu WebSocket client for receiving messages without webhook.

This uses Feishu's event subscription via WebSocket, which doesn't require public IP.
Reference: https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/event-subscription/overview
"""

import json
import logging
import asyncio
import threading
from typing import Callable, Optional, Dict, Any

import httpx
import websockets

logger = logging.getLogger("FeishuWebSocket")


class FeishuWebSocketClient:
    """Feishu WebSocket client for real-time message receiving."""
    
    def __init__(self, app_id: str, app_secret: str, message_handler: Callable[[Dict[str, Any]], None]):
        """
        Initialize Feishu WebSocket client.
        
        Args:
            app_id: Feishu app ID
            app_secret: Feishu app secret
            message_handler: Callback for received messages
        """
        self.app_id = app_id
        self.app_secret = app_secret
        self.message_handler = message_handler
        self.ws_url = None
        self.access_token = None
        self.running = False
        self.ws_thread: Optional[threading.Thread] = None
        
    async def _get_access_token(self) -> Optional[str]:
        """Get Feishu tenant access token."""
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json={
                "app_id": self.app_id,
                "app_secret": self.app_secret
            })
            data = resp.json()
            if data.get("code") == 0:
                return data.get("tenant_access_token")
            logger.error(f"Failed to get access token: {data}")
        return None
    
    async def _get_websocket_url(self) -> Optional[str]:
        """Get WebSocket connection URL."""
        if not self.access_token:
            self.access_token = await self._get_access_token()
            if not self.access_token:
                return None
        
        url = "https://open.feishu.cn/open-apis/event/v1/subscription/websocket"
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {self.access_token}"}
            )
            data = resp.json()
            if data.get("code") == 0:
                return data.get("data", {}).get("url")
            logger.error(f"Failed to get WebSocket URL: {data}")
        return None
    
    async def _connect_and_listen(self):
        """Connect to WebSocket and listen for messages."""
        ws_url = await self._get_websocket_url()
        if not ws_url:
            logger.error("Failed to get WebSocket URL")
            return
        
        logger.info(f"Connecting to Feishu WebSocket...")
        
        try:
            async with websockets.connect(ws_url) as websocket:
                logger.info("Connected to Feishu WebSocket")
                
                while self.running:
                    try:
                        message = await asyncio.wait_for(
                            websocket.recv(),
                            timeout=30
                        )
                        await self._handle_message(message)
                    except asyncio.TimeoutError:
                        # Send ping to keep connection alive
                        await websocket.ping()
                    except websockets.exceptions.ConnectionClosed:
                        logger.warning("WebSocket connection closed, reconnecting...")
                        break
                        
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
    
    async def _handle_message(self, message: str):
        """Handle incoming WebSocket message."""
        try:
            data = json.loads(message)
            
            # Check if it's a message event
            event_type = data.get("header", {}).get("event_type")
            
            if event_type == "im.message.receive_v1":
                event = data.get("event", {})
                message_data = event.get("message", {})
                sender = event.get("sender", {})
                
                parsed_message = {
                    "type": "message",
                    "message_id": message_data.get("message_id"),
                    "content": message_data.get("content", {}),
                    "chat_id": event.get("chat_id"),
                    "user_id": sender.get("sender_id", {}).get("user_id"),
                    "user_name": sender.get("sender_id", {}).get("name"),
                    "msg_type": message_data.get("message_type"),
                    "provider": "feishu"
                }
                
                # Call handler
                self.message_handler(parsed_message)
                
        except json.JSONDecodeError:
            logger.error(f"Failed to parse message: {message}")
        except Exception as e:
            logger.error(f"Error handling message: {e}")
    
    def _run_async_loop(self):
        """Run async WebSocket loop in separate thread."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        while self.running:
            try:
                loop.run_until_complete(self._connect_and_listen())
            except Exception as e:
                logger.error(f"WebSocket loop error: {e}")
            
            if self.running:
                logger.info("Reconnecting in 5 seconds...")
                loop.run_until_complete(asyncio.sleep(5))
        
        loop.close()
    
    def start(self):
        """Start WebSocket client in background thread."""
        if self.running:
            return
        
        self.running = True
        self.ws_thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self.ws_thread.start()
        logger.info("Feishu WebSocket client started")
    
    def stop(self):
        """Stop WebSocket client."""
        self.running = False
        if self.ws_thread:
            self.ws_thread.join(timeout=5)
        logger.info("Feishu WebSocket client stopped")

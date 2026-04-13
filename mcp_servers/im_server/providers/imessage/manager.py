"""iMessage Manager for bidirectional conversation.

Manages session binding, message routing, and conversation state for iMessage.
"""

import logging
import threading
from typing import Dict, Any, Optional
from datetime import datetime

from .provider import iMessageProvider
from .listener import iMessageNotificationListener, iMessageDatabasePoller

logger = logging.getLogger("iMessageManager")


class iMessageManager:
    """Manages iMessage bidirectional conversations."""
    
    def __init__(self, agent_id: str, use_database_polling: bool = True, config: Optional[Dict[str, Any]] = None):
        """
        Initialize iMessage manager.
        
        Args:
            agent_id: Default agent ID to route messages to
            use_database_polling: If True, use database polling (more reliable but requires Full Disk Access)
                                  If False, use notification listening (less reliable but easier setup)
            config: iMessage configuration dict with allowed_senders, etc.
        """
        self.agent_id = agent_id
        self.config = config or {}
        self.provider = iMessageProvider(self.config)
        
        # Session management: phone/email -> session_id mapping
        self._user_sessions: Dict[str, str] = {}  # user_id -> session_id
        self._session_users: Dict[str, str] = {}  # session_id -> user_id
        self._lock = threading.Lock()
        
        # Message listener
        if use_database_polling:
            self.listener = iMessageDatabasePoller(self._handle_incoming_message)
        else:
            self.listener = iMessageNotificationListener(self._handle_incoming_message)
            
        self._started = False
        
    async def start(self):
        """Start listening for incoming messages."""
        if self._started:
            return
            
        # Check iMessage availability
        result = await self.provider.check_availability()
        if not result.get("available"):
            logger.error(f"iMessage not available: {result.get('error')}")
            return
            
        logger.info("Starting iMessage listener...")
        self.listener.start()
        self._started = True
        logger.info("iMessage manager started")
        
    def stop(self):
        """Stop listening."""
        if self._started:
            self.listener.stop()
            self._started = False
            logger.info("iMessage manager stopped")
            
    def bind_user_to_session(self, user_id: str, session_id: str) -> bool:
        """
        Bind an iMessage user (phone/email) to a session.
        
        Args:
            user_id: Phone number or email address
            session_id: Sage session ID
            
        Returns:
            True if binding successful
        """
        with self._lock:
            self._user_sessions[user_id] = session_id
            self._session_users[session_id] = user_id
            
        logger.info(f"Bound user {user_id} to session {session_id}")
        return True
        
    def unbind_user(self, user_id: str):
        """Unbind a user."""
        with self._lock:
            session_id = self._user_sessions.get(user_id)
            if session_id:
                del self._user_sessions[user_id]
                if session_id in self._session_users:
                    del self._session_users[session_id]
                    
    def get_session_for_user(self, user_id: str) -> Optional[str]:
        """Get session ID for a user."""
        return self._user_sessions.get(user_id)
        
    def get_user_for_session(self, session_id: str) -> Optional[str]:
        """Get user ID for a session."""
        return self._session_users.get(session_id)
        
    async def send_message(self, session_id: str, content: str) -> Dict[str, Any]:
        """
        Send message to user via iMessage.
        
        Args:
            session_id: Sage session ID
            content: Message content
            
        Returns:
            Send result
        """
        user_id = self.get_user_for_session(session_id)
        if not user_id:
            return {
                "success": False,
                "error": f"No user bound to session {session_id}"
            }
            
        return await self.provider.send_message(
            content=content,
            user_id=user_id
        )
        
    def _handle_incoming_message(self, message: Dict[str, Any]):
        """
        Handle incoming iMessage from listener.
        
        Args:
            message: Dict with sender, content, timestamp
        """
        sender = message.get("sender")
        content = message.get("content")
        
        if not sender or not content:
            return
        
        # Check whitelist
        if not self.provider.is_sender_allowed(sender):
            logger.info(f"Ignoring message from non-whitelisted sender: {sender}")
            return
            
        logger.info(f"Received iMessage from {sender}: {content[:50]}...")
        
        # Find or create session
        session_id = self.get_session_for_user(sender)
        
        if not session_id:
            # Create new session
            import uuid
            session_id = f"imessage_{uuid.uuid4().hex[:12]}"
            self.bind_user_to_session(sender, session_id)
            logger.info(f"Created new session {session_id} for user {sender}")
            
        # Route to agent (this will be implemented in im_server.py)
        self._route_to_agent(session_id, sender, content)
        
    def _route_to_agent(self, session_id: str, sender: str, content: str):
        """
        Route incoming message to agent.
        This method should be overridden or connected to im_server's routing logic.
        """
        # This will be called when new message arrives
        # The actual routing logic should be implemented in im_server.py
        logger.info(f"Routing message from {sender} to agent via session {session_id}")
        
        # Store for later processing
        # The im_server will poll this or use a callback
        if not hasattr(self, '_pending_messages'):
            self._pending_messages = []
            
        self._pending_messages.append({
            "session_id": session_id,
            "sender": sender,
            "content": content,
            "timestamp": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
        })
        
    def get_pending_messages(self) -> list:
        """Get and clear pending messages."""
        if not hasattr(self, '_pending_messages'):
            return []
            
        messages = self._pending_messages.copy()
        self._pending_messages.clear()
        return messages
        
    def list_bindings(self) -> Dict[str, str]:
        """List all user-session bindings."""
        with self._lock:
            return self._user_sessions.copy()


# Global manager instance
_imessage_manager: Optional[iMessageManager] = None


def get_imessage_manager(agent_id: str = "default", config: Optional[Dict[str, Any]] = None) -> iMessageManager:
    """Get or create global iMessage manager instance."""
    global _imessage_manager
    if _imessage_manager is None:
        _imessage_manager = iMessageManager(agent_id, config=config)
    elif config is not None:
        # Update config if provided and different
        if _imessage_manager.config != config:
            logger.info(f"[iMessageManager] Updating config with new allowed_senders: {config.get('allowed_senders', [])}")
            _imessage_manager.config = config
            _imessage_manager.provider.allowed_senders = config.get("allowed_senders", [])
    return _imessage_manager

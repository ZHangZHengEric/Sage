"""Unified Session Manager for all IM providers.

Manages bidirectional conversation state and session bindings using SQLite database.
"""

import logging
import threading
from typing import Dict, Any, Optional, List

from .db import get_im_db, IMServerDB

logger = logging.getLogger("IMSessionManager")


class SessionManager:
    """Unified session manager for all IM providers using database storage."""
    
    def __init__(self, db: Optional[IMServerDB] = None):
        """
        Initialize session manager.
        
        Args:
            db: IMServerDB instance (optional, will use global instance if not provided)
        """
        self._lock = threading.Lock()
        
        # Use provided db or get global instance
        self._db = db or get_im_db()
        
        logger.info("SessionManager initialized with database storage")
        
    def bind_session(
        self,
        session_id: str,
        provider: str,
        user_id: str,
        chat_id: Optional[str] = None,
        user_name: Optional[str] = None,
        agent_id: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Bind a session to an IM user.
        
        Args:
            session_id: Sage session ID
            provider: IM provider name (feishu, dingtalk, wechat_work, imessage)
            user_id: User ID in the IM platform
            chat_id: Chat/Group ID (optional, for group chats)
            user_name: Display name of the user
            agent_id: Agent ID to route messages to
            extra: Extra provider-specific data
            
        Returns:
            True if binding successful
        """
        with self._lock:
            result = self._db.create_or_update_binding(
                session_id=session_id,
                provider=provider,
                user_id=user_id,
                user_name=user_name,
                chat_id=chat_id,
                agent_id=agent_id,
                metadata=extra
            )
            
        if result:
            logger.info(f"Bound session {session_id} to {provider}:{user_id}")
        else:
            logger.error(f"Failed to bind session {session_id} to {provider}:{user_id}")
        
        return result
    
    def unbind_session(self, session_id: str) -> bool:
        """Unbind a session."""
        with self._lock:
            result = self._db.delete_binding(session_id)
            
        if result:
            logger.info(f"Unbound session {session_id}")
        else:
            logger.warning(f"Failed to unbind session {session_id} (not found)")
        
        return result
    
    def get_binding(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get binding by session ID."""
        binding = self._db.get_binding(session_id)
        
        if binding:
            # Update last active time
            self._db.create_or_update_binding(
                session_id=session_id,
                provider=binding["provider"],
                user_id=binding["user_id"],
                user_name=binding.get("user_name"),
                chat_id=binding.get("chat_id"),
                agent_id=binding.get("agent_id"),
                metadata=binding.get("metadata")
            )
        
        return binding
    
    def find_session_by_user(self, provider: str, user_id: str, chat_id: Optional[str] = None) -> Optional[str]:
        """Find session ID by provider and user ID."""
        binding = self._db.find_binding_by_user(provider, user_id, chat_id)
        if binding:
            return binding.get("session_id")
        return None
    
    def find_or_create_session(
        self,
        provider: str,
        user_id: str,
        agent_id: str,
        chat_id: Optional[str] = None,
        user_name: Optional[str] = None
    ) -> str:
        """
        Find existing session or create new one.
        
        Returns:
            session_id
        """
        # Try to find existing session
        existing_session = self.find_session_by_user(provider, user_id, chat_id)
        if existing_session:
            logger.info(f"Found existing session {existing_session} for {provider}:{user_id}")
            return existing_session
        
        # Create new session
        import uuid
        session_id = f"im_{provider}_{uuid.uuid4().hex[:12]}"
        
        self.bind_session(
            session_id=session_id,
            provider=provider,
            user_id=user_id,
            chat_id=chat_id,
            user_name=user_name,
            agent_id=agent_id
        )
        
        return session_id
    
    def list_bindings(
        self,
        provider: Optional[str] = None,
        agent_id: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """List all bindings with optional filtering."""
        return self._db.list_bindings(provider, agent_id, limit)
    
    def update_last_active(self, session_id: str):
        """Update last active timestamp."""
        binding = self._db.get_binding(session_id)
        if binding:
            self._db.create_or_update_binding(
                session_id=session_id,
                provider=binding["provider"],
                user_id=binding["user_id"],
                user_name=binding.get("user_name"),
                chat_id=binding.get("chat_id"),
                agent_id=binding.get("agent_id"),
                metadata=binding.get("metadata")
            )

    def cleanup_expired_sessions(self, max_age_hours: int = 24):
        """Clean up expired sessions (not implemented for DB version - use SQL query if needed)."""
        # For database version, we could use a SQL query to delete old sessions
        # But for now, we'll leave them in the database for history
        logger.debug(f"Cleanup not implemented for DB version (max_age={max_age_hours}h)")


# Global session manager instance
_session_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    """Get or create global session manager instance."""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager

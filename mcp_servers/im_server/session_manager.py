"""Unified Session Manager for all IM providers.

Manages bidirectional conversation state and session bindings.
"""

import json
import logging
import threading
from typing import Dict, Any, Optional, List
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("IMSessionManager")


class SessionManager:
    """Unified session manager for all IM providers."""
    
    def __init__(self, storage_path: Optional[str] = None):
        """
        Initialize session manager.
        
        Args:
            storage_path: Path to store session bindings persistently
        """
        self._bindings: Dict[str, Dict[str, Any]] = {}  # session_id -> binding
        self._user_index: Dict[str, str] = {}  # provider:user_id -> session_id
        self._lock = threading.Lock()
        
        # Storage for persistence
        self._storage_path = storage_path or str(Path.home() / ".sage" / "im_session_bindings.json")
        self._load_bindings()
        
    def _load_bindings(self):
        """Load bindings from storage."""
        try:
            path = Path(self._storage_path)
            if path.exists():
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self._bindings = data.get("bindings", {})
                    self._user_index = data.get("user_index", {})
                logger.info(f"Loaded {len(self._bindings)} session bindings")
        except Exception as e:
            logger.warning(f"Failed to load bindings: {e}")
            
    def _save_bindings(self):
        """Save bindings to storage."""
        try:
            path = Path(self._storage_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump({
                    "bindings": self._bindings,
                    "user_index": self._user_index,
                    "updated_at": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
                }, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save bindings: {e}")
    
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
            # Create binding
            binding = {
                "session_id": session_id,
                "provider": provider,
                "user_id": user_id,
                "chat_id": chat_id,
                "user_name": user_name,
                "agent_id": agent_id,
                "bound_at": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"),
                "last_active": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"),
                "extra": extra or {}
            }
            
            # Update bindings
            self._bindings[session_id] = binding
            
            # Update user index for quick lookup
            user_key = f"{provider}:{user_id}"
            self._user_index[user_key] = session_id
            
            # Save to storage
            self._save_bindings()
            
        logger.info(f"Bound session {session_id} to {provider}:{user_id}")
        return True
    
    def unbind_session(self, session_id: str) -> bool:
        """Unbind a session."""
        with self._lock:
            if session_id not in self._bindings:
                return False
                
            binding = self._bindings[session_id]
            user_key = f"{binding['provider']}:{binding['user_id']}"
            
            del self._bindings[session_id]
            if user_key in self._user_index:
                del self._user_index[user_key]
                
            self._save_bindings()
            
        logger.info(f"Unbound session {session_id}")
        return True
    
    def get_binding(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get binding by session ID."""
        with self._lock:
            binding = self._bindings.get(session_id)
            if binding:
                # Update last active
                binding["last_active"] = datetime.now().astimezone().isoformat()
            return binding.copy() if binding else None
    
    def find_session_by_user(self, provider: str, user_id: str) -> Optional[str]:
        """Find session ID by provider and user ID."""
        user_key = f"{provider}:{user_id}"
        return self._user_index.get(user_key)
    
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
        existing_session = self.find_session_by_user(provider, user_id)
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
        agent_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List all bindings with optional filtering."""
        with self._lock:
            bindings = list(self._bindings.values())
            
        if provider:
            bindings = [b for b in bindings if b["provider"] == provider]
        if agent_id:
            bindings = [b for b in bindings if b.get("agent_id") == agent_id]
            
        return bindings
    
    def update_last_active(self, session_id: str):
        """Update last active timestamp."""
        with self._lock:
            if session_id in self._bindings:
                self._bindings[session_id]["last_active"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self._save_bindings()

    def _cleanup_expired_sessions(self):
        """Clean up expired sessions"""
        now = datetime.now().astimezone()
        expired_sessions = []
        
        with self._lock:
            for session_id, binding in self._bindings.items():
                last_active_str = binding.get("last_active")
                if not last_active_str:
                    continue
                    
                try:
                    # Robust parsing for both ISO formats (T or space)
                    last_active_str = last_active_str.replace(" ", "T")
                    last_active = datetime.fromisoformat(last_active_str)
                    
                    # Handle naive datetime (assume local if naive, as it was likely datetime.now())
                    if last_active.tzinfo is None:
                        last_active = last_active.replace(tzinfo=now.tzinfo)
                    
                    # Check expiration (e.g. 24 hours)
                    # TODO: Configurable timeout
                    if (now - last_active).total_seconds() > 24 * 3600:
                        expired_sessions.append(session_id)
                except Exception as e:
                    logger.warning(f"Error checking session expiration for {session_id}: {e}")
            
            # Remove expired sessions
            for session_id in expired_sessions:
                self.unbind_session(session_id)


# Global session manager instance
_session_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    """Get or create global session manager instance."""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager

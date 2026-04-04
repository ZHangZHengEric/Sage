"""
IM Server Database Module

Persistent storage for IM session bindings.
Reference: local sqlite helper pattern used by IM server only.
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List


class IMServerDB:
    """Database for IM session bindings."""
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        if not self.db_path.parent.exists():
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _get_conn(self):
        return sqlite3.connect(self.db_path, check_same_thread=False)
    
    def _init_db(self):
        """Initialize database with session bindings table."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            
            # Session bindings table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS im_session_bindings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT UNIQUE NOT NULL,
                    provider TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    user_name TEXT,
                    chat_id TEXT,
                    agent_id TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_message_at DATETIME,
                    metadata TEXT  -- JSON string for additional info
                )
            """)
            
            # Create indexes for performance
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_bindings_session 
                ON im_session_bindings(session_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_bindings_user 
                ON im_session_bindings(provider, user_id)
            """)
            
            # User IM configurations table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS im_user_configs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sage_user_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    config TEXT NOT NULL,  -- JSON string for provider config
                    enabled INTEGER DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(sage_user_id, provider)
                )
            """)
            
            # Create index for user configs
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_configs 
                ON im_user_configs(sage_user_id, provider)
            """)
            
            conn.commit()
    
    # === Session Bindings ===
    
    def create_or_update_binding(
        self,
        session_id: str,
        provider: str,
        user_id: str,
        user_name: Optional[str] = None,
        chat_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> bool:
        """Create or update session binding."""
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                now = datetime.now().isoformat()
                metadata_json = json.dumps(metadata) if metadata else None
                
                cursor.execute("""
                    INSERT INTO im_session_bindings 
                    (session_id, provider, user_id, user_name, chat_id, agent_id, 
                     updated_at, last_message_at, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET
                        user_name = excluded.user_name,
                        chat_id = excluded.chat_id,
                        agent_id = excluded.agent_id,
                        updated_at = excluded.updated_at,
                        last_message_at = excluded.last_message_at,
                        metadata = excluded.metadata
                """, (session_id, provider, user_id, user_name, chat_id, agent_id,
                      now, now, metadata_json))
                
                conn.commit()
                return True
        except Exception as e:
            print(f"[IM DB] Error creating binding: {e}")
            return False
    
    def get_binding(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session binding by session_id."""
        try:
            with self._get_conn() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT * FROM im_session_bindings 
                    WHERE session_id = ?
                """, (session_id,))
                
                row = cursor.fetchone()
                if row:
                    binding = dict(row)
                    if binding.get('metadata'):
                        binding['metadata'] = json.loads(binding['metadata'])
                    return binding
                return None
        except Exception as e:
            print(f"[IM DB] Error getting binding: {e}")
            return None
    
    def find_binding_by_user(
        self,
        provider: str,
        user_id: str,
        chat_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Find session binding by provider and user_id."""
        try:
            with self._get_conn() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                if chat_id:
                    cursor.execute("""
                        SELECT * FROM im_session_bindings 
                        WHERE provider = ? AND user_id = ? AND chat_id = ?
                        ORDER BY updated_at DESC LIMIT 1
                    """, (provider, user_id, chat_id))
                else:
                    cursor.execute("""
                        SELECT * FROM im_session_bindings 
                        WHERE provider = ? AND user_id = ?
                        ORDER BY updated_at DESC LIMIT 1
                    """, (provider, user_id))
                
                row = cursor.fetchone()
                if row:
                    binding = dict(row)
                    if binding.get('metadata'):
                        binding['metadata'] = json.loads(binding['metadata'])
                    return binding
                return None
        except Exception as e:
            print(f"[IM DB] Error finding binding: {e}")
            return None
    
    def list_bindings(
        self,
        provider: Optional[str] = None,
        agent_id: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """List session bindings with optional filters."""
        try:
            with self._get_conn() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                query = "SELECT * FROM im_session_bindings WHERE 1=1"
                params = []
                
                if provider:
                    query += " AND provider = ?"
                    params.append(provider)
                
                if agent_id:
                    query += " AND agent_id = ?"
                    params.append(agent_id)
                
                query += " ORDER BY updated_at DESC LIMIT ?"
                params.append(limit)
                
                cursor.execute(query, params)
                
                rows = cursor.fetchall()
                bindings = []
                for row in rows:
                    binding = dict(row)
                    if binding.get('metadata'):
                        binding['metadata'] = json.loads(binding['metadata'])
                    bindings.append(binding)
                return bindings
        except Exception as e:
            print(f"[IM DB] Error listing bindings: {e}")
            return []
    
    def delete_binding(self, session_id: str) -> bool:
        """Delete session binding."""
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    DELETE FROM im_session_bindings 
                    WHERE session_id = ?
                """, (session_id,))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            print(f"[IM DB] Error deleting binding: {e}")
            return False
    
    # === User IM Configurations ===
    
    def save_user_config(
        self,
        sage_user_id: str,
        provider: str,
        config: Dict[str, Any],
        enabled: bool = True
    ) -> bool:
        """Save or update user's IM configuration for a provider."""
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                now = datetime.now().isoformat()
                config_json = json.dumps(config, ensure_ascii=False)
                enabled_flag = 1 if enabled else 0
                
                cursor.execute("""
                    INSERT INTO im_user_configs 
                    (sage_user_id, provider, config, enabled, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(sage_user_id, provider) DO UPDATE SET
                        config = excluded.config,
                        enabled = excluded.enabled,
                        updated_at = excluded.updated_at
                """, (sage_user_id, provider, config_json, enabled_flag, now))
                
                conn.commit()
                return True
        except Exception as e:
            print(f"[IM DB] Error saving user config: {e}")
            return False
    
    def get_user_config(
        self,
        sage_user_id: str,
        provider: str
    ) -> Optional[Dict[str, Any]]:
        """Get user's IM configuration for a provider."""
        try:
            with self._get_conn() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT * FROM im_user_configs 
                    WHERE sage_user_id = ? AND provider = ? AND enabled = 1
                """, (sage_user_id, provider))
                
                row = cursor.fetchone()
                if row:
                    config = dict(row)
                    if config.get('config'):
                        config['config'] = json.loads(config['config'])
                    return config
                return None
        except Exception as e:
            print(f"[IM DB] Error getting user config: {e}")
            return None
    
    def list_user_configs(
        self,
        sage_user_id: str
    ) -> List[Dict[str, Any]]:
        """List all IM configurations for a user."""
        try:
            with self._get_conn() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT * FROM im_user_configs 
                    WHERE sage_user_id = ? AND enabled = 1
                    ORDER BY updated_at DESC
                """, (sage_user_id,))
                
                rows = cursor.fetchall()
                configs = []
                for row in rows:
                    config = dict(row)
                    if config.get('config'):
                        config['config'] = json.loads(config['config'])
                    configs.append(config)
                return configs
        except Exception as e:
            print(f"[IM DB] Error listing user configs: {e}")
            return []
    
    def delete_user_config(
        self,
        sage_user_id: str,
        provider: str
    ) -> bool:
        """Delete user's IM configuration for a provider."""
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    DELETE FROM im_user_configs 
                    WHERE sage_user_id = ? AND provider = ?
                """, (sage_user_id, provider))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            print(f"[IM DB] Error deleting user config: {e}")
            return False


# Global database instance
_im_db: Optional[IMServerDB] = None


def get_im_db(db_path: Optional[Path] = None) -> IMServerDB:
    """Get or create global IM database instance."""
    global _im_db
    if _im_db is None:
        if db_path is None:
            # Default path: ~/.sage/im_server.db
            db_path = Path.home() / ".sage" / "sage.db"
        _im_db = IMServerDB(db_path)
    return _im_db

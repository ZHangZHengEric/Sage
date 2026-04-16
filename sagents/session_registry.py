"""
SQLite-backed central registry for session ID → workspace path mapping.

Replaces the in-memory dict ``_all_session_paths`` that previously required
a full directory scan on every startup.
"""

import os
import sqlite3
import threading
import time
from typing import Dict, Optional

from sagents.utils.logger import logger


class SessionRegistry:
    """Thread-safe SQLite registry that maps session_id to its workspace path.

    Paths are stored as **relative paths** under ``root_dir`` so the registry
    remains valid even if ``root_dir`` is moved to a different location.
    """

    _CREATE_TABLE = """
        CREATE TABLE IF NOT EXISTS sessions (
            session_id       TEXT PRIMARY KEY,
            workspace        TEXT NOT NULL,
            parent_session_id TEXT,
            created_at       REAL NOT NULL
        )
    """

    def __init__(self, db_path: str, root_dir: str):
        self._db_path = db_path
        self._root_dir = os.path.abspath(root_dir)
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(self._CREATE_TABLE)
        self._conn.commit()

    def _to_relative(self, workspace: str) -> str:
        """Convert an absolute workspace path to a path relative to root_dir."""
        abs_ws = os.path.abspath(workspace)
        try:
            return os.path.relpath(abs_ws, self._root_dir)
        except ValueError:
            return abs_ws

    def _to_absolute(self, rel_path: str) -> str:
        """Convert a stored relative path back to an absolute path."""
        if os.path.isabs(rel_path):
            return rel_path
        return os.path.join(self._root_dir, rel_path)

    def register(
        self,
        session_id: str,
        workspace: str,
        parent_session_id: Optional[str] = None,
    ) -> None:
        rel_ws = self._to_relative(workspace)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO sessions (session_id, workspace, parent_session_id, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    workspace = excluded.workspace,
                    parent_session_id = COALESCE(excluded.parent_session_id, sessions.parent_session_id)
                """,
                (session_id, rel_ws, parent_session_id, time.time()),
            )
            self._conn.commit()

    def register_batch(
        self,
        entries: list,
    ) -> None:
        """Bulk-insert ``[(session_id, workspace, parent_session_id), ...]``."""
        now = time.time()
        with self._lock:
            self._conn.executemany(
                """
                INSERT OR IGNORE INTO sessions (session_id, workspace, parent_session_id, created_at)
                VALUES (?, ?, ?, ?)
                """,
                [(sid, self._to_relative(ws), pid, now) for sid, ws, pid in entries],
            )
            self._conn.commit()

    def get_workspace(self, session_id: str) -> Optional[str]:
        """Return the **absolute** workspace path for *session_id*, or ``None``."""
        with self._lock:
            row = self._conn.execute(
                "SELECT workspace FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return self._to_absolute(row[0]) if row else None

    def exists(self, session_id: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM sessions WHERE session_id = ? LIMIT 1",
                (session_id,),
            ).fetchone()
        return row is not None

    def is_sub_session(self, session_id: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT parent_session_id FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return row is not None and row[0] is not None

    def get_parent_session_id(self, session_id: str) -> Optional[str]:
        """Return the parent_session_id for *session_id*, or ``None``."""
        with self._lock:
            row = self._conn.execute(
                "SELECT parent_session_id FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return row[0] if row else None

    def remove(self, session_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM sessions WHERE session_id = ?",
                (session_id,),
            )
            self._conn.commit()

    def list_all(self) -> Dict[str, str]:
        """Return ``{session_id: absolute_workspace_path}``."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT session_id, workspace FROM sessions"
            ).fetchall()
        return {row[0]: self._to_absolute(row[1]) for row in rows}

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

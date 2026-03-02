import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from enum import Enum


class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskType(str, Enum):
    ONCE = "once"
    RECURRING = "recurring"


class TaskSchedulerDB:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        if not self.db_path.parent.exists():
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self):
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def _init_db(self):
        """Initialize database with new schema: separate tables for one-time and recurring tasks"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            
            # Recurring tasks table (templates for scheduled tasks)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS recurring_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT,
                    agent_id TEXT NOT NULL,
                    session_id TEXT,
                    cron_expression TEXT NOT NULL,
                    enabled BOOLEAN DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_executed_at DATETIME
                )
            """)
            
            # One-time tasks table (actual executable tasks)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT,
                    agent_id TEXT NOT NULL,
                    session_id TEXT,
                    execute_at DATETIME NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    completed_at DATETIME,
                    retry_count INTEGER DEFAULT 0,
                    max_retries INTEGER DEFAULT 3,
                    recurring_task_id INTEGER,
                    FOREIGN KEY (recurring_task_id) REFERENCES recurring_tasks (id)
                )
            """)
            
            # Task execution history table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS task_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    executed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    status TEXT,
                    response TEXT,
                    error_message TEXT,
                    FOREIGN KEY (task_id) REFERENCES tasks (id)
                )
            """)
            
            # Create indexes for performance
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_tasks_session_status 
                ON tasks (session_id, status)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_tasks_execute_at 
                ON tasks (execute_at)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_recurring_tasks_enabled 
                ON recurring_tasks (enabled)
            """)
            
            # Migration: Allow NULL session_id in existing tables
            self._migrate_allow_null_session_id(cursor)
            
            conn.commit()
    
    def _migrate_allow_null_session_id(self, cursor):
        """Migrate existing tables to allow NULL session_id"""
        try:
            # Check and alter recurring_tasks table
            cursor.execute("PRAGMA table_info(recurring_tasks)")
            columns = cursor.fetchall()
            session_id_col = next((col for col in columns if col[1] == 'session_id'), None)
            
            if session_id_col and session_id_col[3] == 1:  # notnull = 1
                # Need to recreate table to remove NOT NULL constraint
                cursor.execute("""
                    CREATE TABLE recurring_tasks_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        description TEXT,
                        agent_id TEXT NOT NULL,
                        session_id TEXT,
                        cron_expression TEXT NOT NULL,
                        enabled BOOLEAN DEFAULT 1,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        last_executed_at DATETIME
                    )
                """)
                cursor.execute("""
                    INSERT INTO recurring_tasks_new 
                    SELECT * FROM recurring_tasks
                """)
                cursor.execute("DROP TABLE recurring_tasks")
                cursor.execute("ALTER TABLE recurring_tasks_new RENAME TO recurring_tasks")
                print("Migrated recurring_tasks: session_id can now be NULL")
        except Exception as e:
            print(f"Migration warning for recurring_tasks: {e}")
        
        try:
            # Check and alter tasks table
            cursor.execute("PRAGMA table_info(tasks)")
            columns = cursor.fetchall()
            session_id_col = next((col for col in columns if col[1] == 'session_id'), None)
            
            if session_id_col and session_id_col[3] == 1:  # notnull = 1
                # Need to recreate table to remove NOT NULL constraint
                cursor.execute("""
                    CREATE TABLE tasks_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        description TEXT,
                        agent_id TEXT NOT NULL,
                        session_id TEXT,
                        execute_at DATETIME NOT NULL,
                        status TEXT DEFAULT 'pending',
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        completed_at DATETIME,
                        retry_count INTEGER DEFAULT 0,
                        max_retries INTEGER DEFAULT 3,
                        recurring_task_id INTEGER,
                        FOREIGN KEY (recurring_task_id) REFERENCES recurring_tasks (id)
                    )
                """)
                cursor.execute("""
                    INSERT INTO tasks_new 
                    SELECT * FROM tasks
                """)
                cursor.execute("DROP TABLE tasks")
                cursor.execute("ALTER TABLE tasks_new RENAME TO tasks")
                print("Migrated tasks: session_id can now be NULL")
        except Exception as e:
            print(f"Migration warning for tasks: {e}")

    # === Recurring Tasks Management ===
    
    def add_recurring_task(
        self,
        name: str,
        description: str,
        agent_id: str,
        session_id: str,
        cron_expression: str
    ) -> int:
        """Add a recurring task template"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO recurring_tasks (name, description, agent_id, session_id, cron_expression)
                VALUES (?, ?, ?, ?, ?)
            """, (name, description, agent_id, session_id, cron_expression))
            conn.commit()
            return cursor.lastrowid

    def list_recurring_tasks(
        self,
        agent_id: Optional[str] = None,
        enabled_only: bool = True
    ) -> List[Dict[str, Any]]:
        """List recurring task templates"""
        with self._get_conn() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            query = "SELECT * FROM recurring_tasks WHERE 1=1"
            params = []
            
            if agent_id:
                query += " AND agent_id = ?"
                params.append(agent_id)
            if enabled_only:
                query += " AND enabled = 1"
            
            query += " ORDER BY created_at DESC"
            
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_recurring_task(self, task_id: int) -> Optional[Dict[str, Any]]:
        """Get a recurring task template by ID"""
        with self._get_conn() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM recurring_tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_recurring_task_last_executed(self, task_id: int):
        """Update the last_executed_at timestamp for a recurring task"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE recurring_tasks 
                SET last_executed_at = ?, updated_at = ?
                WHERE id = ?
            """, (datetime.now().isoformat(), datetime.now().isoformat(), task_id))
            conn.commit()

    def delete_recurring_task(self, task_id: int) -> bool:
        """Delete a recurring task template and all its pending instances"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            # Delete pending tasks associated with this recurring task
            cursor.execute("""
                DELETE FROM tasks 
                WHERE recurring_task_id = ? AND status = 'pending'
            """, (task_id,))
            # Delete the recurring task
            cursor.execute("DELETE FROM recurring_tasks WHERE id = ?", (task_id,))
            conn.commit()
            return cursor.rowcount > 0

    def enable_recurring_task(self, task_id: int, enabled: bool) -> bool:
        """Enable or disable a recurring task"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE recurring_tasks 
                SET enabled = ?, updated_at = ?
                WHERE id = ?
            """, (1 if enabled else 0, datetime.now().isoformat(), task_id))
            conn.commit()
            return cursor.rowcount > 0

    # === One-time Tasks Management ===

    def add_task(
        self,
        name: str,
        description: str,
        agent_id: str,
        session_id: str,
        execute_at: str,
        recurring_task_id: Optional[int] = None
    ) -> int:
        """Add a one-time task (can be linked to a recurring task template)"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO tasks (name, description, agent_id, session_id, execute_at, status, recurring_task_id)
                VALUES (?, ?, ?, ?, ?, 'pending', ?)
            """, (name, description, agent_id, session_id, execute_at, recurring_task_id))
            conn.commit()
            return cursor.lastrowid

    def list_tasks(
        self,
        agent_id: Optional[str] = None,
        status: Optional[str] = None,
        session_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """List one-time tasks"""
        with self._get_conn() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            query = "SELECT * FROM tasks WHERE 1=1"
            params = []

            if agent_id:
                query += " AND agent_id = ?"
                params.append(agent_id)
            if status:
                query += " AND status = ?"
                params.append(status)
            if session_id:
                query += " AND session_id = ?"
                params.append(session_id)

            query += " ORDER BY execute_at ASC LIMIT ? OFFSET ?"
            params.append(limit)
            params.append(offset)

            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_task(self, task_id: int) -> Optional[Dict[str, Any]]:
        """Get a one-time task by ID"""
        with self._get_conn() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def delete_task(self, task_id: int) -> bool:
        """Delete a one-time task and its history"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            # First delete related history
            cursor.execute("DELETE FROM task_history WHERE task_id = ?", (task_id,))
            # Then delete the task
            cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            conn.commit()
            return cursor.rowcount > 0

    def complete_task(self, task_id: int) -> bool:
        """Mark a task as completed"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            completed_at = datetime.now().isoformat()
            cursor.execute("""
                UPDATE tasks
                SET status = 'completed', completed_at = ?, updated_at = ?
                WHERE id = ?
            """, (completed_at, completed_at, task_id))
            conn.commit()
            return cursor.rowcount > 0

    def get_pending_tasks(self) -> List[Dict[str, Any]]:
        """Get all pending tasks that are due for execution"""
        now = datetime.now().isoformat()
        with self._get_conn() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM tasks
                WHERE status = 'pending'
                  AND execute_at <= ?
                ORDER BY execute_at ASC
            """, (now,))
            return [dict(row) for row in cursor.fetchall()]

    def get_pending_tasks_by_session(self, session_id: str) -> List[Dict[str, Any]]:
        """Get pending tasks for a specific session, ordered by creation time"""
        with self._get_conn() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM tasks
                WHERE status = 'pending'
                  AND session_id = ?
                ORDER BY created_at ASC
            """, (session_id,))
            return [dict(row) for row in cursor.fetchall()]

    def claim_task(self, task_id: int) -> bool:
        """Claim a task for processing (atomic operation)"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE tasks SET status = 'processing', updated_at = ? WHERE id = ? AND status = 'pending'",
                (datetime.now().isoformat(), task_id)
            )
            conn.commit()
            return cursor.rowcount > 0

    def update_task_status(self, task_id: int, status: str, error_message: Optional[str] = None):
        """Update task status"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            updated_at = datetime.now().isoformat()
            if error_message:
                cursor.execute("""
                    UPDATE tasks
                    SET status = ?, updated_at = ?, retry_count = retry_count + 1
                    WHERE id = ?
                """, (status, updated_at, task_id))
            else:
                cursor.execute("""
                    UPDATE tasks
                    SET status = ?, updated_at = ?
                    WHERE id = ?
                """, (status, updated_at, task_id))
            conn.commit()

    def add_task_history(self, task_id: int, status: str, response: Optional[str] = None, error_message: Optional[str] = None):
        """Add task execution history record"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO task_history (task_id, status, response, error_message)
                VALUES (?, ?, ?, ?)
            """, (task_id, status, response, error_message))
            conn.commit()

    def get_task_history(self, task_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        """Get execution history for a task"""
        with self._get_conn() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM task_history
                WHERE task_id = ?
                ORDER BY executed_at DESC
                LIMIT ?
            """, (task_id, limit))
            return [dict(row) for row in cursor.fetchall()]

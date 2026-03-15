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
                CREATE INDEX IF NOT EXISTS idx_tasks_agent_status 
                ON tasks (agent_id, status)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_tasks_execute_at 
                ON tasks (execute_at)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_recurring_tasks_enabled 
                ON recurring_tasks (enabled)
            """)
            
            conn.commit()

    # === Recurring Tasks Management ===
    
    def add_recurring_task(
        self,
        name: str,
        description: str,
        agent_id: str,
        cron_expression: str
    ) -> int:
        """Add a recurring task template"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("""
                INSERT INTO recurring_tasks (name, description, agent_id, cron_expression, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (name, description, agent_id, cron_expression, now, now))
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

    def update_recurring_task_last_executed(self, task_id: int, executed_at: Optional[str] = None):
        """Update the last_executed_at timestamp for a recurring task
        
        Args:
            task_id: The recurring task ID
            executed_at: Optional timestamp string (YYYY-MM-DD HH:MM:SS format). If not provided, uses current time.
        """
        with self._get_conn() as conn:
            cursor = conn.cursor()
            now = executed_at or datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("""
                UPDATE recurring_tasks 
                SET last_executed_at = ?, updated_at = ?
                WHERE id = ?
            """, (now, now, task_id))
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
            """, (1 if enabled else 0, datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"), task_id))
            conn.commit()
            return cursor.rowcount > 0

    # === One-time Tasks Management ===

    def add_task(
        self,
        name: str,
        description: str,
        agent_id: str,
        execute_at: str,
        recurring_task_id: Optional[int] = None
    ) -> int:
        """Add a one-time task (can be linked to a recurring task template)"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("""
                INSERT INTO tasks (name, description, agent_id, execute_at, status, recurring_task_id, created_at, updated_at, retry_count, max_retries)
                VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, 0, 3)    
            """, (name, description, agent_id, execute_at, recurring_task_id, now, now))
            conn.commit()
            return cursor.lastrowid

    def list_tasks(
        self,
        agent_id: Optional[str] = None,
        status: Optional[str] = None,
        execute_after: Optional[str] = None,
        execute_before: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """List one-time tasks with optional time range filtering"""
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
            if execute_after:
                query += " AND execute_at >= ?"
                params.append(execute_after)
            if execute_before:
                query += " AND execute_at <= ?"
                params.append(execute_before)

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
            completed_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("""
                UPDATE tasks
                SET status = 'completed', completed_at = ?, updated_at = ?
                WHERE id = ?
            """, (completed_at, completed_at, task_id))
            conn.commit()
            return cursor.rowcount > 0

    def get_pending_tasks(self) -> List[Dict[str, Any]]:
        """Get all pending tasks that are due for execution"""
        # Use timezone-aware time for consistent comparison with task_scheduler_server
        now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
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

    def claim_task(self, task_id: int) -> bool:
        """Claim a task for processing (atomic operation)"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE tasks SET status = 'processing', updated_at = ? WHERE id = ? AND status = 'pending'",
                (datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"), task_id)
            )
            conn.commit()
            return cursor.rowcount > 0

    def update_task_status(self, task_id: int, status: str, error_message: Optional[str] = None):
        """Update task status"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            updated_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
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
                INSERT INTO task_history (task_id, status, response, error_message, executed_at)
                VALUES (?, ?, ?, ?, ?)
            """, (task_id, status, response, error_message, datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")))
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

    def update_recurring_task(self, task_id: int, **kwargs) -> bool:
        """
        Update a recurring task with the given fields.
        
        Args:
            task_id: The ID of the recurring task to update.
            **kwargs: Fields to update (name, description, agent_id, cron_expression, enabled).
            
        Returns:
            True if update was successful, False otherwise.
        """
        if not kwargs:
            return False
            
        allowed_fields = {'name', 'description', 'agent_id', 'cron_expression', 'enabled'}
        update_fields = {k: v for k, v in kwargs.items() if k in allowed_fields}
        
        if not update_fields:
            return False
            
        with self._get_conn() as conn:
            cursor = conn.cursor()
            set_clause = ", ".join([f"{k} = ?" for k in update_fields.keys()])
            set_clause += ", updated_at = ?"
            values = list(update_fields.values())
            values.append(datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"))
            values.append(task_id)
            
            cursor.execute(f"""
                UPDATE recurring_tasks 
                SET {set_clause}
                WHERE id = ?
            """, values)
            conn.commit()
            return cursor.rowcount > 0

    def update_task(self, task_id: int, **kwargs) -> bool:
        """
        Update a one-time task with the given fields.
        
        Args:
            task_id: The ID of the task to update.
            **kwargs: Fields to update (name, description, agent_id, execute_at, status, max_retries).
            
        Returns:
            True if update was successful, False otherwise.
        """
        if not kwargs:
            return False
            
        allowed_fields = {'name', 'description', 'agent_id', 'execute_at', 'status', 'max_retries'}
        update_fields = {k: v for k, v in kwargs.items() if k in allowed_fields}
        
        if not update_fields:
            return False
            
        with self._get_conn() as conn:
            cursor = conn.cursor()
            set_clause = ", ".join([f"{k} = ?" for k in update_fields.keys()])
            set_clause += ", updated_at = ?"
            values = list(update_fields.values())
            values.append(datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"))
            values.append(task_id)
            
            cursor.execute(f"""
                UPDATE tasks 
                SET {set_clause}
                WHERE id = ?
            """, values)
            conn.commit()
            return cursor.rowcount > 0

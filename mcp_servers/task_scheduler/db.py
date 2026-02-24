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
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class TaskSchedulerDB:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self):
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def _init_db(self):
        with self._get_conn() as conn:
            cursor = conn.cursor()
            # Tasks table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT,
                    agent_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    execute_at DATETIME NOT NULL,
                    task_type TEXT DEFAULT 'once',
                    status TEXT DEFAULT 'pending',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    completed_at DATETIME,
                    retry_count INTEGER DEFAULT 0,
                    max_retries INTEGER DEFAULT 3
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
            conn.commit()

    def add_task(
        self,
        name: str,
        description: str,
        agent_id: str,
        session_id: str,
        execute_at: str,
        task_type: str = "once"
    ) -> int:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO tasks (name, description, agent_id, session_id, execute_at, task_type, status)
                VALUES (?, ?, ?, ?, ?, ?, 'pending')
            """, (name, description, agent_id, session_id, execute_at, task_type))
            conn.commit()
            return cursor.lastrowid

    def list_tasks(
        self,
        agent_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
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

            query += " ORDER BY execute_at ASC LIMIT ? OFFSET ?"
            params.append(limit)
            params.append(offset)

            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_task(self, task_id: int) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def delete_task(self, task_id: int) -> bool:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            # First delete related history
            cursor.execute("DELETE FROM task_history WHERE task_id = ?", (task_id,))
            # Then delete the task
            cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            conn.commit()
            return cursor.rowcount > 0

    def complete_task(self, task_id: int) -> bool:
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

    def claim_task(self, task_id: int) -> bool:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE tasks SET status = 'processing', updated_at = ? WHERE id = ? AND status = 'pending'",
                (datetime.now().isoformat(), task_id)
            )
            conn.commit()
            return cursor.rowcount > 0

    def update_task_status(self, task_id: int, status: str, error_message: Optional[str] = None):
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

    def reschedule_recurring_task(self, task_id: int, task_type: str) -> bool:
        task = self.get_task(task_id)
        if not task or task_type == TaskType.ONCE:
            return False

        current_execute_at = datetime.fromisoformat(task['execute_at'])

        if task_type == TaskType.DAILY:
            next_execute_at = current_execute_at + timedelta(days=1)
        elif task_type == TaskType.WEEKLY:
            next_execute_at = current_execute_at + timedelta(weeks=1)
        elif task_type == TaskType.MONTHLY:
            # Add one month (approximate)
            next_month = current_execute_at.month + 1
            next_year = current_execute_at.year
            if next_month > 12:
                next_month = 1
                next_year += 1
            next_execute_at = current_execute_at.replace(year=next_year, month=next_month)
        else:
            return False

        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE tasks
                SET execute_at = ?, status = 'pending', updated_at = ?
                WHERE id = ?
            """, (next_execute_at.isoformat(), datetime.now().isoformat(), task_id))
            conn.commit()
            return cursor.rowcount > 0

    def add_task_history(self, task_id: int, status: str, response: Optional[str] = None, error_message: Optional[str] = None):
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO task_history (task_id, status, response, error_message)
                VALUES (?, ?, ?, ?)
            """, (task_id, status, response, error_message))
            conn.commit()

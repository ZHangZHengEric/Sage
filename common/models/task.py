"""Task / RecurringTask ORM + DAO shared by desktop and server."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, Text, desc, select, update
from sqlalchemy.orm import Mapped, mapped_column, relationship

from common.models.base import Base, BaseDao, get_local_now


class RecurringTask(Base):
    __tablename__ = "recurring_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(128), default="")
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    session_id: Mapped[str] = mapped_column(String(255), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(255), nullable=False)
    cron_expression: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=get_local_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=get_local_now, onupdate=get_local_now
    )
    last_executed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )

    tasks: Mapped[List["Task"]] = relationship(
        "Task", back_populates="recurring_task", cascade="all, delete-orphan"
    )


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(128), default="")
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    agent_id: Mapped[str] = mapped_column(String(255), nullable=False)
    session_id: Mapped[str] = mapped_column(String(255), nullable=True)
    execute_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), default="pending"
    )  # pending, processing, completed, failed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=get_local_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=get_local_now, onupdate=get_local_now
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    retry_count: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    max_retries: Mapped[Optional[int]] = mapped_column(Integer, default=3)
    recurring_task_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("recurring_tasks.id"), nullable=True
    )

    recurring_task: Mapped[Optional["RecurringTask"]] = relationship(
        "RecurringTask", back_populates="tasks"
    )
    history: Mapped[List["TaskHistory"]] = relationship(
        "TaskHistory", back_populates="task", cascade="all, delete-orphan"
    )


class TaskHistory(Base):
    __tablename__ = "task_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(Integer, ForeignKey("tasks.id"), nullable=False)
    executed_at: Mapped[datetime] = mapped_column(DateTime, default=get_local_now)
    status: Mapped[str] = mapped_column(String(50), nullable=True)
    response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    task: Mapped["Task"] = relationship("Task", back_populates="history")


import time
from loguru import logger

class TaskDao(BaseDao):
    """定时任务数据访问对象（DAO）"""

    async def get_recurring_list(
        self,
        page: int = 1,
        page_size: int = 20,
        agent_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> tuple[List[RecurringTask], int]:
        start_time = time.perf_counter()
        logger.info(f"[TaskDao] get_recurring_list START | page={page} | page_size={page_size} | agent_id={agent_id} | user_id={user_id}")
        where = []
        if agent_id:
            where.append(RecurringTask.agent_id == agent_id)
        if user_id:
            where.append(RecurringTask.user_id == user_id)

        result = await self.paginate_list(
            RecurringTask,
            where=where,
            order_by=desc(RecurringTask.created_at),
            page=page,
            page_size=page_size,
        )
        elapsed = time.perf_counter() - start_time
        logger.info(f"[TaskDao] get_recurring_list SUCCESS | count={len(result[0])} | total={result[1]} | time={elapsed:.3f}s")
        return result

    async def get_recurring_task(self, task_id: int) -> Optional[RecurringTask]:
        start_time = time.perf_counter()
        logger.info(f"[TaskDao] get_recurring_task START | task_id={task_id}")
        result = await self.get_by_id(RecurringTask, task_id)
        elapsed = time.perf_counter() - start_time
        logger.info(f"[TaskDao] get_recurring_task SUCCESS | task_id={task_id} | found={result is not None} | time={elapsed:.3f}s")
        return result

    async def get_enabled_recurring_tasks(
        self,
        *,
        user_id: Optional[str] = None,
    ) -> List[RecurringTask]:
        start_time = time.perf_counter()
        logger.info(f"[TaskDao] get_enabled_recurring_tasks START | user_id={user_id}")
        where = [RecurringTask.enabled == True]  # noqa: E712
        if user_id:
            where.append(RecurringTask.user_id == user_id)
        result = await self.get_list(
            RecurringTask,
            where=where,
            order_by=desc(RecurringTask.created_at),
        )
        elapsed = time.perf_counter() - start_time
        logger.info(f"[TaskDao] get_enabled_recurring_tasks SUCCESS | count={len(result)} | time={elapsed:.3f}s")
        return result

    async def create_recurring_task(self, task: RecurringTask) -> RecurringTask:
        start_time = time.perf_counter()
        logger.info(f"[TaskDao] create_recurring_task START | name='{task.name}' | agent_id={task.agent_id}")
        await self.insert(task)
        elapsed = time.perf_counter() - start_time
        logger.info(f"[TaskDao] create_recurring_task SUCCESS | task_id={task.id} | time={elapsed:.3f}s")
        return task

    async def update_recurring_task(self, task: RecurringTask) -> RecurringTask:
        start_time = time.perf_counter()
        logger.info(f"[TaskDao] update_recurring_task START | task_id={task.id}")
        task.updated_at = get_local_now()
        await self.save(task)
        elapsed = time.perf_counter() - start_time
        logger.info(f"[TaskDao] update_recurring_task SUCCESS | task_id={task.id} | time={elapsed:.3f}s")
        return task

    async def update_recurring_task_last_executed(
        self,
        task_id: int,
        executed_at: Optional[datetime] = None,
    ) -> Optional[RecurringTask]:
        task = await self.get_recurring_task(task_id)
        if not task:
            return None
        task.last_executed_at = executed_at or get_local_now()
        task.updated_at = get_local_now()
        await self.save(task)
        return task

    async def advance_recurring_task_cursor(
        self,
        task_id: int,
        *,
        expected_last_executed: Optional[datetime],
        executed_at: datetime,
        user_id: Optional[str] = None,
    ) -> bool:
        """
        原子推进 recurring task 的执行游标。

        通过比较旧的 last_executed_at 实现简单的 compare-and-set，避免多个调度器
        同时为同一条循环任务重复生成 one-time 实例。
        """
        db = await self._get_db()
        async with db.get_session() as session:  # type: ignore[attr-defined]
            stmt = update(RecurringTask).where(
                RecurringTask.id == task_id,
                RecurringTask.enabled == True,  # noqa: E712
            )
            if user_id:
                stmt = stmt.where(RecurringTask.user_id == user_id)
            if expected_last_executed is None:
                stmt = stmt.where(RecurringTask.last_executed_at.is_(None))
            else:
                stmt = stmt.where(RecurringTask.last_executed_at == expected_last_executed)

            stmt = stmt.values(last_executed_at=executed_at, updated_at=executed_at)
            result = await session.execute(stmt)
            return bool(result.rowcount)

    async def delete_recurring_task(self, task_id: int) -> bool:
        start_time = time.perf_counter()
        logger.info(f"[TaskDao] delete_recurring_task START | task_id={task_id}")
        result = await self.delete_by_id(RecurringTask, task_id)
        elapsed = time.perf_counter() - start_time
        logger.info(f"[TaskDao] delete_recurring_task SUCCESS | task_id={task_id} | result={result} | time={elapsed:.3f}s")
        return result

    async def get_task_history(
        self,
        recurring_task_id: int,
        page: int = 1,
        page_size: int = 20,
        user_id: Optional[str] = None,
    ) -> tuple[List[Task], int]:
        start_time = time.perf_counter()
        logger.info(f"[TaskDao] get_task_history START | recurring_task_id={recurring_task_id} | page={page} | user_id={user_id}")
        where = [Task.recurring_task_id == recurring_task_id]
        if user_id:
            where.append(Task.user_id == user_id)

        result = await self.paginate_list(
            Task,
            where=where,
            order_by=desc(Task.execute_at),
            page=page,
            page_size=page_size,
        )
        elapsed = time.perf_counter() - start_time
        logger.info(f"[TaskDao] get_task_history SUCCESS | count={len(result[0])} | time={elapsed:.3f}s")
        return result

    async def get_one_time_tasks(
        self,
        page: int = 1,
        page_size: int = 20,
        agent_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> tuple[List[Task], int]:
        """获取一次性任务列表（recurring_task_id=0）"""
        start_time = time.perf_counter()
        logger.info(f"[TaskDao] get_one_time_tasks START | page={page} | page_size={page_size} | agent_id={agent_id} | user_id={user_id}")
        where = [Task.recurring_task_id == 0]
        if agent_id:
            where.append(Task.agent_id == agent_id)
        if user_id:
            where.append(Task.user_id == user_id)

        result = await self.paginate_list(
            Task,
            where=where,
            order_by=desc(Task.created_at),
            page=page,
            page_size=page_size,
        )
        elapsed = time.perf_counter() - start_time
        logger.info(f"[TaskDao] get_one_time_tasks SUCCESS | count={len(result[0])} | total={result[1]} | time={elapsed:.3f}s")
        return result

    async def has_pending_task_instance(
        self,
        recurring_task_id: int,
        *,
        user_id: Optional[str] = None,
    ) -> bool:
        start_time = time.perf_counter()
        logger.info(f"[TaskDao] has_pending_task_instance START | recurring_task_id={recurring_task_id} | user_id={user_id}")
        where = [
            Task.recurring_task_id == recurring_task_id,
            Task.status == "pending",
        ]
        if user_id:
            where.append(Task.user_id == user_id)

        items = await self.get_list(
            Task,
            where=where,
            limit=1,
        )
        result = bool(items)
        elapsed = time.perf_counter() - start_time
        logger.info(f"[TaskDao] has_pending_task_instance SUCCESS | result={result} | time={elapsed:.3f}s")
        return result

    async def has_active_task_instance(
        self,
        recurring_task_id: int,
        *,
        user_id: Optional[str] = None,
    ) -> bool:
        start_time = time.perf_counter()
        logger.info(f"[TaskDao] has_active_task_instance START | recurring_task_id={recurring_task_id} | user_id={user_id}")
        where = [
            Task.recurring_task_id == recurring_task_id,
            Task.status.in_(("pending", "processing")),
        ]
        if user_id:
            where.append(Task.user_id == user_id)

        items = await self.get_list(
            Task,
            where=where,
            limit=1,
        )
        result = bool(items)
        elapsed = time.perf_counter() - start_time
        logger.info(f"[TaskDao] has_active_task_instance SUCCESS | result={result} | time={elapsed:.3f}s")
        return result

    async def create_one_time_task(self, task: Task) -> Task:
        import time
        from loguru import logger
        start_time = time.perf_counter()
        logger.info(f"[TaskDao] create_one_time_task START | name='{task.name}' | agent_id={task.agent_id}")
        await self.insert(task)
        elapsed = time.perf_counter() - start_time
        logger.info(f"[TaskDao] create_one_time_task SUCCESS | task_id={task.id} | time={elapsed:.3f}s")
        return task

    async def get_one_time_task(self, task_id: int) -> Optional[Task]:
        start_time = time.perf_counter()
        logger.info(f"[TaskDao] get_one_time_task START | task_id={task_id}")
        result = await self.get_by_id(Task, task_id)
        elapsed = time.perf_counter() - start_time
        logger.info(f"[TaskDao] get_one_time_task SUCCESS | task_id={task_id} | found={result is not None} | time={elapsed:.3f}s")
        return result

    async def get_due_pending_tasks(
        self,
        *,
        user_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Task]:
        start_time = time.perf_counter()
        logger.info(f"[TaskDao] get_due_pending_tasks START | user_id={user_id} | limit={limit}")
        where = [Task.status == "pending", Task.execute_at <= get_local_now()]
        if user_id:
            where.append(Task.user_id == user_id)
        result = await self.get_list(
            Task,
            where=where,
            order_by=Task.execute_at,
            limit=limit,
        )
        elapsed = time.perf_counter() - start_time
        logger.info(f"[TaskDao] get_due_pending_tasks SUCCESS | count={len(result)} | time={elapsed:.3f}s")
        return result

    async def claim_one_time_task(
        self,
        task_id: int,
        *,
        user_id: Optional[str] = None,
    ) -> bool:
        start_time = time.perf_counter()
        logger.info(f"[TaskDao] claim_one_time_task START | task_id={task_id} | user_id={user_id}")
        db = await self._get_db()
        async with db.get_session() as session:  # type: ignore[attr-defined]
            stmt = update(Task).where(Task.id == task_id, Task.status == "pending")
            if user_id:
                stmt = stmt.where(Task.user_id == user_id)
            stmt = stmt.values(status="processing", updated_at=get_local_now())
            result = await session.execute(stmt)
            claimed = bool(result.rowcount)
        elapsed = time.perf_counter() - start_time
        logger.info(f"[TaskDao] claim_one_time_task SUCCESS | task_id={task_id} | claimed={claimed} | time={elapsed:.3f}s")
        return claimed

    async def update_one_time_task(self, task: Task) -> Task:
        start_time = time.perf_counter()
        logger.info(f"[TaskDao] update_one_time_task START | task_id={task.id}")
        task.updated_at = get_local_now()
        await self.save(task)
        elapsed = time.perf_counter() - start_time
        logger.info(f"[TaskDao] update_one_time_task SUCCESS | task_id={task.id} | time={elapsed:.3f}s")
        return task

    async def complete_one_time_task(
        self,
        task_id: int,
        *,
        user_id: Optional[str] = None,
    ) -> Optional[Task]:
        start_time = time.perf_counter()
        logger.info(f"[TaskDao] complete_one_time_task START | task_id={task_id} | user_id={user_id}")
        task = await self.get_one_time_task(task_id)
        if not task or (user_id and task.user_id and task.user_id != user_id):
            elapsed = time.perf_counter() - start_time
            logger.warning(f"[TaskDao] complete_one_time_task FAILED | task_id={task_id} | error=Task not found or permission denied | time={elapsed:.3f}s")
            return None
        now = get_local_now()
        task.status = "completed"
        task.completed_at = now
        task.updated_at = now
        await self.save(task)
        elapsed = time.perf_counter() - start_time
        logger.info(f"[TaskDao] complete_one_time_task SUCCESS | task_id={task_id} | time={elapsed:.3f}s")
        return task

    async def fail_one_time_task(
        self,
        task_id: int,
        *,
        user_id: Optional[str] = None,
        retry: bool = True,
    ) -> Optional[Task]:
        start_time = time.perf_counter()
        logger.info(f"[TaskDao] fail_one_time_task START | task_id={task_id} | user_id={user_id} | retry={retry}")
        task = await self.get_one_time_task(task_id)
        if not task or (user_id and task.user_id and task.user_id != user_id):
            elapsed = time.perf_counter() - start_time
            logger.warning(f"[TaskDao] fail_one_time_task FAILED | task_id={task_id} | error=Task not found or permission denied | time={elapsed:.3f}s")
            return None
        now = get_local_now()
        task.retry_count = int(task.retry_count or 0) + 1
        max_retries = int(task.max_retries or 0)
        task.status = "pending" if retry and task.retry_count <= max_retries else "failed"
        task.updated_at = now
        await self.save(task)
        elapsed = time.perf_counter() - start_time
        logger.info(f"[TaskDao] fail_one_time_task SUCCESS | task_id={task_id} | new_status={task.status} | time={elapsed:.3f}s")
        return task

    async def add_task_history(
        self,
        task_id: int,
        *,
        status: str,
        response: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> TaskHistory:
        start_time = time.perf_counter()
        logger.info(f"[TaskDao] add_task_history START | task_id={task_id} | status={status}")
        history = TaskHistory(
            task_id=task_id,
            status=status,
            response=response,
            error_message=error_message,
        )
        await self.insert(history)
        elapsed = time.perf_counter() - start_time
        logger.info(f"[TaskDao] add_task_history SUCCESS | task_id={task_id} | history_id={history.id} | time={elapsed:.3f}s")
        return history

    async def get_one_time_task_history(
        self,
        task_id: int,
        *,
        limit: int = 20,
    ) -> List[TaskHistory]:
        start_time = time.perf_counter()
        logger.info(f"[TaskDao] get_one_time_task_history START | task_id={task_id} | limit={limit}")
        result = await self.get_list(
            TaskHistory,
            where=[TaskHistory.task_id == task_id],
            order_by=desc(TaskHistory.executed_at),
            limit=limit,
        )
        elapsed = time.perf_counter() - start_time
        logger.info(f"[TaskDao] get_one_time_task_history SUCCESS | task_id={task_id} | count={len(result)} | time={elapsed:.3f}s")
        return result

    async def delete_one_time_task(self, task_id: int) -> bool:
        start_time = time.perf_counter()
        logger.info(f"[TaskDao] delete_one_time_task START | task_id={task_id}")
        result = await self.delete_by_id(Task, task_id)
        elapsed = time.perf_counter() - start_time
        logger.info(f"[TaskDao] delete_one_time_task SUCCESS | task_id={task_id} | result={result} | time={elapsed:.3f}s")
        return result


__all__ = [
    "RecurringTask",
    "Task",
    "TaskHistory",
    "TaskDao",
]

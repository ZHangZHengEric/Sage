"""Task / RecurringTask ORM + DAO shared by desktop and server."""

import time
from datetime import datetime
from typing import List, Optional

from loguru import logger
from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    Text,
    String,
    delete,
    desc,
    select,
    update,
)
from sqlalchemy.orm import Mapped, mapped_column

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


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (Index("recurring_task_id", "recurring_task_id"),)

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
    recurring_task_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class TaskHistory(Base):
    __tablename__ = "task_history"
    __table_args__ = (Index("task_id", "task_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(Integer, nullable=False)
    executed_at: Mapped[datetime] = mapped_column(DateTime, default=get_local_now)
    status: Mapped[str] = mapped_column(String(50), nullable=True)
    response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


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
        logger.info(
            f"[TaskDao] get_recurring_list START | page={page} | page_size={page_size} | agent_id={agent_id} | user_id={user_id}"
        )
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
        logger.info(
            f"[TaskDao] get_recurring_list SUCCESS | count={len(result[0])} | total={result[1]} | time={elapsed:.3f}s"
        )
        return result

    async def get_recurring_task(self, task_id: int) -> Optional[RecurringTask]:
        start_time = time.perf_counter()
        logger.info(f"[TaskDao] get_recurring_task START | task_id={task_id}")
        result = await self.get_by_id(RecurringTask, task_id)
        elapsed = time.perf_counter() - start_time
        logger.info(
            f"[TaskDao] get_recurring_task SUCCESS | task_id={task_id} | found={result is not None} | time={elapsed:.3f}s"
        )
        return result

    async def get_enabled_recurring_tasks(
        self,
        *,
        user_id: Optional[str] = None,
    ) -> List[RecurringTask]:
        where = [RecurringTask.enabled == True]  # noqa: E712
        if user_id:
            where.append(RecurringTask.user_id == user_id)
        return await self.get_list(
            RecurringTask,
            where=where,
            order_by=desc(RecurringTask.created_at),
        )

    async def create_recurring_task(self, task: RecurringTask) -> RecurringTask:
        start_time = time.perf_counter()
        logger.info(
            f"[TaskDao] create_recurring_task START | name='{task.name}' | agent_id={task.agent_id}"
        )
        await self.insert(task)
        elapsed = time.perf_counter() - start_time
        logger.info(
            f"[TaskDao] create_recurring_task SUCCESS | task_id={task.id} | time={elapsed:.3f}s"
        )
        return task

    async def update_recurring_task(
        self,
        task_id: int,
        *,
        user_id: Optional[str],
        values: dict[str, object],
    ) -> Optional[RecurringTask]:
        start_time = time.perf_counter()
        logger.info(f"[TaskDao] update_recurring_task START | task_id={task_id}")
        db = await self._get_db()
        async with db.get_session() as session:  # type: ignore[attr-defined]
            task = await session.get(RecurringTask, task_id, with_for_update=True)
            if not task or (user_id and task.user_id and task.user_id != user_id):
                return None
            for field, value in values.items():
                setattr(task, field, value)
            task.updated_at = get_local_now()
            await session.flush()
        elapsed = time.perf_counter() - start_time
        logger.info(
            f"[TaskDao] update_recurring_task SUCCESS | task_id={task_id} | time={elapsed:.3f}s"
        )
        return task

    async def update_recurring_task_last_executed(
        self,
        task_id: int,
        executed_at: Optional[datetime] = None,
        user_id: Optional[str] = None,
    ) -> Optional[RecurringTask]:
        db = await self._get_db()
        async with db.get_session() as session:  # type: ignore[attr-defined]
            task = await session.get(RecurringTask, task_id, with_for_update=True)
            if not task or (user_id and task.user_id and task.user_id != user_id):
                return None
            task.last_executed_at = executed_at or get_local_now()
            task.updated_at = get_local_now()
            await session.flush()
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
                stmt = stmt.where(
                    RecurringTask.last_executed_at == expected_last_executed
                )

            stmt = stmt.values(last_executed_at=executed_at, updated_at=executed_at)
            result = await session.execute(stmt)
            return bool(result.rowcount)  # pyright: ignore[reportAttributeAccessIssue]

    async def spawn_recurring_task_instance(
        self,
        task: Task,
        *,
        expected_last_executed: datetime,
        executed_at: datetime,
        user_id: Optional[str] = None,
    ) -> bool:
        """Advance a recurring cursor and insert its task in one transaction."""
        recurring_task_id = int(task.recurring_task_id or 0)
        if not recurring_task_id:
            return False

        db = await self._get_db()
        async with db.get_session() as session:  # type: ignore[attr-defined]
            recurring_task = await session.get(
                RecurringTask,
                recurring_task_id,
                with_for_update=True,
            )
            if (
                not recurring_task
                or not recurring_task.enabled
                or (user_id and recurring_task.user_id != user_id)
                or recurring_task.last_executed_at != expected_last_executed
            ):
                return False

            active_stmt = (
                select(Task.id)
                .where(
                    Task.recurring_task_id == recurring_task_id,
                    Task.status.in_(("pending", "processing")),
                )
                .limit(1)
            )
            if (await session.execute(active_stmt)).scalar_one_or_none() is not None:
                return False

            recurring_task.last_executed_at = executed_at
            recurring_task.updated_at = executed_at
            session.add(task)
            await session.flush()
            return True

    async def delete_recurring_task(
        self,
        task_id: int,
        *,
        user_id: Optional[str] = None,
    ) -> bool:
        start_time = time.perf_counter()
        logger.info(f"[TaskDao] delete_recurring_task START | task_id={task_id}")
        db = await self._get_db()
        async with db.get_session() as session:  # type: ignore[attr-defined]
            recurring_task = await session.get(
                RecurringTask,
                task_id,
                with_for_update=True,
            )
            if not recurring_task or (
                user_id and recurring_task.user_id and recurring_task.user_id != user_id
            ):
                return False

            task_ids = list(
                (
                    await session.execute(
                        select(Task.id)
                        .where(Task.recurring_task_id == task_id)
                        .with_for_update()
                    )
                ).scalars()
            )
            if task_ids:
                await session.execute(
                    delete(TaskHistory).where(TaskHistory.task_id.in_(task_ids))
                )
                await session.execute(delete(Task).where(Task.id.in_(task_ids)))
            await session.delete(recurring_task)
            result = True
        elapsed = time.perf_counter() - start_time
        logger.info(
            f"[TaskDao] delete_recurring_task SUCCESS | task_id={task_id} | result={result} | time={elapsed:.3f}s"
        )
        return result

    async def get_task_history(
        self,
        recurring_task_id: int,
        page: int = 1,
        page_size: int = 20,
        user_id: Optional[str] = None,
    ) -> tuple[List[Task], int]:
        start_time = time.perf_counter()
        logger.info(
            f"[TaskDao] get_task_history START | recurring_task_id={recurring_task_id} | page={page} | user_id={user_id}"
        )
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
        logger.info(
            f"[TaskDao] get_task_history SUCCESS | count={len(result[0])} | time={elapsed:.3f}s"
        )
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
        logger.info(
            f"[TaskDao] get_one_time_tasks START | page={page} | page_size={page_size} | agent_id={agent_id} | user_id={user_id}"
        )
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
        logger.info(
            f"[TaskDao] get_one_time_tasks SUCCESS | count={len(result[0])} | total={result[1]} | time={elapsed:.3f}s"
        )
        return result

    async def has_pending_task_instance(
        self,
        recurring_task_id: int,
        *,
        user_id: Optional[str] = None,
    ) -> bool:
        start_time = time.perf_counter()
        logger.info(
            f"[TaskDao] has_pending_task_instance START | recurring_task_id={recurring_task_id} | user_id={user_id}"
        )
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
        logger.info(
            f"[TaskDao] has_pending_task_instance SUCCESS | result={result} | time={elapsed:.3f}s"
        )
        return result

    async def has_active_task_instance(
        self,
        recurring_task_id: int,
        *,
        user_id: Optional[str] = None,
    ) -> bool:
        start_time = time.perf_counter()
        logger.info(
            f"[TaskDao] has_active_task_instance START | recurring_task_id={recurring_task_id} | user_id={user_id}"
        )
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
        logger.info(
            f"[TaskDao] has_active_task_instance SUCCESS | result={result} | time={elapsed:.3f}s"
        )
        return result

    async def create_one_time_task(self, task: Task) -> Task:
        import time
        from loguru import logger

        start_time = time.perf_counter()
        logger.debug(
            f"[TaskDao] create_one_time_task START | name='{task.name}' | agent_id={task.agent_id}"
        )
        db = await self._get_db()
        async with db.get_session() as session:  # type: ignore[attr-defined]
            recurring_task_id = int(task.recurring_task_id or 0)
            if recurring_task_id:
                recurring_task = await session.get(
                    RecurringTask,
                    recurring_task_id,
                    with_for_update=True,
                )
                if not recurring_task or (
                    task.user_id
                    and recurring_task.user_id
                    and recurring_task.user_id != task.user_id
                ):
                    raise ValueError(
                        f"recurring task does not exist: {recurring_task_id}"
                    )
            session.add(task)
            await session.flush()
        elapsed = time.perf_counter() - start_time
        logger.debug(
            f"[TaskDao] create_one_time_task SUCCESS | task_id={task.id} | time={elapsed:.3f}s"
        )
        return task

    async def get_one_time_task(self, task_id: int) -> Optional[Task]:
        start_time = time.perf_counter()
        logger.info(f"[TaskDao] get_one_time_task START | task_id={task_id}")
        result = await self.get_by_id(Task, task_id)
        elapsed = time.perf_counter() - start_time
        logger.info(
            f"[TaskDao] get_one_time_task SUCCESS | task_id={task_id} | found={result is not None} | time={elapsed:.3f}s"
        )
        return result

    async def get_due_pending_tasks(
        self,
        *,
        user_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Task]:
        where = [Task.status == "pending", Task.execute_at <= get_local_now()]
        if user_id:
            where.append(Task.user_id == user_id)
        return await self.get_list(
            Task,
            where=where,
            order_by=Task.execute_at,
            limit=limit,
        )

    async def claim_one_time_task(
        self,
        task_id: int,
        *,
        user_id: Optional[str] = None,
    ) -> bool:
        start_time = time.perf_counter()
        logger.info(
            f"[TaskDao] claim_one_time_task START | task_id={task_id} | user_id={user_id}"
        )
        db = await self._get_db()
        async with db.get_session() as session:  # type: ignore[attr-defined]
            stmt = update(Task).where(Task.id == task_id, Task.status == "pending")
            if user_id:
                stmt = stmt.where(Task.user_id == user_id)
            stmt = stmt.values(status="processing", updated_at=get_local_now())
            result = await session.execute(stmt)
            claimed = bool(result.rowcount)  # pyright: ignore[reportAttributeAccessIssue]
        elapsed = time.perf_counter() - start_time
        logger.info(
            f"[TaskDao] claim_one_time_task SUCCESS | task_id={task_id} | claimed={claimed} | time={elapsed:.3f}s"
        )
        return claimed

    async def update_one_time_task(
        self,
        task_id: int,
        *,
        user_id: Optional[str],
        values: dict[str, object],
    ) -> Optional[Task]:
        start_time = time.perf_counter()
        logger.info(f"[TaskDao] update_one_time_task START | task_id={task_id}")
        db = await self._get_db()
        async with db.get_session() as session:  # type: ignore[attr-defined]
            task = await session.get(Task, task_id, with_for_update=True)
            if (
                not task
                or int(task.recurring_task_id or 0) != 0
                or (user_id and task.user_id and task.user_id != user_id)
            ):
                return None
            for field, value in values.items():
                setattr(task, field, value)
            task.updated_at = get_local_now()
            await session.flush()
        elapsed = time.perf_counter() - start_time
        logger.info(
            f"[TaskDao] update_one_time_task SUCCESS | task_id={task_id} | time={elapsed:.3f}s"
        )
        return task

    async def complete_one_time_task(
        self,
        task_id: int,
        *,
        user_id: Optional[str] = None,
        response: Optional[str] = None,
    ) -> Optional[Task]:
        start_time = time.perf_counter()
        logger.info(
            f"[TaskDao] complete_one_time_task START | task_id={task_id} | user_id={user_id}"
        )
        db = await self._get_db()
        async with db.get_session() as session:  # type: ignore[attr-defined]
            task = await session.get(Task, task_id, with_for_update=True)
            if not task or (user_id and task.user_id and task.user_id != user_id):
                elapsed = time.perf_counter() - start_time
                logger.warning(
                    f"[TaskDao] complete_one_time_task FAILED | task_id={task_id} | error=Task not found or permission denied | time={elapsed:.3f}s"
                )
                return None
            now = get_local_now()
            task.status = "completed"
            task.completed_at = now
            task.updated_at = now
            session.add(
                TaskHistory(
                    task_id=task_id,
                    status="completed",
                    response=response,
                )
            )
            await session.flush()
        elapsed = time.perf_counter() - start_time
        logger.info(
            f"[TaskDao] complete_one_time_task SUCCESS | task_id={task_id} | time={elapsed:.3f}s"
        )
        return task

    async def fail_one_time_task(
        self,
        task_id: int,
        *,
        user_id: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> Optional[Task]:
        start_time = time.perf_counter()
        logger.info(
            f"[TaskDao] fail_one_time_task START | task_id={task_id} | user_id={user_id}"
        )
        db = await self._get_db()
        async with db.get_session() as session:  # type: ignore[attr-defined]
            task = await session.get(Task, task_id, with_for_update=True)
            if not task or (user_id and task.user_id and task.user_id != user_id):
                elapsed = time.perf_counter() - start_time
                logger.warning(
                    f"[TaskDao] fail_one_time_task FAILED | task_id={task_id} | error=Task not found or permission denied | time={elapsed:.3f}s"
                )
                return None
            now = get_local_now()
            task.retry_count = int(task.retry_count or 0) + 1
            max_retries = int(task.max_retries or 0)
            task.status = (
                "pending" if task.retry_count <= max_retries else "failed"  # pyright: ignore[reportOptionalOperand]
            )
            task.updated_at = now
            session.add(
                TaskHistory(
                    task_id=task_id,
                    status="failed",
                    error_message=error_message,
                )
            )
            await session.flush()
        elapsed = time.perf_counter() - start_time
        logger.info(
            f"[TaskDao] fail_one_time_task SUCCESS | task_id={task_id} | new_status={task.status} | time={elapsed:.3f}s"
        )
        return task

    async def add_task_history(
        self,
        task_id: int,
        *,
        status: str,
        response: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> Optional[TaskHistory]:
        start_time = time.perf_counter()
        logger.info(
            f"[TaskDao] add_task_history START | task_id={task_id} | status={status}"
        )
        db = await self._get_db()
        async with db.get_session() as session:  # type: ignore[attr-defined]
            task = await session.get(Task, task_id, with_for_update=True)
            if not task:
                return None
            history = TaskHistory(
                task_id=task_id,
                status=status,
                response=response,
                error_message=error_message,
            )
            session.add(history)
            await session.flush()
        elapsed = time.perf_counter() - start_time
        logger.info(
            f"[TaskDao] add_task_history SUCCESS | task_id={task_id} | history_id={history.id} | time={elapsed:.3f}s"
        )
        return history

    async def get_one_time_task_history(
        self,
        task_id: int,
        *,
        limit: int = 20,
    ) -> List[TaskHistory]:
        start_time = time.perf_counter()
        logger.info(
            f"[TaskDao] get_one_time_task_history START | task_id={task_id} | limit={limit}"
        )
        result = await self.get_list(
            TaskHistory,
            where=[TaskHistory.task_id == task_id],
            order_by=desc(TaskHistory.executed_at),
            limit=limit,
        )
        elapsed = time.perf_counter() - start_time
        logger.info(
            f"[TaskDao] get_one_time_task_history SUCCESS | task_id={task_id} | count={len(result)} | time={elapsed:.3f}s"
        )
        return result

    async def delete_one_time_task(
        self,
        task_id: int,
        *,
        user_id: Optional[str] = None,
    ) -> bool:
        start_time = time.perf_counter()
        logger.info(f"[TaskDao] delete_one_time_task START | task_id={task_id}")
        db = await self._get_db()
        async with db.get_session() as session:  # type: ignore[attr-defined]
            task = await session.get(Task, task_id, with_for_update=True)
            if (
                not task
                or int(task.recurring_task_id or 0) != 0
                or (user_id and task.user_id and task.user_id != user_id)
            ):
                return False
            await session.execute(
                delete(TaskHistory).where(TaskHistory.task_id == task_id)
            )
            await session.delete(task)
            result = True
        elapsed = time.perf_counter() - start_time
        logger.info(
            f"[TaskDao] delete_one_time_task SUCCESS | task_id={task_id} | result={result} | time={elapsed:.3f}s"
        )
        return result


__all__ = [
    "RecurringTask",
    "Task",
    "TaskHistory",
    "TaskDao",
]

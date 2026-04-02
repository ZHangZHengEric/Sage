"""Task / RecurringTask ORM + DAO (desktop-only usage)."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import JSON, String, Integer, Boolean, DateTime, ForeignKey, Text, select, desc
from sqlalchemy.orm import Mapped, mapped_column, relationship

from common.models.base import Base, BaseDao, get_local_now


class RecurringTask(Base):
    __tablename__ = "recurring_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
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


class TaskDao(BaseDao):
    """定时任务数据访问对象（DAO）"""

    async def get_recurring_list(
        self,
        page: int = 1,
        page_size: int = 20,
        agent_id: Optional[str] = None,
    ) -> tuple[List[RecurringTask], int]:
        where = []
        if agent_id:
            where.append(RecurringTask.agent_id == agent_id)

        return await self.paginate_list(
            RecurringTask,
            where=where,
            order_by=desc(RecurringTask.created_at),
            page=page,
            page_size=page_size,
        )

    async def get_recurring_task(self, task_id: int) -> Optional[RecurringTask]:
        return await self.get_by_id(RecurringTask, task_id)

    async def create_recurring_task(self, task: RecurringTask) -> RecurringTask:
        await self.insert(task)
        return task

    async def update_recurring_task(self, task: RecurringTask) -> RecurringTask:
        task.updated_at = get_local_now()
        await self.save(task)
        return task

    async def delete_recurring_task(self, task_id: int) -> bool:
        return await self.delete_by_id(RecurringTask, task_id)

    async def get_task_history(
        self,
        recurring_task_id: int,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[List[Task], int]:
        where = [Task.recurring_task_id == recurring_task_id]

        return await self.paginate_list(
            Task,
            where=where,
            order_by=desc(Task.execute_at),
            page=page,
            page_size=page_size,
        )

    async def get_one_time_tasks(
        self,
        page: int = 1,
        page_size: int = 20,
        agent_id: Optional[str] = None,
    ) -> tuple[List[Task], int]:
        """获取一次性任务列表（recurring_task_id=0）"""
        where = [Task.recurring_task_id == 0]
        if agent_id:
            where.append(Task.agent_id == agent_id)

        return await self.paginate_list(
            Task,
            where=where,
            order_by=desc(Task.created_at),
            page=page,
            page_size=page_size,
        )

    async def create_one_time_task(self, task: Task) -> Task:
        await self.insert(task)
        return task

    async def get_one_time_task(self, task_id: int) -> Optional[Task]:
        return await self.get_by_id(Task, task_id)

    async def update_one_time_task(self, task: Task) -> Task:
        task.updated_at = get_local_now()
        await self.save(task)
        return task

    async def delete_one_time_task(self, task_id: int) -> bool:
        return await self.delete_by_id(Task, task_id)


__all__ = [
    "RecurringTask",
    "Task",
    "TaskHistory",
    "TaskDao",
]

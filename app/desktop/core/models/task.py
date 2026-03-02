from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import JSON, String, Integer, Boolean, DateTime, ForeignKey, Text, select, desc
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, BaseDao


class RecurringTask(Base):
    __tablename__ = "recurring_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    agent_id: Mapped[str] = mapped_column(String(255), nullable=False)
    cron_expression: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)
    last_executed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationship to tasks
    tasks: Mapped[List["Task"]] = relationship("Task", back_populates="recurring_task", cascade="all, delete-orphan")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    agent_id: Mapped[str] = mapped_column(String(255), nullable=False)
    session_id: Mapped[str] = mapped_column(String(255), nullable=True)
    execute_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending")  # pending, processing, completed, failed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    recurring_task_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("recurring_tasks.id"), nullable=True)
    
    # Relationship to recurring task
    recurring_task: Mapped[Optional["RecurringTask"]] = relationship("RecurringTask", back_populates="tasks")
    
    # Relationship to history
    history: Mapped[List["TaskHistory"]] = relationship("TaskHistory", back_populates="task", cascade="all, delete-orphan")


class TaskHistory(Base):
    __tablename__ = "task_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(Integer, ForeignKey("tasks.id"), nullable=False)
    executed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    status: Mapped[str] = mapped_column(String(50), nullable=True)
    response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    task: Mapped["Task"] = relationship("Task", back_populates="history")


class TaskDao(BaseDao):
    """
    定时任务数据访问对象（DAO）
    """

    async def get_recurring_list(
        self, 
        page: int = 1, 
        page_size: int = 20, 
        agent_id: Optional[str] = None
    ) -> tuple[List[RecurringTask], int]:
        """获取循环任务列表"""
        where = []
        if agent_id:
            where.append(RecurringTask.agent_id == agent_id)
        
        return await self.paginate_list(
            RecurringTask, 
            where=where, 
            order_by=desc(RecurringTask.created_at),
            page=page,
            page_size=page_size
        )

    async def get_recurring_task(self, task_id: int) -> Optional[RecurringTask]:
        """获取单个循环任务"""
        return await self.get_by_id(RecurringTask, task_id)

    async def create_recurring_task(self, task: RecurringTask) -> RecurringTask:
        """创建循环任务"""
        await self.save(task)
        return task

    async def update_recurring_task(self, task: RecurringTask) -> RecurringTask:
        """更新循环任务"""
        task.updated_at = datetime.now()
        await self.save(task)
        return task

    async def delete_recurring_task(self, task_id: int) -> bool:
        """删除循环任务"""
        return await self.delete_by_id(RecurringTask, task_id)

    async def get_task_history(
        self, 
        recurring_task_id: int, 
        page: int = 1, 
        page_size: int = 20
    ) -> tuple[List[Task], int]:
        """获取任务执行历史（通过 Task 表查询）"""
        where = [Task.recurring_task_id == recurring_task_id]
        
        return await self.paginate_list(
            Task,
            where=where,
            order_by=desc(Task.execute_at),
            page=page,
            page_size=page_size
        )

    async def get_one_time_tasks(
        self, 
        page: int = 1, 
        page_size: int = 20, 
        agent_id: Optional[str] = None
    ) -> tuple[List[Task], int]:
        """获取一次性任务列表（recurring_task_id=0）"""
        # TODO: 暂时使用 recurring_task_id=0 来标识一次性任务，后续可能需要更严谨的判断
        where = [Task.recurring_task_id == 0]
        if agent_id:
            where.append(Task.agent_id == agent_id)
        
        return await self.paginate_list(
            Task,
            where=where,
            order_by=desc(Task.created_at),
            page=page,
            page_size=page_size
        )

    async def create_one_time_task(self, task: Task) -> Task:
        """创建一次性任务"""
        await self.save(task)
        return task

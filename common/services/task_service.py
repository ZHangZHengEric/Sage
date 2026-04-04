from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from common.core.exceptions import SageHTTPException
from common.models.base import get_local_now
from common.models.task import RecurringTask, Task, TaskDao, TaskHistory
from common.schemas.base import (
    OneTimeTaskCreate,
    OneTimeTaskUpdate,
    RecurringTaskCreate,
    RecurringTaskUpdate,
)
from sagents.utils.logger import logger

try:
    from croniter import croniter
except ImportError:
    croniter = None


class TaskService:
    def __init__(self):
        self.dao = TaskDao()

    async def get_recurring_tasks(
        self,
        page: int = 1,
        page_size: int = 20,
        agent_id: Optional[str] = None,
        user_id: str = "",
    ) -> Tuple[List[RecurringTask], int]:
        return await self.dao.get_recurring_list(page, page_size, agent_id, user_id=user_id)

    async def create_recurring_task(
        self,
        data: RecurringTaskCreate,
        user_id: str = "",
    ) -> RecurringTask:
        session_id = "recurring-" + datetime.now().strftime("%Y%m%d%H%M%S")
        task = RecurringTask(
            user_id=user_id,
            name=data.name,
            session_id=session_id,
            description=data.description,
            agent_id=data.agent_id,
            cron_expression=data.cron_expression,
            enabled=data.enabled,
        )
        return await self.dao.create_recurring_task(task)

    async def create_one_time_task(
        self,
        data: OneTimeTaskCreate,
        user_id: str = "",
    ) -> Task:
        session_id = "one-time-" + datetime.now().strftime("%Y%m%d%H%M%S")
        execute_at = data.execute_at
        if execute_at.tzinfo is None:
            execute_at = execute_at.astimezone()

        task = Task(
            user_id=user_id,
            name=data.name,
            session_id=session_id,
            description=data.description,
            agent_id=data.agent_id,
            execute_at=execute_at,
            recurring_task_id=0,
            status="pending",
        )
        return await self.dao.create_one_time_task(task)

    async def update_one_time_task(
        self,
        task_id: int,
        data: OneTimeTaskUpdate,
        user_id: str = "",
    ) -> Task:
        task = await self.dao.get_one_time_task(task_id)
        if not task or task.recurring_task_id != 0 or (user_id and task.user_id and task.user_id != user_id):
            raise SageHTTPException(status_code=404, detail="Task not found")

        if data.name is not None:
            task.name = data.name
        if data.description is not None:
            task.description = data.description
        if data.agent_id is not None:
            task.agent_id = data.agent_id
        if data.execute_at is not None:
            execute_at = data.execute_at
            if execute_at.tzinfo is None:
                execute_at = execute_at.astimezone()
            task.execute_at = execute_at

        logger.info(
            "TaskService: updating one-time task id=%s user_id=%s agent_id=%s execute_at=%s status=%s",
            task.id,
            user_id or task.user_id or "",
            task.agent_id,
            task.execute_at,
            task.status,
        )

        return await self.dao.update_one_time_task(task)

    async def delete_one_time_task(self, task_id: int, user_id: str = "") -> bool:
        task = await self.dao.get_one_time_task(task_id)
        if not task or task.recurring_task_id != 0 or (user_id and task.user_id and task.user_id != user_id):
            raise SageHTTPException(status_code=404, detail="Task not found")
        return await self.dao.delete_one_time_task(task_id)

    async def update_recurring_task(
        self,
        task_id: int,
        data: RecurringTaskUpdate,
        user_id: str = "",
    ) -> RecurringTask:
        task = await self.dao.get_recurring_task(task_id)
        if not task or (user_id and task.user_id and task.user_id != user_id):
            raise SageHTTPException(status_code=404, detail="Task not found")

        if data.name is not None:
            task.name = data.name
        if data.description is not None:
            task.description = data.description
        if data.agent_id is not None:
            task.agent_id = data.agent_id
        if data.cron_expression is not None:
            task.cron_expression = data.cron_expression
        if data.enabled is not None:
            task.enabled = data.enabled

        return await self.dao.update_recurring_task(task)

    async def delete_recurring_task(self, task_id: int, user_id: str = "") -> bool:
        task = await self.dao.get_recurring_task(task_id)
        if not task or (user_id and task.user_id and task.user_id != user_id):
            raise SageHTTPException(status_code=404, detail="Task not found")
        return await self.dao.delete_recurring_task(task_id)

    async def toggle_task_status(self, task_id: int, enabled: bool, user_id: str = "") -> RecurringTask:
        task = await self.dao.get_recurring_task(task_id)
        if not task or (user_id and task.user_id and task.user_id != user_id):
            raise SageHTTPException(status_code=404, detail="Task not found")
        task.enabled = enabled
        return await self.dao.update_recurring_task(task)

    async def get_task_history(
        self,
        recurring_task_id: int,
        page: int = 1,
        page_size: int = 20,
        user_id: str = "",
    ) -> Tuple[List[Task], int]:
        return await self.dao.get_task_history(recurring_task_id, page, page_size, user_id=user_id)

    async def get_one_time_tasks(
        self,
        page: int = 1,
        page_size: int = 20,
        agent_id: Optional[str] = None,
        user_id: str = "",
    ) -> Tuple[List[Task], int]:
        return await self.dao.get_one_time_tasks(page, page_size, agent_id, user_id=user_id)

    async def get_one_time_task(self, task_id: int, user_id: str = "") -> Task:
        task = await self.dao.get_one_time_task(task_id)
        if not task or (user_id and task.user_id and task.user_id != user_id):
            raise SageHTTPException(status_code=404, detail="Task not found")
        return task

    async def get_recurring_task(self, task_id: int, user_id: str = "") -> RecurringTask:
        task = await self.dao.get_recurring_task(task_id)
        if not task or (user_id and task.user_id and task.user_id != user_id):
            raise SageHTTPException(status_code=404, detail="Task not found")
        return task

    async def get_one_time_task_history(
        self,
        task_id: int,
        *,
        user_id: str = "",
        limit: int = 20,
    ) -> List[TaskHistory]:
        await self.get_one_time_task(task_id, user_id=user_id)
        return await self.dao.get_one_time_task_history(task_id, limit=limit)

    async def get_due_pending_tasks(
        self,
        *,
        user_id: str = "",
        limit: int = 100,
    ) -> List[Task]:
        items = await self.dao.get_due_pending_tasks(user_id=user_id or None, limit=limit)
        logger.info(
            "TaskService: fetched due pending tasks count=%s user_id=%s limit=%s",
            len(items),
            user_id or "",
            limit,
        )
        return items

    async def claim_one_time_task(self, task_id: int, *, user_id: str = "") -> bool:
        return await self.dao.claim_one_time_task(task_id, user_id=user_id or None)

    async def complete_one_time_task(
        self,
        task_id: int,
        *,
        user_id: str = "",
        response: Optional[str] = None,
    ) -> Task:
        task = await self.dao.complete_one_time_task(task_id, user_id=user_id or None)
        if not task:
            raise SageHTTPException(status_code=404, detail="Task not found")
        await self.dao.add_task_history(task_id, status="completed", response=response)
        return task

    async def fail_one_time_task(
        self,
        task_id: int,
        *,
        user_id: str = "",
        error_message: Optional[str] = None,
    ) -> Task:
        task = await self.get_one_time_task(task_id, user_id=user_id)
        retry = int(task.retry_count or 0) < int(task.max_retries or 0)
        updated = await self.dao.fail_one_time_task(
            task_id,
            user_id=user_id or None,
            retry=retry,
        )
        if not updated:
            raise SageHTTPException(status_code=404, detail="Task not found")
        await self.dao.add_task_history(task_id, status="failed", error_message=error_message)
        return updated

    async def complete_recurring_task(
        self,
        task_id: int,
        *,
        user_id: str = "",
        executed_at: Optional[datetime] = None,
    ) -> RecurringTask:
        task = await self.get_recurring_task(task_id, user_id=user_id)
        updated = await self.dao.update_recurring_task_last_executed(task.id, executed_at=executed_at)
        if not updated:
            raise SageHTTPException(status_code=404, detail="Task not found")
        return updated

    async def spawn_due_recurring_tasks(
        self,
        *,
        user_id: str = "",
    ) -> List[Task]:
        if croniter is None:
            return []

        now = get_local_now()
        spawned: List[Task] = []
        recurring_tasks = await self.dao.get_enabled_recurring_tasks(user_id=user_id or None)
        logger.info(
            "TaskService: checking recurring tasks count=%s user_id=%s now=%s",
            len(recurring_tasks),
            user_id or "",
            now,
        )

        for recurring_task in recurring_tasks:
            try:
                if not croniter.is_valid(recurring_task.cron_expression):
                    continue

                last_executed = recurring_task.last_executed_at
                if last_executed is None:
                    task = Task(
                        user_id=recurring_task.user_id,
                        name=recurring_task.name,
                        session_id="one-time-" + datetime.now().strftime("%Y%m%d%H%M%S"),
                        description=recurring_task.description,
                        agent_id=recurring_task.agent_id,
                        execute_at=now,
                        recurring_task_id=recurring_task.id,
                        status="pending",
                    )
                    await self.dao.create_one_time_task(task)
                    await self.dao.update_recurring_task_last_executed(recurring_task.id, executed_at=now)
                    spawned.append(task)
                    logger.info(
                        "TaskService: spawned initial one-time task recurring_task_id=%s task_id=%s user_id=%s execute_at=%s",
                        recurring_task.id,
                        task.id,
                        recurring_task.user_id,
                        task.execute_at,
                    )
                    continue

                itr = croniter(recurring_task.cron_expression, last_executed)
                next_run = itr.get_next(datetime)
                if next_run > now + timedelta(minutes=1):
                    continue

                pending_tasks, _ = await self.dao.get_one_time_tasks(
                    page=1,
                    page_size=200,
                    agent_id=recurring_task.agent_id,
                    user_id=recurring_task.user_id,
                )
                has_pending_instance = any(
                    int(task.recurring_task_id or 0) == recurring_task.id and task.status == "pending"
                    for task in pending_tasks
                )
                await self.dao.update_recurring_task_last_executed(recurring_task.id, executed_at=next_run)
                if has_pending_instance:
                    continue

                task = Task(
                    user_id=recurring_task.user_id,
                    name=recurring_task.name,
                    session_id="one-time-" + datetime.now().strftime("%Y%m%d%H%M%S"),
                    description=recurring_task.description,
                    agent_id=recurring_task.agent_id,
                    execute_at=now,
                    recurring_task_id=recurring_task.id,
                    status="pending",
                )
                await self.dao.create_one_time_task(task)
                spawned.append(task)
                logger.info(
                    "TaskService: spawned recurring one-time task recurring_task_id=%s task_id=%s user_id=%s execute_at=%s next_run=%s",
                    recurring_task.id,
                    task.id,
                    recurring_task.user_id,
                    task.execute_at,
                    next_run,
                )
            except Exception:
                continue
        return spawned


task_service = TaskService()

from typing import List, Optional, Tuple
from datetime import datetime
from loguru import logger
from ..models.task import TaskDao, RecurringTask, Task
from ..schemas.task import RecurringTaskCreate, RecurringTaskUpdate, OneTimeTaskCreate
from ..core.exceptions import SageHTTPException

class TaskService:
    def __init__(self):
        self.dao = TaskDao()

    async def get_recurring_tasks(
        self, page: int = 1, page_size: int = 20, agent_id: Optional[str] = None
    ) -> Tuple[List[RecurringTask], int]:
        return await self.dao.get_recurring_list(page, page_size, agent_id)

    async def create_recurring_task(self, data: RecurringTaskCreate) -> RecurringTask:
        # TODO: Validate cron expression
        task = RecurringTask(
            name=data.name,
            description=data.description,
            agent_id=data.agent_id,
            cron_expression=data.cron_expression,
            enabled=data.enabled
        )
        return await self.dao.create_recurring_task(task)

    async def create_one_time_task(self, data: OneTimeTaskCreate) -> Task:
        session_id = "one-time-" + datetime.now().strftime("%Y%m%d%H%M%S")
        task = Task(
            name=data.name,
            session_id=session_id,
            description=data.description,
            agent_id=data.agent_id,
            execute_at=data.execute_at,
            recurring_task_id=0,
            status="pending"
        )
        return await self.dao.create_one_time_task(task)

    async def update_recurring_task(
        self, task_id: int, data: RecurringTaskUpdate
    ) -> RecurringTask:
        task = await self.dao.get_recurring_task(task_id)
        if not task:
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

    async def delete_recurring_task(self, task_id: int) -> bool:
        task = await self.dao.get_recurring_task(task_id)
        if not task:
            raise SageHTTPException(status_code=404, detail="Task not found")
        return await self.dao.delete_recurring_task(task_id)

    async def toggle_task_status(self, task_id: int, enabled: bool) -> RecurringTask:
        task = await self.dao.get_recurring_task(task_id)
        if not task:
            raise SageHTTPException(status_code=404, detail="Task not found")
        task.enabled = enabled
        return await self.dao.update_recurring_task(task)

    async def get_task_history(
        self, recurring_task_id: int, page: int = 1, page_size: int = 20
    ) -> Tuple[List[Task], int]:
        return await self.dao.get_task_history(recurring_task_id, page, page_size)

    async def get_one_time_tasks(
        self, page: int = 1, page_size: int = 20, agent_id: Optional[str] = None
    ) -> Tuple[List[Task], int]:
        return await self.dao.get_one_time_tasks(page, page_size, agent_id)

task_service = TaskService()

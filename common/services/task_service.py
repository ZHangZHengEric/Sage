from datetime import datetime
from typing import List, Optional, Tuple
import time

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
        start_time = time.perf_counter()
        logger.info(f"[TaskService] get_recurring_tasks START | page={page} | page_size={page_size} | agent_id={agent_id} | user_id={user_id}")
        result = await self.dao.get_recurring_list(page, page_size, agent_id, user_id=user_id)
        elapsed = time.perf_counter() - start_time
        logger.info(f"[TaskService] get_recurring_tasks SUCCESS | count={len(result[0])} | total={result[1]} | time={elapsed:.3f}s")
        return result

    async def create_recurring_task(
        self,
        data: RecurringTaskCreate,
        user_id: str = "",
    ) -> RecurringTask:
        start_time = time.perf_counter()
        logger.info(f"[TaskService] create_recurring_task START | name='{data.name}' | agent_id={data.agent_id} | user_id={user_id}")
        
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
        result = await self.dao.create_recurring_task(task)
        elapsed = time.perf_counter() - start_time
        logger.info(f"[TaskService] create_recurring_task SUCCESS | task_id={result.id} | time={elapsed:.3f}s")
        return result

    async def create_one_time_task(
        self,
        data: OneTimeTaskCreate,
        user_id: str = "",
    ) -> Task:
        start_time = time.perf_counter()
        logger.info(f"[TaskService] create_one_time_task START | name='{data.name}' | agent_id={data.agent_id} | user_id={user_id}")
        
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
        result = await self.dao.create_one_time_task(task)
        elapsed = time.perf_counter() - start_time
        logger.info(f"[TaskService] create_one_time_task SUCCESS | task_id={result.id} | time={elapsed:.3f}s")
        return result

    async def update_one_time_task(
        self,
        task_id: int,
        data: OneTimeTaskUpdate,
        user_id: str = "",
    ) -> Task:
        start_time = time.perf_counter()
        logger.info(f"[TaskService] update_one_time_task START | task_id={task_id} | user_id={user_id}")
        
        task = await self.dao.get_one_time_task(task_id)
        if not task or task.recurring_task_id != 0 or (user_id and task.user_id and task.user_id != user_id):
            logger.warning(f"[TaskService] update_one_time_task FAILED | task_id={task_id} | error=Task not found")
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

        result = await self.dao.update_one_time_task(task)
        elapsed = time.perf_counter() - start_time
        logger.info(f"[TaskService] update_one_time_task SUCCESS | task_id={task_id} | time={elapsed:.3f}s")
        return result

    async def delete_one_time_task(self, task_id: int, user_id: str = "") -> bool:
        start_time = time.perf_counter()
        logger.info(f"[TaskService] delete_one_time_task START | task_id={task_id} | user_id={user_id}")
        
        task = await self.dao.get_one_time_task(task_id)
        if not task or task.recurring_task_id != 0 or (user_id and task.user_id and task.user_id != user_id):
            logger.warning(f"[TaskService] delete_one_time_task FAILED | task_id={task_id} | error=Task not found")
            raise SageHTTPException(status_code=404, detail="Task not found")
        result = await self.dao.delete_one_time_task(task_id)
        elapsed = time.perf_counter() - start_time
        logger.info(f"[TaskService] delete_one_time_task SUCCESS | task_id={task_id} | time={elapsed:.3f}s")
        return result

    async def update_recurring_task(
        self,
        task_id: int,
        data: RecurringTaskUpdate,
        user_id: str = "",
    ) -> RecurringTask:
        start_time = time.perf_counter()
        logger.info(f"[TaskService] update_recurring_task START | task_id={task_id} | user_id={user_id}")
        
        task = await self.dao.get_recurring_task(task_id)
        if not task or (user_id and task.user_id and task.user_id != user_id):
            logger.warning(f"[TaskService] update_recurring_task FAILED | task_id={task_id} | error=Task not found")
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

        result = await self.dao.update_recurring_task(task)
        elapsed = time.perf_counter() - start_time
        logger.info(f"[TaskService] update_recurring_task SUCCESS | task_id={task_id} | time={elapsed:.3f}s")
        return result

    async def delete_recurring_task(self, task_id: int, user_id: str = "") -> bool:
        start_time = time.perf_counter()
        logger.info(f"[TaskService] delete_recurring_task START | task_id={task_id} | user_id={user_id}")
        
        task = await self.dao.get_recurring_task(task_id)
        if not task or (user_id and task.user_id and task.user_id != user_id):
            logger.warning(f"[TaskService] delete_recurring_task FAILED | task_id={task_id} | error=Task not found")
            raise SageHTTPException(status_code=404, detail="Task not found")
        result = await self.dao.delete_recurring_task(task_id)
        elapsed = time.perf_counter() - start_time
        logger.info(f"[TaskService] delete_recurring_task SUCCESS | task_id={task_id} | time={elapsed:.3f}s")
        return result

    async def toggle_task_status(self, task_id: int, enabled: bool, user_id: str = "") -> RecurringTask:
        start_time = time.perf_counter()
        logger.info(f"[TaskService] toggle_task_status START | task_id={task_id} | enabled={enabled} | user_id={user_id}")
        task = await self.dao.get_recurring_task(task_id)
        if not task or (user_id and task.user_id and task.user_id != user_id):
            logger.warning(f"[TaskService] toggle_task_status FAILED | task_id={task_id} | error=Task not found")
            raise SageHTTPException(status_code=404, detail="Task not found")
        task.enabled = enabled
        result = await self.dao.update_recurring_task(task)
        elapsed = time.perf_counter() - start_time
        logger.info(f"[TaskService] toggle_task_status SUCCESS | task_id={task_id} | enabled={enabled} | time={elapsed:.3f}s")
        return result

    async def get_task_history(
        self,
        recurring_task_id: int,
        page: int = 1,
        page_size: int = 20,
        user_id: str = "",
    ) -> Tuple[List[Task], int]:
        start_time = time.perf_counter()
        logger.info(f"[TaskService] get_task_history START | recurring_task_id={recurring_task_id} | page={page} | user_id={user_id}")
        result = await self.dao.get_task_history(recurring_task_id, page, page_size, user_id=user_id)
        elapsed = time.perf_counter() - start_time
        logger.info(f"[TaskService] get_task_history SUCCESS | count={len(result[0])} | time={elapsed:.3f}s")
        return result

    async def get_one_time_tasks(
        self,
        page: int = 1,
        page_size: int = 20,
        agent_id: Optional[str] = None,
        user_id: str = "",
    ) -> Tuple[List[Task], int]:
        start_time = time.perf_counter()
        logger.info(f"[TaskService] get_one_time_tasks START | page={page} | page_size={page_size} | agent_id={agent_id} | user_id={user_id}")
        result = await self.dao.get_one_time_tasks(page, page_size, agent_id, user_id=user_id)
        elapsed = time.perf_counter() - start_time
        logger.info(f"[TaskService] get_one_time_tasks SUCCESS | count={len(result[0])} | total={result[1]} | time={elapsed:.3f}s")
        return result

    async def get_one_time_task(self, task_id: int, user_id: str = "") -> Task:
        start_time = time.perf_counter()
        logger.info(f"[TaskService] get_one_time_task START | task_id={task_id} | user_id={user_id}")
        task = await self.dao.get_one_time_task(task_id)
        if not task or (user_id and task.user_id and task.user_id != user_id):
            logger.warning(f"[TaskService] get_one_time_task FAILED | task_id={task_id} | error=Task not found")
            raise SageHTTPException(status_code=404, detail="Task not found")
        elapsed = time.perf_counter() - start_time
        logger.info(f"[TaskService] get_one_time_task SUCCESS | task_id={task_id} | time={elapsed:.3f}s")
        return task

    async def get_recurring_task(self, task_id: int, user_id: str = "") -> RecurringTask:
        start_time = time.perf_counter()
        logger.info(f"[TaskService] get_recurring_task START | task_id={task_id} | user_id={user_id}")
        task = await self.dao.get_recurring_task(task_id)
        if not task or (user_id and task.user_id and task.user_id != user_id):
            logger.warning(f"[TaskService] get_recurring_task FAILED | task_id={task_id} | error=Task not found")
            raise SageHTTPException(status_code=404, detail="Task not found")
        elapsed = time.perf_counter() - start_time
        logger.info(f"[TaskService] get_recurring_task SUCCESS | task_id={task_id} | time={elapsed:.3f}s")
        return task

    async def get_one_time_task_history(
        self,
        task_id: int,
        *,
        user_id: str = "",
        limit: int = 20,
    ) -> List[TaskHistory]:
        start_time = time.perf_counter()
        logger.info(f"[TaskService] get_one_time_task_history START | task_id={task_id} | limit={limit} | user_id={user_id}")
        await self.get_one_time_task(task_id, user_id=user_id)
        result = await self.dao.get_one_time_task_history(task_id, limit=limit)
        elapsed = time.perf_counter() - start_time
        logger.info(f"[TaskService] get_one_time_task_history SUCCESS | task_id={task_id} | count={len(result)} | time={elapsed:.3f}s")
        return result

    async def get_due_pending_tasks(
        self,
        *,
        user_id: str = "",
        limit: int = 100,
    ) -> List[Task]:
        items = await self.dao.get_due_pending_tasks(user_id=user_id or None, limit=limit)
        return items

    async def claim_one_time_task(self, task_id: int, *, user_id: str = "") -> bool:
        start_time = time.perf_counter()
        logger.info(f"[TaskService] claim_one_time_task START | task_id={task_id} | user_id={user_id}")
        result = await self.dao.claim_one_time_task(task_id, user_id=user_id or None)
        elapsed = time.perf_counter() - start_time
        logger.info(f"[TaskService] claim_one_time_task SUCCESS | task_id={task_id} | claimed={result} | time={elapsed:.3f}s")
        return result

    async def complete_one_time_task(
        self,
        task_id: int,
        *,
        user_id: str = "",
        response: Optional[str] = None,
    ) -> Task:
        start_time = time.perf_counter()
        logger.info(f"[TaskService] complete_one_time_task START | task_id={task_id} | user_id={user_id}")
        task = await self.dao.complete_one_time_task(task_id, user_id=user_id or None)
        if not task:
            logger.warning(f"[TaskService] complete_one_time_task FAILED | task_id={task_id} | error=Task not found")
            raise SageHTTPException(status_code=404, detail="Task not found")
        await self.dao.add_task_history(task_id, status="completed", response=response)
        elapsed = time.perf_counter() - start_time
        logger.info(f"[TaskService] complete_one_time_task SUCCESS | task_id={task_id} | time={elapsed:.3f}s")
        return task

    async def fail_one_time_task(
        self,
        task_id: int,
        *,
        user_id: str = "",
        error_message: Optional[str] = None,
    ) -> Task:
        start_time = time.perf_counter()
        logger.info(f"[TaskService] fail_one_time_task START | task_id={task_id} | user_id={user_id}")
        task = await self.get_one_time_task(task_id, user_id=user_id)
        retry = int(task.retry_count or 0) < int(task.max_retries or 0)
        updated = await self.dao.fail_one_time_task(
            task_id,
            user_id=user_id or None,
            retry=retry,
        )
        if not updated:
            logger.warning(f"[TaskService] fail_one_time_task FAILED | task_id={task_id} | error=Task not found")
            raise SageHTTPException(status_code=404, detail="Task not found")
        await self.dao.add_task_history(task_id, status="failed", error_message=error_message)
        elapsed = time.perf_counter() - start_time
        logger.info(f"[TaskService] fail_one_time_task SUCCESS | task_id={task_id} | time={elapsed:.3f}s")
        return updated

    async def complete_recurring_task(
        self,
        task_id: int,
        *,
        user_id: str = "",
        executed_at: Optional[datetime] = None,
    ) -> RecurringTask:
        start_time = time.perf_counter()
        logger.info(f"[TaskService] complete_recurring_task START | task_id={task_id} | user_id={user_id}")
        task = await self.get_recurring_task(task_id, user_id=user_id)
        updated = await self.dao.update_recurring_task_last_executed(task.id, executed_at=executed_at)
        if not updated:
            logger.warning(f"[TaskService] complete_recurring_task FAILED | task_id={task_id} | error=Task not found")
            raise SageHTTPException(status_code=404, detail="Task not found")
        elapsed = time.perf_counter() - start_time
        logger.info(f"[TaskService] complete_recurring_task SUCCESS | task_id={task_id} | time={elapsed:.3f}s")
        return updated

    async def spawn_due_recurring_tasks(
        self,
        *,
        user_id: str = "",
    ) -> List[Task]:
        """
        为已到点的 recurring task 派生一条 one-time 实例。

        语义：到点才派生（不再做提前预派生）。
        - 取当前时间之前最近一次的 cron 触发点 prev_run
        - 若 prev_run 大于该 recurring task 的调度游标 last_executed_at，
          说明这一次触发还没派生过 → 创建一条 execute_at=prev_run 的 one-time 任务
        - 否则跳过
        - 首次见到（last_executed_at is None）只初始化游标到 now，不补派历史触发点
        """
        if croniter is None:
            logger.warning("[TaskService] spawn_due_recurring_tasks SKIPPED | croniter not available")
            return []

        now = get_local_now()
        spawned: List[Task] = []
        recurring_tasks = await self.dao.get_enabled_recurring_tasks(user_id=user_id or None)

        for recurring_task in recurring_tasks:
            try:
                if not croniter.is_valid(recurring_task.cron_expression):
                    continue

                last_executed = recurring_task.last_executed_at

                if last_executed is None:
                    await self.dao.advance_recurring_task_cursor(
                        recurring_task.id,
                        expected_last_executed=None,
                        executed_at=now,
                        user_id=recurring_task.user_id or None,
                    )
                    continue

                itr = croniter(recurring_task.cron_expression, now)
                prev_run = itr.get_prev(datetime)

                if prev_run <= last_executed:
                    continue

                active_instances = await self.dao.get_list(
                    Task,
                    where=[
                        Task.recurring_task_id == recurring_task.id,
                        Task.status.in_(("pending", "processing")),
                    ],
                    limit=1,
                )
                if active_instances:
                    continue

                claimed = await self.dao.advance_recurring_task_cursor(
                    recurring_task.id,
                    expected_last_executed=last_executed,
                    executed_at=prev_run,
                    user_id=recurring_task.user_id or None,
                )
                if not claimed:
                    continue

                task = Task(
                    user_id=recurring_task.user_id,
                    name=recurring_task.name,
                    session_id="one-time-" + datetime.now().strftime("%Y%m%d%H%M%S"),
                    description=recurring_task.description,
                    agent_id=recurring_task.agent_id,
                    execute_at=prev_run,
                    recurring_task_id=recurring_task.id,
                    status="pending",
                )
                await self.dao.create_one_time_task(task)
                spawned.append(task)
            except Exception as e:
                logger.error(f"[TaskService] spawn_due_recurring_tasks error | recurring_task_id={recurring_task.id} | error={e}")
                continue
        return spawned


task_service = TaskService()

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

import common.services.task_service as task_service_module
from common.models.task import RecurringTask
from common.services.task_service import TaskService


def _build_recurring_task(*, last_executed_at: datetime) -> RecurringTask:
    return RecurringTask(
        id=1,
        user_id="user-1",
        name="Daily digest",
        session_id="recurring-1",
        description="test recurring task",
        agent_id="agent-1",
        cron_expression="0 9 * * *",
        enabled=True,
        last_executed_at=last_executed_at,
    )


@pytest.mark.skipif(task_service_module.croniter is None, reason="croniter not installed")
def test_spawn_due_recurring_tasks_creates_only_one_catch_up_task(monkeypatch):
    fixed_now = datetime(2026, 4, 7, 15, 30, 0)
    monkeypatch.setattr(task_service_module, "get_local_now", lambda: fixed_now)

    service = TaskService()
    recurring_task = _build_recurring_task(last_executed_at=datetime(2026, 4, 1, 9, 0, 0))

    service.dao.get_enabled_recurring_tasks = AsyncMock(return_value=[recurring_task])
    service.dao.advance_recurring_task_cursor = AsyncMock(return_value=True)
    service.dao.has_active_task_instance = AsyncMock(return_value=False)
    service.dao.get_list = AsyncMock(return_value=[])
    service.dao.create_one_time_task = AsyncMock(side_effect=lambda task: task)

    spawned = asyncio.run(service.spawn_due_recurring_tasks(user_id="user-1"))

    assert len(spawned) == 1
    created_task = spawned[0]
    assert created_task.recurring_task_id == recurring_task.id
    # execute_at 为 cron 上一触发点，由 croniter 计算，不强行等于「当前时间」
    assert created_task.execute_at is not None
    service.dao.advance_recurring_task_cursor.assert_awaited_once()
    cargs, ckwargs = service.dao.advance_recurring_task_cursor.call_args
    assert cargs[0] == recurring_task.id
    assert ckwargs.get("expected_last_executed") == recurring_task.last_executed_at
    assert ckwargs.get("user_id") == recurring_task.user_id


@pytest.mark.skipif(task_service_module.croniter is None, reason="croniter not installed")
def test_spawn_due_recurring_tasks_does_not_backfill_when_pending_exists(monkeypatch):
    fixed_now = datetime(2026, 4, 7, 15, 30, 0)
    monkeypatch.setattr(task_service_module, "get_local_now", lambda: fixed_now)

    service = TaskService()
    recurring_task = _build_recurring_task(last_executed_at=datetime(2026, 4, 1, 9, 0, 0))

    service.dao.get_enabled_recurring_tasks = AsyncMock(return_value=[recurring_task])
    service.dao.advance_recurring_task_cursor = AsyncMock(return_value=True)
    service.dao.has_active_task_instance = AsyncMock(return_value=True)
    service.dao.get_list = AsyncMock(return_value=[object()])
    service.dao.create_one_time_task = AsyncMock()

    spawned = asyncio.run(service.spawn_due_recurring_tasks(user_id="user-1"))

    assert spawned == []
    service.dao.create_one_time_task.assert_not_awaited()
    # 已有进行中的 one-time 实例时直接跳过，不推进游标、不创建
    service.dao.advance_recurring_task_cursor.assert_not_awaited()


@pytest.mark.skipif(task_service_module.croniter is None, reason="croniter not installed")
def test_spawn_due_recurring_tasks_does_not_spawn_early_within_one_minute(monkeypatch):
    fixed_now = datetime(2026, 4, 8, 11, 59, 14)
    monkeypatch.setattr(task_service_module, "get_local_now", lambda: fixed_now)

    service = TaskService()
    recurring_task = RecurringTask(
        id=2,
        user_id="default_user",
        name="Noon task",
        session_id="recurring-2",
        description="run at noon",
        agent_id="agent-1",
        cron_expression="0 12 * * *",
        enabled=True,
        last_executed_at=datetime(2026, 4, 7, 12, 0, 0),
    )

    service.dao.get_enabled_recurring_tasks = AsyncMock(return_value=[recurring_task])
    service.dao.advance_recurring_task_cursor = AsyncMock()
    service.dao.has_active_task_instance = AsyncMock()
    service.dao.create_one_time_task = AsyncMock()

    spawned = asyncio.run(service.spawn_due_recurring_tasks(user_id="default_user"))

    assert spawned == []
    service.dao.advance_recurring_task_cursor.assert_not_awaited()
    service.dao.has_active_task_instance.assert_not_awaited()
    service.dao.create_one_time_task.assert_not_awaited()

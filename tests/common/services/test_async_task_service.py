import asyncio

import pytest

from common.services.async_task_service import AsyncTaskService


@pytest.mark.asyncio
async def test_terminal_task_drops_runner_and_expires_without_access():
    service = AsyncTaskService(
        retention_seconds=0.02,
        cleanup_interval_seconds=0.01,
    )
    submitted = await service.submit(
        task_type="test",
        owner_id="owner",
        runner=lambda: asyncio.sleep(0, result={"large": "result"}),
    )
    task_id = submitted["task_id"]

    for _ in range(20):
        task = service._tasks.get(task_id)
        if task and task.get("status") == "completed":
            break
        await asyncio.sleep(0.005)

    assert service._tasks[task_id]["status"] == "completed"
    assert "asyncio_task" not in service._tasks[task_id]

    await asyncio.sleep(0.05)
    assert task_id not in service._tasks
    await service.shutdown()


@pytest.mark.asyncio
async def test_shutdown_cancels_running_tasks_and_clears_registry():
    service = AsyncTaskService(cleanup_interval_seconds=60)
    started = asyncio.Event()

    async def runner():
        started.set()
        await asyncio.Event().wait()

    await service.submit(task_type="test", owner_id="owner", runner=runner)
    await started.wait()
    await service.shutdown()

    assert service._tasks == {}
    assert service._cleanup_task is None


@pytest.mark.asyncio
async def test_cancelled_submit_does_not_leave_pending_record_or_runner():
    service = AsyncTaskService(cleanup_interval_seconds=60)
    runner_called = False

    async def runner():
        nonlocal runner_called
        runner_called = True

    await service._lock.acquire()
    submit_task = asyncio.create_task(
        service.submit(task_type="test", owner_id="owner", runner=runner)
    )
    await asyncio.sleep(0)
    submit_task.cancel()
    service._lock.release()

    with pytest.raises(asyncio.CancelledError):
        await submit_task
    await asyncio.sleep(0)

    assert service._tasks == {}
    assert runner_called is False
    await service.shutdown()


@pytest.mark.asyncio
async def test_submit_cannot_register_after_shutdown_cutoff():
    service = AsyncTaskService(cleanup_interval_seconds=60)
    await service._lock.acquire()
    shutdown_task = asyncio.create_task(service.shutdown())
    await asyncio.sleep(0)
    submit_task = asyncio.create_task(
        service.submit(
            task_type="test",
            owner_id="owner",
            runner=lambda: asyncio.sleep(0),
        )
    )
    service._lock.release()

    await shutdown_task
    with pytest.raises(RuntimeError, match="shut down"):
        await submit_task
    assert service._tasks == {}

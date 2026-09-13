import asyncio
from unittest.mock import AsyncMock

import pytest
from mcp_servers.task_scheduler import task_scheduler_server as scheduler


@pytest.mark.asyncio
async def test_poll_backoff_recovers_without_hiding_spawn_failure(monkeypatch):
    monkeypatch.setattr(scheduler, "_wait_for_api_ready", AsyncMock())
    request = AsyncMock(
        side_effect=[OSError("offline"), OSError("offline"), {"items": []}, {"items": []}, OSError("offline")]
    )
    monkeypatch.setattr(scheduler, "_request_json", request)
    delays = []

    async def sleep(seconds):
        delays.append(seconds)
        if len(delays) == 4:
            raise asyncio.CancelledError

    monkeypatch.setattr(scheduler.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        await scheduler.scheduler_loop_async()
    assert delays == [5, 10, 30, 5]
    assert request.await_count == 5
    assert request.await_args_list[3].args == ("GET", "/tasks/internal/due")

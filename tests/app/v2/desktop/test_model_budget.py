
from typing import Any, cast

import asyncio

import pytest

from app.v2.desktop.backend.service import DesktopV2Service


@pytest.mark.asyncio
async def test_desktop_standard_runs_share_the_registered_model_budget(tmp_path):
    from tests.app.v2.desktop.sdk_fixture import desktop, execute
    from sagents.v2.testing.plugins import ScriptedModelProvider
    from tests.sagents.v2.test_standard_execution_configuration import response
    release, started = asyncio.Event(), asyncio.Event()
    calls = []
    class Model(ScriptedModelProvider):
        async def stream(self, request):
            calls.append(request.run_id)
            started.set()
            await release.wait()
            async for event in super().stream(request):
                yield event
    model = Model((response(), response()))
    service, _, _ = desktop(tmp_path, model=model, max_concurrent_model_calls=1)
    tasks = []
    try:
        tasks.append(asyncio.create_task(execute(service)))
        await asyncio.wait_for(started.wait(), 30)
        tasks.append(asyncio.create_task(execute(service)))
        async with asyncio.timeout(30):
            while service.model_budget.waiting != 1:
                await asyncio.sleep(0.01)
        assert service.model_budget.active == 1
        assert len(calls) == 1
        release.set()
        results = await asyncio.gather(*tasks)
        assert all(result[0].state.value == "completed" for result in results)
        assert len(calls) == 2
        assert service.model_budget.active == 0
        assert service.model_budget.waiting == 0
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await service.close()


@pytest.mark.asyncio
async def test_desktop_queue_overload_is_http_429_with_retry_metadata(tmp_path):
    from fastapi import HTTPException
    from app.v2.desktop.backend.app import _safe

    service = DesktopV2Service(
        tmp_path,
        max_concurrent_model_calls=1,
        max_waiting_model_calls=0,
        model_queue_timeout_seconds=2,
    )

    async def request():
        async with service.model_budget.lease():
            pytest.fail("no capacity available")

    try:
        async with service.model_budget.lease():
            with pytest.raises(HTTPException) as error:
                await _safe(request())
            assert error.value.status_code == 429
            assert cast('dict[str, Any]', error.value.detail)["code"] == "model.queue_full"
            assert cast('dict[str, Any]', error.value.detail)["retryable"] is True
        assert service.model_budget.waiting == 0
    finally:
        await service.close()

import asyncio

import pytest

from app.desktop_v2.backend.catalog import DesktopModelProviderRecord
from app.desktop_v2.backend.service import DesktopV2Service


@pytest.mark.asyncio
async def test_desktop_primary_and_auxiliary_providers_share_budget(
    tmp_path, monkeypatch
):
    calls = []
    release = asyncio.Event()
    started = asyncio.Event()

    class Provider:
        async def stream(self, request):
            calls.append(request)
            started.set()
            await release.wait()
            yield request

    monkeypatch.setattr(
        "app.desktop_v2.backend.run_composition.create_registered_model_provider",
        lambda *args, **kwargs: Provider(),
    )
    service = DesktopV2Service(tmp_path, max_concurrent_model_calls=1)
    tasks = []
    try:
        await service.start()
        agent = await service._agent("sage", "user_1")
        record = DesktopModelProviderRecord(
            id="test",
            user_id="user_1",
            name="Test",
            model="test",
            protocol="openai-chat-completions",
            base_url="https://example.invalid/v1",
            api_key="test",
        )
        primary = await service._model_provider(record, agent, enable_thinking=True)
        auxiliary = await service._model_provider(record, agent, enable_thinking=False)

        async def consume(provider, name):
            return [item async for item in provider.stream(name)]

        tasks.append(asyncio.create_task(consume(primary, "primary")))
        await started.wait()
        tasks.append(asyncio.create_task(consume(auxiliary, "auxiliary")))
        await asyncio.sleep(0)
        assert service.model_budget.snapshot() == {
            "limit": 1,
            "active": 1,
            "waiting": 1,
            "max_waiting": 128,
            "wait_timeout_seconds": 60,
            "rejected": 0,
            "timed_out": 0,
        }
        assert calls == ["primary"]
        release.set()
        assert await asyncio.gather(*tasks) == [["primary"], ["auxiliary"]]
        assert service.model_budget.active == 0
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await service.close()


@pytest.mark.asyncio
async def test_desktop_queue_overload_is_http_429_with_retry_metadata(tmp_path):
    from fastapi import HTTPException
    from app.desktop_v2.backend.app import _safe

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
            assert error.value.detail["code"] == "model.queue_full"
            assert error.value.detail["retryable"] is True
        assert service.model_budget.waiting == 0
    finally:
        await service.close()

import asyncio

import pytest

from sagents.v2.model.middleware.concurrency import ModelConcurrencyBudget


@pytest.mark.asyncio
async def test_shared_budget_bounds_independent_streams_and_cancelled_waiters():
    budget = ModelConcurrencyBudget(1)
    release = asyncio.Event()
    started = asyncio.Event()
    calls = []
    closed = []

    class Provider:
        async def stream(self, request):
            calls.append(request)
            started.set()
            try:
                await release.wait()
                yield request
            finally:
                closed.append(request)

    async def consume(provider, request):
        return [item async for item in provider.stream(request)]

    first = asyncio.create_task(consume(budget.wrap(Provider()), "first"))
    await started.wait()
    second = asyncio.create_task(consume(budget.wrap(Provider()), "second"))
    await asyncio.sleep(0)
    assert budget.snapshot() == {
        "limit": 1,
        "active": 1,
        "waiting": 1,
        "max_waiting": 128,
        "wait_timeout_seconds": 60,
        "rejected": 0,
        "timed_out": 0,
    }
    second.cancel()
    with pytest.raises(asyncio.CancelledError):
        await second
    assert budget.waiting == 0
    release.set()
    assert await first == ["first"]
    assert calls == closed == ["first"]
    assert budget.active == 0
    assert await consume(budget.wrap(Provider()), "third") == ["third"]


@pytest.mark.asyncio
async def test_stream_failure_and_early_close_return_permit():
    budget = ModelConcurrencyBudget(1)
    closed = []

    class Provider:
        async def stream(self, request):
            try:
                yield "first"
                raise ValueError("stream broke")
            finally:
                closed.append(True)

    stream = budget.wrap(Provider()).stream(None)
    assert await anext(stream) == "first"
    assert budget.active == 1
    await stream.aclose()
    assert budget.active == 0
    with pytest.raises(ValueError, match="stream broke"):
        async for _ in budget.wrap(Provider()).stream(None):
            pass
    assert budget.active == 0
    assert len(closed) == 2


@pytest.mark.asyncio
async def test_recording_stream_close_immediately_returns_inner_budget_slot():
    from unittest.mock import AsyncMock
    from sagents.v2.model import (
        ModelRequest,
        ModelStreamEvent,
        ModelEventKind,
        RecordingModelProvider,
    )

    budget = ModelConcurrencyBudget(1)
    closed = []

    class Provider:
        async def stream(self, request):
            try:
                yield ModelStreamEvent(kind=ModelEventKind.TEXT_DELTA, delta="partial")
            finally:
                closed.append(True)

    provider = RecordingModelProvider(
        budget.wrap(Provider()),
        sink=AsyncMock(),
        session_id_resolver=AsyncMock(return_value="session"),
    )
    stream = provider.stream(
        ModelRequest(
            request_id="request", run_id="run", model_binding="test", messages=()
        )
    )
    await anext(stream)
    assert budget.active == 1
    await stream.aclose()
    assert budget.active == 0
    assert closed == [True]


@pytest.mark.asyncio
async def test_queue_rejects_overflow_without_invoking_provider_and_preserves_fifo():
    from sagents.v2.contracts.errors import SageV2Error

    budget = ModelConcurrencyBudget(1, max_waiting=2)
    entered = []

    async def work(name):
        async with budget.lease():
            entered.append(name)

    async with budget.lease():
        first = asyncio.create_task(work("first"))
        second = asyncio.create_task(work("second"))
        await asyncio.sleep(0)
        with pytest.raises(SageV2Error) as error:
            await work("overflow")
        assert error.value.info.code == "model.queue_full"
        assert error.value.info.retryable and error.value.info.safe_to_resume
        assert budget.waiting == 2
        assert budget.rejected == 1
    await asyncio.gather(first, second)
    assert entered == ["first", "second"]
    assert budget.active == budget.waiting == 0


@pytest.mark.asyncio
async def test_queue_timeout_only_applies_before_provider_admission():
    from sagents.v2.contracts.errors import SageV2Error

    budget = ModelConcurrencyBudget(1, wait_timeout_seconds=0.01)
    async with budget.lease():
        with pytest.raises(SageV2Error) as error:
            async with budget.lease():
                pytest.fail("queued request must not enter provider")
        assert error.value.info.code == "model.queue_timeout"
        assert budget.waiting == 0
        assert budget.active == 1
        assert budget.timed_out == 1
    async with budget.lease():
        # The queue deadline must not cancel an already admitted model call.
        await asyncio.sleep(0.02)
        assert budget.active == 1
    assert budget.active == 0


@pytest.mark.asyncio
async def test_zero_queue_allows_available_slot_but_rejects_waiting():
    from sagents.v2.contracts.errors import SageV2Error

    budget = ModelConcurrencyBudget(1, max_waiting=0)
    async with budget.lease():
        with pytest.raises(SageV2Error, match="queue is full"):
            async with budget.lease():
                pytest.fail("queue disabled")
    async with budget.lease():
        assert budget.active == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"limit": 0},
        {"limit": 1.5},
        {"limit": True},
        {"max_waiting": -1},
        {"max_waiting": 1.5},
        {"wait_timeout_seconds": 0},
        {"wait_timeout_seconds": float("inf")},
        {"wait_timeout_seconds": float("nan")},
    ],
)
def test_invalid_budget_parameters_are_rejected(kwargs):
    with pytest.raises(ValueError):
        ModelConcurrencyBudget(**kwargs)


@pytest.mark.asyncio
async def test_cancel_during_slot_handoff_does_not_lose_capacity():
    budget = ModelConcurrencyBudget(1, max_waiting=1)

    async def waiting():
        async with budget.lease():
            pytest.fail("cancelled waiter must not execute")

    async with budget.lease():
        task = asyncio.create_task(waiting())
        await asyncio.sleep(0)
    # The waiter has been granted capacity, but has not resumed yet.
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert budget.active == budget.waiting == 0
    async with budget.lease():
        assert budget.active == 1


@pytest.mark.asyncio
async def test_provider_timeout_is_not_misclassified_as_queue_timeout():
    budget = ModelConcurrencyBudget(1)

    class Provider:
        async def stream(self, request):
            raise TimeoutError("upstream timed out")
            yield

    with pytest.raises(TimeoutError, match="upstream"):
        async for _ in budget.wrap(Provider()).stream(None):
            pass
    assert budget.timed_out == 0
    assert budget.active == 0

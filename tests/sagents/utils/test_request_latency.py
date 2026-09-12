import asyncio
from types import SimpleNamespace
import pytest
from sagents.utils import request_latency as metrics


@pytest.fixture
def fake_clock(monkeypatch):
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(metrics.time, "perf_counter", lambda: clock.now)
    return clock


def test_parallel_model_waits_are_unioned_and_first_output_is_recorded_once(
    fake_clock, monkeypatch
):
    records = []
    monkeypatch.setattr(metrics, "_emit", records.append)
    budget = metrics.RequestLatency()
    with budget.activate():
        fake_clock.now = 0.2
        with metrics.model_wait(new_call=True):
            fake_clock.now = 0.4
            with metrics.model_wait(new_call=True):
                fake_clock.now = 1.0
            fake_clock.now = 1.2
        fake_clock.now = 1.5
        metrics.record_first_output()
        metrics.record_first_output()
    assert len(records) == 1
    assert records[0]["elapsed_ms"] == 1500
    assert records[0]["model_wait_union_ms"] == 1000
    assert records[0]["non_model_ms"] == 500
    assert records[0]["counts"]["model_calls"] == 2


@pytest.mark.asyncio
async def test_stream_consumer_processing_is_not_model_wait(fake_clock):
    class Stream:
        def __init__(self):
            self.index = 0

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self.index == 2:
                raise StopAsyncIteration
            self.index += 1
            fake_clock.now += 0.1
            return self.index

    budget = metrics.RequestLatency()
    with budget.activate():
        async for value in metrics.observe_stream(Stream(), True):
            fake_clock.now += 0.3  # app processing between received chunks
    payload = budget.snapshot("test")
    assert payload["model_wait_union_ms"] == 200
    assert payload["non_model_ms"] == 600


@pytest.mark.asyncio
async def test_cancellation_balances_wait_and_concurrent_requests_are_isolated():
    started = asyncio.Event()
    one, two = metrics.RequestLatency(), metrics.RequestLatency()

    async def blocked():
        with one.activate():
            with metrics.model_wait(new_call=True):
                started.set()
                await asyncio.Event().wait()

    task = asyncio.create_task(blocked())
    await started.wait()
    with two.activate():
        with metrics.model_wait(new_call=True):
            await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert one.active == two.active == 0
    assert one.model_calls == two.model_calls == 1
    assert metrics._current.get() is None


def test_full_turn_over_budget_is_separate_from_first_output(fake_clock, monkeypatch):
    records = []
    monkeypatch.setattr(metrics, "_emit", records.append)
    budget = metrics.RequestLatency()
    budget.first_output()
    fake_clock.now = 1.1
    budget.finish()
    budget.finish()
    assert [r["operation"] for r in records] == [
        "request.first_output",
        "request.completed",
    ]
    assert records[-1]["non_model_ms"] == 1100
    assert records[-1]["status"] == "slow"


def test_parallel_tools_and_models_excluded_without_double_subtraction(fake_clock):
    budget = metrics.RequestLatency()
    with budget.activate():
        fake_clock.now = 0.1
        with metrics.tool_execution():
            fake_clock.now = 0.2
            with metrics.model_wait(new_call=True):
                fake_clock.now = 1.2
            fake_clock.now = 1.4
        fake_clock.now = 1.6
    p = budget.snapshot("test")
    assert p["model_wait_union_ms"] == 1000
    assert p["tool_execution_union_ms"] == 1300
    assert p["model_or_tool_union_ms"] == 1300
    assert p["framework_overhead_ms"] == 300
    assert p["non_model_ms"] == 600
    assert p["status"] == "ok"

import asyncio
from types import SimpleNamespace
import pytest
from sagents.utils.stream_yield import StreamYieldBudget


@pytest.mark.asyncio
async def test_buffered_stream_preserves_order_and_gives_other_tasks_bounded_turns():
    clock = SimpleNamespace(now=0.0)
    budget = StreamYieldBudget(clock=lambda: clock.now)
    output, observations = [], []
    done = False
    async def observer():
        while not done:
            observations.append(len(output))
            await asyncio.sleep(0)
    watcher = asyncio.create_task(observer())
    for value in range(1000):
        clock.now += .0005  # deterministic simulated per-chunk CPU work
        await budget.checkpoint()
        output.append(value)
    done = True
    await watcher
    assert output == list(range(1000))
    assert 50 < len(observations) < 150  # not one reschedule per chunk
    checkpoints = [0] + observations + [len(output)]
    assert max(b-a for a,b in zip(checkpoints, checkpoints[1:])) <= 12


@pytest.mark.asyncio
async def test_checkpoint_does_not_hide_cancellation():
    clock = SimpleNamespace(now=0.0)
    budget = StreamYieldBudget(clock=lambda: clock.now)
    started = asyncio.Event()
    async def producer():
        started.set()
        for _ in range(1000):
            clock.now += .006
            await budget.checkpoint()
    task = asyncio.create_task(producer())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_network_suspensions_do_not_force_duplicate_yields(monkeypatch):
    from sagents.utils import request_latency as metrics
    request = metrics.RequestLatency()
    clock = SimpleNamespace(now=0.0)
    budget = StreamYieldBudget(clock=lambda: clock.now)
    async def source():
        for i in range(20):
            clock.now += .1  # time spent waiting, not processing
            await asyncio.sleep(0)
            yield i
    seen = []
    with request.activate():
        async for item in budget.iterate(source()):
            clock.now += .0001
            await budget.checkpoint()
            seen.append(item)
    assert seen == list(range(20))
    assert 'stream.scheduler_yield' not in request.stream_stages


@pytest.mark.asyncio
async def test_buffered_sdk_reads_keep_budget_and_yield_to_observer():
    clock = SimpleNamespace(now=0.0)
    budget = StreamYieldBudget(clock=lambda: clock.now)
    seen, turns = [], []
    done = False
    async def source():
        for i in range(1000):
            clock.now += .0005  # synchronous SDK decoding must count too
            yield i
    async def observer():
        while not done:
            turns.append(len(seen))
            await asyncio.sleep(0)
    watcher = asyncio.create_task(observer())
    async for item in budget.iterate(source()):
        await budget.checkpoint()
        seen.append(item)
    done = True
    await watcher
    assert seen == list(range(1000))
    assert 50 < len(turns) < 150
    assert max(b-a for a,b in zip([0]+turns, turns+[1000])) <= 12


@pytest.mark.asyncio
async def test_sdk_cpu_after_real_resume_is_not_excluded():
    from sagents.utils import request_latency as metrics
    request = metrics.RequestLatency()
    clock = SimpleNamespace(now=0.0)
    budget = StreamYieldBudget(clock=lambda: clock.now)
    async def source():
        await asyncio.sleep(0)
        clock.now += .006
        yield 'decoded'
    with request.activate():
        async for item in budget.iterate(source()):
            await budget.checkpoint()
    assert item == 'decoded'
    assert request.stream_stages['stream.scheduler_yield'][0] == 1


@pytest.mark.asyncio
async def test_actual_future_result_exception_and_cancellation_cleanup():
    budget = StreamYieldBudget()
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    started, cleaned = asyncio.Event(), asyncio.Event()
    async def source():
        try:
            started.set()
            yield await future
            raise ValueError('provider error')
        finally:
            await asyncio.sleep(0)
            cleaned.set()
    stream = budget.iterate(source())
    reader = asyncio.create_task(anext(stream))
    await started.wait()
    future.set_result('content')
    assert await reader == 'content'
    with pytest.raises(ValueError, match='provider error'):
        await anext(stream)
    assert cleaned.is_set()

    future = loop.create_future()
    started.clear()
    cleaned.clear()
    stream = budget.iterate(source())
    reader = asyncio.create_task(anext(stream))
    await started.wait()
    reader.cancel()
    with pytest.raises(asyncio.CancelledError):
        await reader
    assert future.cancelled()
    assert cleaned.is_set()

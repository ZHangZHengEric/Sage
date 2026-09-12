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

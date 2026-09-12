import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import threading
import time

from sagents.utils import latency_diagnostics as timing
from sagents.utils import loop_diagnostics as loop_diag


def test_watchdog_captures_blocking_function_without_locals_and_stops(monkeypatch):
    records = []
    monkeypatch.setattr(timing, "_emit", records.append)
    monkeypatch.setenv("SAGE_LATENCY_DIAGNOSTICS", "1")

    def block_loop_for_test():
        secret_local = "MUST_NOT_APPEAR_IN_STACK_RECORD"
        time.sleep(0.30)
        return secret_local

    @timing.diagnose("watchdog.test", 10000)
    async def operation():
        await asyncio.sleep(0.07)
        block_loop_for_test()
        await asyncio.sleep(0.03)

    async def run():
        loop_diag.start_loop_diagnostics()
        monitor = loop_diag.current_monitor()
        try:
            await operation()
            # Once work is done, the watchdog returns to an indefinite event wait.
            await asyncio.sleep(0.07)
            assert not monitor.wake.is_set()
        finally:
            loop_diag.stop_loop_diagnostics()
        assert not monitor.thread.is_alive()

    asyncio.run(run())
    stalls = [r for r in records if r["operation"] == "event_loop.stall"]
    assert len(stalls) == 1
    assert stalls[0]["lag_ms"] >= 100
    assert any(
        f["function"] == "block_loop_for_test" for f in stalls[0]["event_loop_stack"]
    )
    assert "MUST_NOT_APPEAR" not in json.dumps(stalls)
    assert loop_diag.current_monitor() is None


def test_pool_queue_counts_include_waiting_jobs_and_are_cleaned(monkeypatch):
    monkeypatch.setattr(timing, "_emit", lambda payload: None)
    gate = threading.Event()

    @timing.diagnose("queue.test", 10000)
    async def operation():
        tasks = [
            asyncio.create_task(timing.to_thread("queued", lambda: 3)) for _ in range(3)
        ]
        await asyncio.sleep(0.03)
        state = loop_diag.current_monitor().snapshot()
        assert state["pending"] == 3
        assert state["running"] == 0
        assert state["oldest_pending_ms"] >= 15
        assert state["instrumented_jobs_only"] is True
        gate.set()
        assert await asyncio.gather(*tasks) == [3, 3, 3]
        state = loop_diag.current_monitor().snapshot()
        assert state["pending"] == state["running"] == 0

    async def run():
        executor = ThreadPoolExecutor(max_workers=1)
        asyncio.get_running_loop().set_default_executor(executor)
        blocker = executor.submit(gate.wait, 2)
        loop_diag.start_loop_diagnostics()
        try:
            await operation()
        finally:
            gate.set()
            loop_diag.stop_loop_diagnostics()
        blocker.result(2)

    asyncio.run(run())


def test_monitor_maps_and_pending_heartbeat_are_bounded():
    class Loop:
        calls = 0

        def call_soon_threadsafe(self, callback):
            self.calls += 1

    loop = Loop()
    monitor = loop_diag.LoopDiagnostics(loop)
    for i in range(monitor.MAX_JOBS + 4):
        monitor.submit("work")
    assert len(monitor.jobs) == monitor.MAX_JOBS
    assert monitor.snapshot()["untracked_overflow"] == 4
    now = time.perf_counter()
    monitor._sample(now, 0)
    monitor._sample(now + 0.01, 0)
    assert loop.calls == 1


def test_disabled_monitor_creates_no_thread(monkeypatch):
    monkeypatch.setenv("SAGE_LATENCY_DIAGNOSTICS", "0")
    loop_diag.start_loop_diagnostics()
    assert loop_diag.current_monitor() is None

"""Compare old global and per-Run fencing with controlled asynchronous write latency.

No model or external database is involved; results measure the Scheduler fence
bottleneck only. Run: python scripts/benchmark_v2_single_host.py --sessions 64
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import timedelta
import json
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sagents.v2.contracts.common import utc_now
from sagents.v2.runtime.execution.scheduler import InMemoryScheduler, WorkItem


class GlobalFenceBaseline(InMemoryScheduler):
    async def execute_fenced(self, lease, operation):
        # Original critical section before per-Run pins were introduced.
        async with self._condition:
            reaped = self._reap_expired_locked()
            if reaped:
                await self._persist_locked()
            self._assert_fence_locked(lease)
            return await operation()


async def measure(cls, sessions, writes, io_ms):
    scheduler = cls(max_pending_items=max(1024, sessions))
    leases = []
    for index in range(sessions):
        name = f"run-{index}"
        await scheduler.submit(
            WorkItem(
                work_id=name, run_id=name, available_at=utc_now(), idempotency_key=name
            )
        )
        leases.append(
            await scheduler.claim(
                name, lease_duration=timedelta(hours=1), wait_timeout=0
            )
        )
    active = peak = completed = 0
    latencies = []

    async def write():
        nonlocal active, peak, completed
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(io_ms / 1000)
            completed += 1
        finally:
            active -= 1

    async def worker(lease):
        for _ in range(writes):
            started = time.perf_counter()
            await scheduler.execute_fenced(lease, write)
            latencies.append((time.perf_counter() - started) * 1000)

    began = time.perf_counter()
    try:
        await asyncio.gather(*(worker(lease) for lease in leases))
        elapsed = time.perf_counter() - began
        assert completed == sessions * writes
        assert not scheduler._fenced_runs
        ordered = sorted(latencies)
        return {
            "path": "global_baseline" if cls is GlobalFenceBaseline else "per_run",
            "sessions": sessions,
            "writes": completed,
            "simulated_io_ms": io_ms,
            "elapsed_ms": round(elapsed * 1000, 2),
            "peak_concurrent_writes": peak,
            "median_write_ms": round(statistics.median(ordered), 2),
            "p95_write_ms": round(
                ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 2
            ),
        }
    finally:
        await scheduler.close()


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions", type=int, default=64)
    parser.add_argument("--writes", type=int, default=8)
    parser.add_argument("--io-ms", type=float, default=2)
    args = parser.parse_args()
    if min(args.sessions, args.writes, args.io_ms) <= 0:
        parser.error("sessions, writes and io-ms must be positive")
    for cls in (GlobalFenceBaseline, InMemoryScheduler):
        print(
            json.dumps(await measure(cls, args.sessions, args.writes, args.io_ms)),
            flush=True,
        )


if __name__ == "__main__":
    asyncio.run(main())

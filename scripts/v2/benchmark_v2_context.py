"""Synthetic v2 context benchmark, including event-loop lag under concurrency.

Run from the repository root: python scripts/v2/benchmark_v2_context.py
No input-token accounting or model/network calls are performed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from sagents.v2.context import (
    ContextReductionScope,
    InMemoryConversationSummaryStore,
    PersistentSummaryContextReducer,
)
from sagents.v2.contracts.items import TextBlock
from sagents.v2.model import ModelMessage


async def measure(source, sessions, *, compress):
    async def run():
        reducer = PersistentSummaryContextReducer(InMemoryConversationSummaryStore())
        result = await reducer.reduce(
            source,
            scope=ContextReductionScope(
                context_key="benchmark",
                session_id="benchmark",
                run_id="benchmark",
                force=compress,
            ),
        )
        return result.messages

    stop = False
    gaps = []

    async def heartbeat():
        previous = time.perf_counter()
        while not stop:
            await asyncio.sleep(0.005)
            now = time.perf_counter()
            gaps.append(max(0, now - previous - 0.005))
            previous = now

    probe = asyncio.create_task(heartbeat())
    await asyncio.sleep(0)
    started = time.perf_counter()
    results = await asyncio.gather(*(run() for _ in range(sessions)))
    elapsed = time.perf_counter() - started
    await asyncio.sleep(0.006)
    stop = True
    await probe
    return {
        "path": "compress" if compress else "passthrough",
        "sessions": sessions,
        "messages_per_session": len(source),
        "retained": len(results[0]),
        "elapsed_ms": round(elapsed * 1000, 2),
        "max_loop_lag_ms": round(max(gaps, default=0) * 1000, 2),
    }


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--messages", type=int, default=800)
    parser.add_argument("--sessions", type=int, default=8)
    args = parser.parse_args()
    source = tuple(
        ModelMessage(
            role="user" if i % 2 == 0 else "assistant",
            content=(TextBlock(text=f"{i}: " + "historical text " * 100),),
        )
        for i in range(args.messages)
    )
    for sessions in dict.fromkeys((1, args.sessions)):
        for compress in (False, True):
            print(
                json.dumps(await measure(source, sessions, compress=compress)),
                flush=True,
            )


if __name__ == "__main__":
    asyncio.run(main())

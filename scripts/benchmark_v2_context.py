"""Synthetic v2 context benchmark, including event-loop lag under concurrency.

Run from the repository root: python scripts/benchmark_v2_context.py
The baseline reproduces the previous window reducer's repeated JSON accounting
on text-only messages. No model calls, network, persistence or credentials.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sagents.v2.context import (
    ContextBudget,
    JsonHeuristicTokenEstimator,
    WindowContextReducer,
)
from sagents.v2.contracts.items import TextBlock
from sagents.v2.model import ModelMessage


class OriginalEstimator:
    def __init__(self):
        self.visits = 0

    def estimate(self, messages):
        self.visits += len(messages)
        return sum(
            6
            + math.ceil(
                len(
                    json.dumps(
                        message.model_dump(mode="json"),
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    ).encode("utf-8")
                )
                / 4
            )
            for message in messages
        )


class CountingEstimator(JsonHeuristicTokenEstimator):
    def __init__(self):
        super().__init__()
        self.visits = 0

    def estimate(self, messages):
        self.visits += len(messages)
        return super().estimate(messages)


async def measure(source, sessions, *, baseline):
    estimator = OriginalEstimator() if baseline else CountingEstimator()

    async def run():
        if baseline:
            retained = list(source)
            while estimator.estimate(tuple(retained)) > 4000:
                retained.pop(0)
            estimator.estimate(tuple(retained))
            return tuple(retained)
        result = await WindowContextReducer(estimator).reduce(
            source, ContextBudget(max_input_tokens=4000)
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
        "path": "baseline" if baseline else "optimized",
        "sessions": sessions,
        "messages_per_session": len(source),
        "retained": len(results[0]),
        "message_estimates": estimator.visits,
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
        for baseline in (True, False):
            print(
                json.dumps(await measure(source, sessions, baseline=baseline)),
                flush=True,
            )


if __name__ == "__main__":
    asyncio.run(main())

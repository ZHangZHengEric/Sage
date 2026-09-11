"""Offline stream-merge benchmark; no model calls or session writes.

Run with PYTHONPATH=. python scripts/benchmark_stream_message_merge.py.
Optionally compare an older manager module with --baseline-source PATH, or
read a local messages.json snapshot with --messages PATH (contents are never
printed). Each implementation runs in this standalone process only.
"""

from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import time

from sagents.context.messages.message import MessageChunk
from sagents.context.messages.message_manager import MessageManager


def load_manager(path: str):
    spec = importlib.util.spec_from_file_location(
        "sagents.context.messages._benchmark_candidate", path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.MessageManager


def synthetic_history():
    return [
        MessageChunk(
            role="user" if index % 2 == 0 else "assistant",
            content="history " * 400,
            message_id=f"history-{index}",
            metadata={"nested": [{"key": f"value-{item}"} for item in range(16)]},
        )
        for index in range(73)
    ]


async def measure(manager_type, history, chunks):
    loop = asyncio.get_running_loop()
    timer = loop.create_future()
    start = time.perf_counter()
    loop.call_later(0.01, lambda: timer.set_result(time.perf_counter() - start))
    result = manager_type.merge_new_messages_to_old_messages(chunks, history)
    batch_seconds = time.perf_counter() - start
    timer_seconds = await timer
    manager = manager_type()
    manager.messages = deepcopy(history)
    start = time.perf_counter()
    for part in chunks:
        manager.add_messages(part)
    ledger_seconds = time.perf_counter() - start
    assert result == manager.messages
    return {
        "batch_seconds": round(batch_seconds, 6),
        "timer_10ms_actual_seconds": round(timer_seconds, 6),
        "ledger_seconds": round(ledger_seconds, 6),
    }, result


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--messages")
    parser.add_argument("--baseline-source")
    parser.add_argument("--candidate-source")
    parser.add_argument("--chunks", type=int, default=1000)
    args = parser.parse_args()
    history = (
        [
            MessageChunk.from_dict(item)
            for item in json.loads(Path(args.messages).read_text())
        ]
        if args.messages
        else synthetic_history()
    )
    chunks = [
        MessageChunk(role="assistant", content="x", message_id="benchmark-response")
        for _ in range(args.chunks)
    ]
    original = deepcopy(history + chunks)
    report = {"history_messages": len(history), "chunks": len(chunks)}
    baseline_result = None
    if args.baseline_source:
        report["baseline"], baseline_result = await measure(
            load_manager(args.baseline_source), history, chunks
        )
    candidate = (
        load_manager(args.candidate_source) if args.candidate_source else MessageManager
    )
    report["candidate"], result = await measure(candidate, history, chunks)
    assert history + chunks == original, "merge mutated caller-owned messages"
    if baseline_result is not None:
        assert result == baseline_result, "candidate changed merged message semantics"
        report["outputs_equal"] = True
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())

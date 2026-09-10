"""Batch transport writes without changing NDJSON records or their order."""

from __future__ import annotations

import asyncio
import time
from contextlib import aclosing
from typing import Any, AsyncIterator

from loguru import logger


async def batch_stream_chunks(
    source: AsyncIterator[str],
    *,
    session_id: str,
    max_bytes: int = 16 * 1024,
    flush_interval: float = 0.02,
    queue_size: int = 64,
) -> AsyncIterator[str]:
    """Flush at most every 20 ms, also when the producer pauses between tokens.

    The bounded queue applies backpressure to a slow/disconnected consumer.
    Each input remains intact: batching changes HTTP writes, not protocol events.
    """
    if max_bytes <= 0 or flush_interval <= 0 or queue_size <= 0:
        raise ValueError("batch limits must be positive")
    queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue(maxsize=queue_size)
    started = time.monotonic()
    input_chunks = batches = total_bytes = peak_queue = 0

    async def produce() -> None:
        nonlocal input_chunks, peak_queue
        try:
            async with aclosing(source):
                async for chunk in source:
                    await queue.put(("chunk", chunk))
                    input_chunks += 1
                    peak_queue = max(peak_queue, queue.qsize())
        except Exception as exc:
            await queue.put(("error", exc))
        else:
            await queue.put(("end", None))

    producer = asyncio.create_task(produce(), name=f"stream-batch-{session_id}")
    pending: list[str] = []
    pending_bytes = 0
    deadline = 0.0
    try:
        while True:
            try:
                if pending:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise asyncio.TimeoutError
                    if queue.empty():
                        item = await asyncio.wait_for(queue.get(), remaining)
                    else:
                        item = queue.get_nowait()
                else:
                    item = await queue.get()
            except asyncio.TimeoutError:
                batches += 1
                total_bytes += pending_bytes
                yield "".join(pending)
                pending = []
                pending_bytes = 0
                continue

            kind, value = item
            if kind != "chunk":
                if pending:
                    batches += 1
                    total_bytes += pending_bytes
                    yield "".join(pending)
                if kind == "error":
                    raise value
                break
            if not pending:
                deadline = time.monotonic() + flush_interval
            pending.append(value)
            pending_bytes += len(value.encode("utf-8"))
            if pending_bytes >= max_bytes:
                batches += 1
                total_bytes += pending_bytes
                yield "".join(pending)
                pending = []
                pending_bytes = 0
    finally:
        if not producer.done():
            producer.cancel()
        done, unfinished = await asyncio.wait({producer}, timeout=5.0)
        for task in done:
            if not task.cancelled():
                task.exception()
        for task in unfinished:
            task.add_done_callback(
                lambda finished: None if finished.cancelled() else finished.exception()
            )
            logger.bind(session_id=session_id).warning("stream_batch cleanup timed out")
        logger.bind(session_id=session_id).info(
            "stream_delivery chunks={} batches={} bytes={} peak_queue={} elapsed_ms={:.1f}",
            input_chunks, batches, total_bytes, peak_queue,
            (time.monotonic() - started) * 1000,
        )

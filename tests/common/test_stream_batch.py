import asyncio
import json

import pytest

from common.utils.stream_batch import batch_stream_chunks


@pytest.mark.asyncio
async def test_batch_preserves_every_ndjson_record_and_order():
    records = [json.dumps({"content": "你好", "i": i}) + "\n" for i in range(744)]

    async def source():
        for record in records:
            yield record

    batches = [b async for b in batch_stream_chunks(source(), session_id="batch")]
    assert "".join(batches) == "".join(records)
    assert len(batches) < 10


@pytest.mark.asyncio
async def test_batch_flushes_during_producer_pause_and_closes_source():
    closed = asyncio.Event()

    async def source():
        try:
            yield "first\n"
            await asyncio.Future()
        finally:
            closed.set()

    stream = batch_stream_chunks(source(), session_id="pause", flush_interval=0.01)
    assert await asyncio.wait_for(anext(stream), 0.5) == "first\n"
    await stream.aclose()
    assert closed.is_set()


@pytest.mark.asyncio
async def test_slow_consumer_bounds_producer_queue():
    produced = 0
    closed = asyncio.Event()

    async def source():
        nonlocal produced
        try:
            for _ in range(1000):
                produced += 1
                yield "x\n"
        finally:
            closed.set()

    stream = batch_stream_chunks(source(), session_id="bounded", max_bytes=2, queue_size=2)
    assert await anext(stream) == "x\n"
    await asyncio.sleep(0.01)
    assert produced <= 4
    await stream.aclose()
    assert closed.is_set()


@pytest.mark.asyncio
async def test_source_error_preserves_pending_text_and_propagates():
    async def source():
        yield "before error\n"
        raise ValueError("source failed")

    stream = batch_stream_chunks(source(), session_id="error")
    assert await anext(stream) == "before error\n"
    with pytest.raises(ValueError, match="source failed"):
        await anext(stream)

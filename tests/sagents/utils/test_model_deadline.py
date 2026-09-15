import asyncio
from types import SimpleNamespace
import pytest
from sagents.utils.model_deadline import FirstChunkDeadlineStream
from sagents.utils.llm_request_utils import create_chat_completion_with_fallback


@pytest.mark.asyncio
async def test_keepalive_without_model_data_times_out_and_closes():
    closed = []
    async def source():
        try:
            while True:
                await asyncio.sleep(.002)  # SSE comments/keepalives are not model chunks.
            yield
        finally:
            closed.append(True)
    stream = FirstChunkDeadlineStream(source(), asyncio.get_running_loop().time() + .03)
    with pytest.raises(TimeoutError, match="first-chunk timeout"):
        await anext(stream)
    assert closed == [True]


@pytest.mark.asyncio
async def test_first_chunk_deadline_does_not_limit_generation_or_consumer():
    async def source():
        yield "first"
        await asyncio.sleep(.05)
        yield "second"
    stream = FirstChunkDeadlineStream(source(), asyncio.get_running_loop().time() + .03)
    assert await anext(stream) == "first"
    await asyncio.sleep(.05)
    assert await anext(stream) == "second"
    with pytest.raises(StopAsyncIteration):
        await anext(stream)


@pytest.mark.asyncio
async def test_cancel_is_not_converted_to_retryable_timeout():
    entered = asyncio.Event()
    closed = []
    async def source():
        try:
            entered.set()
            await asyncio.Event().wait()
            yield "never"
        finally:
            closed.append(True)
    stream = FirstChunkDeadlineStream(source(), asyncio.get_running_loop().time() + 10)
    task = asyncio.create_task(anext(stream))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed == [True]


@pytest.mark.asyncio
async def test_headers_and_first_chunk_share_one_deadline(monkeypatch):
    monkeypatch.setenv("SAGE_MODEL_FIRST_CHUNK_TIMEOUT_SECONDS", ".06")
    closed = []
    async def body():
        try:
            await asyncio.sleep(.04)
            yield "too late"
        finally:
            closed.append(True)
    async def create(**kwargs):
        await asyncio.sleep(.04)
        return body()
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    stream = await create_chat_completion_with_fallback(client, model="test", messages=[], stream=True)
    with pytest.raises(TimeoutError):
        await anext(stream)
    assert closed == [True]

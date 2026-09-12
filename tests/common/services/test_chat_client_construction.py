import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from common.services import chat_service
from common.schemas.chat import StreamRequest
from sagents.llm import chat


@pytest.mark.asyncio
async def test_model_client_constructed_off_event_loop(monkeypatch):
    main_thread = threading.get_ident()
    client = SimpleNamespace(close=AsyncMock())

    def build(params):
        assert threading.get_ident() != main_thread
        assert params == {"model": "synthetic"}
        return client

    monkeypatch.setattr(chat_service, "create_model_client", build)
    assert (
        await chat_service._create_model_client_off_loop({"model": "synthetic"})
        is client
    )
    client.close.assert_not_called()


@pytest.mark.asyncio
async def test_cancelled_construction_closes_unclaimed_client(monkeypatch):
    started, release = threading.Event(), threading.Event()
    closed = asyncio.Event()
    client = SimpleNamespace(close=AsyncMock(side_effect=closed.set))

    def build(params):
        started.set()
        assert release.wait(3)
        return client

    monkeypatch.setattr(chat_service, "create_model_client", build)
    task = asyncio.create_task(chat_service._create_model_client_off_loop({}))
    try:
        assert await asyncio.to_thread(started.wait, 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
    await asyncio.wait_for(closed.wait(), 2)
    client.close.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fast_key, fast_url, expected",
    [(None, None, 1), ("different", None, 2), (None, "https://other.invalid", 2)],
)
async def test_dual_models_share_only_identical_provider_clients(
    monkeypatch, fast_key, fast_url, expected
):
    created = []

    def build(**kwargs):
        client = SimpleNamespace(close=AsyncMock(), **kwargs)
        created.append(client)
        return client

    monkeypatch.setattr(chat, "_create_openai_client", build)
    model = chat.OpenAIChat(
        api_key="synthetic",
        base_url="https://provider.invalid",
        model_name="standard",
        fast_model_name="fast",
        fast_api_key=fast_key,
        fast_base_url=fast_url,
    )
    assert len(created) == expected
    assert model.raw_client.fast_model_name == "fast"
    await model.close()
    for client in created:
        client.close.assert_awaited_once()


def test_latency_state_cannot_be_supplied_or_serialized_as_request_payload():
    request = StreamRequest(messages=[], _latency_budget="untrusted")
    assert request._latency_budget is None
    chat_service.mark_request_execution(request, request_source="test")
    assert request._latency_budget is not None
    assert "_latency_budget" not in request.model_dump()


@pytest.mark.asyncio
async def test_cancelled_prepare_releases_session_lock(monkeypatch):
    request = StreamRequest(
        messages=[], session_id="cancel-preparation", llm_model_config={}
    )
    lock = asyncio.Lock()
    monkeypatch.setattr(chat_service, "get_session_run_lock", lambda sid: lock)
    monkeypatch.setattr(
        chat_service, "SageStreamService", lambda request, **kw: SimpleNamespace()
    )
    monkeypatch.setattr(
        chat_service,
        "_create_model_client_off_loop",
        AsyncMock(side_effect=asyncio.CancelledError),
    )
    with pytest.raises(asyncio.CancelledError):
        await chat_service.prepare_session(request)
    assert not lock.locked()


@pytest.mark.asyncio
async def test_service_latency_scope_can_close_in_another_task(monkeypatch):
    from sagents.utils import request_latency

    monkeypatch.setattr(request_latency, "_emit", lambda payload: None)
    service = object.__new__(chat_service.SageStreamService)
    service.latency_budget = request_latency.RequestLatency()
    closed = asyncio.Event()

    async def inner():
        try:
            assert request_latency._current.get() is service.latency_budget
            request_latency.record_first_output()
            yield "chunk"
        finally:
            closed.set()

    service._process_stream = inner
    stream = service.process_stream()
    assert await anext(stream) == "chunk"
    assert request_latency._current.get() is None
    await asyncio.create_task(stream.aclose())
    assert closed.is_set()
    assert service.latency_budget.finished


@pytest.mark.asyncio
async def test_startup_warmup_constructs_and_closes_without_model_call(monkeypatch):
    client = SimpleNamespace(close=AsyncMock())
    factory = AsyncMock(return_value=client)
    monkeypatch.setattr(chat_service, '_create_model_client_off_loop', factory)
    await chat_service.warmup_model_client()
    factory.assert_awaited_once()
    assert factory.call_args.args[0]['base_url'] == 'https://sdk-warmup.invalid/v1'
    client.close.assert_awaited_once()

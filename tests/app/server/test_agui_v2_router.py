from __future__ import annotations

import asyncio
import json

import pytest
from ag_ui.core import RunAgentInput

from app.server.routers.agui_v2 import (
    _BACKGROUND_RUNS,
    _ensure_thread_access,
    _persist_agui_events,
    _to_stream_request,
    agui_v2_router,
    chat_v2,
)
from common.core.exceptions import SageHTTPException
from common.services.agui_v2_run_store import AguiRun, AguiV2RunStore
from starlette.requests import Request


def _input(**overrides) -> RunAgentInput:
    payload = {
        "threadId": "thread-1",
        "runId": "run-1",
        "state": {},
        "messages": [
            {"id": "old", "role": "user", "content": "do not replay"},
            {
                "id": "latest",
                "role": "user",
                "content": [
                    {"type": "text", "text": "看图"},
                    {
                        "type": "image",
                        "source": {
                            "type": "url",
                            "value": "https://example.invalid/image.png",
                        },
                    },
                ],
            },
        ],
        "tools": [],
        "context": [],
        "forwardedProps": {
            "agentId": "agent-1",
            "systemContext": {"scope": {"materialIds": ["material-1"]}},
            "providerId": "provider-1",
            "agentMode": "team",
            "maxLoopCount": 9,
            "moreSuggest": True,
            "availableSubAgentIds": ["agent-2"],
            "sandboxApprovalMode": "on-request",
        },
    }
    payload.update(overrides)
    return RunAgentInput.model_validate(payload)


def test_v2_router_adds_only_the_new_agui_chat_path() -> None:
    paths = {route.path for route in agui_v2_router.routes}

    assert paths == {"/api/v2/agent/chat"}


def test_agui_input_uses_authenticated_user_and_latest_user_message() -> None:
    request = _to_stream_request(_input(), user_id="authenticated-user")

    assert request.session_id == "thread-1"
    assert request.user_id == "authenticated-user"
    assert request.agent_id == "agent-1"
    assert request.provider_id == "provider-1"
    assert request.agent_mode == "team"
    assert request.max_loop_count == 9
    assert request.more_suggest is True
    assert request.available_sub_agent_ids == ["agent-2"]
    assert request.sandbox_approval_mode is None
    assert request.command_policy is None
    assert request.system_context == {"scope": {"materialIds": ["material-1"]}}
    assert [message.message_id for message in request.messages] == ["latest"]
    assert request.messages[0].content == [
        {"type": "text", "text": "看图"},
        {
            "type": "image_url",
            "image_url": {"url": "https://example.invalid/image.png"},
        },
    ]


def test_agui_input_requires_agent_id_and_user_message() -> None:
    with pytest.raises(ValueError, match="agentId"):
        _to_stream_request(
            _input(messages=[], forwardedProps={}),
            user_id="authenticated-user",
        )


def test_agui_input_rejects_unbounded_run_identifiers() -> None:
    with pytest.raises(ValueError, match="runId"):
        _to_stream_request(
            _input(runId="r" * 257),
            user_id="authenticated-user",
        )


@pytest.mark.asyncio
async def test_existing_thread_is_hidden_from_other_users(monkeypatch) -> None:
    import app.server.routers.agui_v2 as router

    class Conversation:
        user_id = "owner-user"

    class Dao:
        async def get_by_session_id(self, session_id):
            assert session_id == "thread-1"
            return Conversation()

    monkeypatch.setattr(router, "ConversationDao", Dao)

    with pytest.raises(Exception) as captured:
        await _ensure_thread_access("thread-1", "other-user")

    assert getattr(captured.value, "status_code", None) == 404


@pytest.mark.asyncio
async def test_native_stream_is_persisted_as_terminal_agui_sequence() -> None:
    published: list[dict] = []
    finished: list[str] = []

    class Store:
        async def publish(self, _run, event):
            published.append(event)

        async def finish(self, _run, *, status):
            finished.append(status)

    async def source():
        yield (
            json.dumps(
                {
                    "role": "assistant",
                    "type": "assistant_text",
                    "message_id": "answer-1",
                    "content": "hello",
                }
            )
            + "\n"
        )
        yield json.dumps({"type": "stream_end"}) + "\n"

    run = AguiRun(run_id="run-1", user_id="user-1", thread_id="thread-1")
    await _persist_agui_events(Store(), run, source())

    assert [event["type"] for event in published] == [
        "TEXT_MESSAGE_START",
        "TEXT_MESSAGE_CONTENT",
        "TEXT_MESSAGE_END",
        "RUN_FINISHED",
    ]
    assert finished == ["completed"]


@pytest.mark.asyncio
async def test_run_finishes_before_native_generator_finalizer_returns() -> None:
    published: list[dict] = []
    finished: list[str] = []
    finalizer_started = asyncio.Event()
    release_finalizer = asyncio.Event()

    class Store:
        async def publish(self, _run, event):
            published.append(event)

        async def finish(self, _run, *, status):
            finished.append(status)

    async def source():
        try:
            yield json.dumps({"role": "assistant", "content": "done"}) + "\n"
            yield json.dumps({"type": "stream_end"}) + "\n"
        finally:
            finalizer_started.set()
            await release_finalizer.wait()

    run = AguiRun(run_id="run-1", user_id="user-1", thread_id="thread-1")
    task = asyncio.create_task(_persist_agui_events(Store(), run, source()))
    try:
        await asyncio.wait_for(finalizer_started.wait(), timeout=1)
        assert any(event["type"] == "RUN_FINISHED" for event in published)
        assert finished == ["completed"]
        assert not task.done()
    finally:
        release_finalizer.set()
        await task


@pytest.mark.asyncio
async def test_repeated_run_id_rejoins_without_starting_the_model_twice(
    monkeypatch,
) -> None:
    import app.server.routers.agui_v2 as router

    store = AguiV2RunStore(ttl_seconds=60, heartbeat_seconds=0.01)
    prepare_count = 0

    def validate(*_args, **_kwargs):
        return None

    async def guard(_request):
        return None

    async def allow_thread(_thread_id, _user_id):
        return None

    async def populate(_request, *, require_agent_id):
        assert require_agent_id is True

    async def prepare(_request):
        nonlocal prepare_count
        prepare_count += 1
        lock = asyncio.Lock()
        await lock.acquire()
        return object(), lock

    async def execute(*, stream_service):
        assert stream_service is not None
        yield json.dumps({"role": "assistant", "content": "done"}) + "\n"
        yield json.dumps({"type": "stream_end"}) + "\n"

    monkeypatch.setattr(router, "get_agui_v2_run_store", lambda: store)
    monkeypatch.setattr(router, "validate_and_prepare_request", validate)
    monkeypatch.setattr(router, "_ensure_thread_access", allow_thread)
    monkeypatch.setattr(router, "_guard_request_multimodal_images", guard)
    monkeypatch.setattr(
        router.chat_service, "mark_request_execution", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        router.chat_service, "populate_request_from_agent_config", populate
    )
    monkeypatch.setattr(router.chat_service, "prepare_session", prepare)
    monkeypatch.setattr(router.chat_service, "execute_chat_session", execute)
    monkeypatch.setattr(router, "delete_session_run_lock", lambda _session_id: None)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v2/agent/chat",
        "headers": [],
    }
    http_request = Request(scope)
    http_request.state.user_claims = {"userid": "user-1"}

    first = await chat_v2(_input(), http_request)
    if _BACKGROUND_RUNS:
        await asyncio.gather(*tuple(_BACKGROUND_RUNS))
    repeated = await chat_v2(_input(), http_request)

    assert first.media_type == "text/event-stream"
    assert repeated.media_type == "text/event-stream"
    assert prepare_count == 1


@pytest.mark.asyncio
async def test_active_sage_thread_is_reported_as_agui_run_conflict(monkeypatch) -> None:
    import app.server.routers.agui_v2 as router

    store = AguiV2RunStore(ttl_seconds=60)

    async def allow_thread(_thread_id, _user_id):
        return None

    async def guard(_request):
        return None

    async def populate(_request, *, require_agent_id):
        assert require_agent_id is True

    async def prepare(_request):
        raise SageHTTPException(message_key="chat.session_running")

    monkeypatch.setattr(router, "get_agui_v2_run_store", lambda: store)
    monkeypatch.setattr(router, "_ensure_thread_access", allow_thread)
    monkeypatch.setattr(
        router, "validate_and_prepare_request", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(router, "_guard_request_multimodal_images", guard)
    monkeypatch.setattr(
        router.chat_service, "mark_request_execution", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        router.chat_service, "populate_request_from_agent_config", populate
    )
    monkeypatch.setattr(router.chat_service, "prepare_session", prepare)

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v2/agent/chat",
            "headers": [],
        }
    )
    request.state.user_claims = {"userid": "user-1"}

    with pytest.raises(SageHTTPException) as captured:
        await chat_v2(_input(), request)

    assert captured.value.status_code == 409

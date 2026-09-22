from __future__ import annotations

import asyncio

import pytest
from ag_ui.core import RunAgentInput

from app.server_v2.agui.mapping import to_start_run
from app.server_v2.agui.sse import (
    ClientOwnedUserTextFilter,
    canonical_agui_sse,
    frame_to_agui_event,
)
from app.server_v2.core.errors import ServerV2Error
from sagents.v2.interfaces.protocols.contracts import ProtocolFrame


def _input(**overrides) -> RunAgentInput:
    payload = {
        "threadId": "thread-1",
        "runId": "run-1",
        "state": {},
        "messages": [{"id": "m1", "role": "user", "content": "hello"}],
        "tools": [],
        "context": [],
        "forwardedProps": {"agentId": "main"},
    }
    payload.update(overrides)
    return RunAgentInput.model_validate(payload)


def test_maps_latest_user_message_and_ids():
    thread_id, run_id, agent_id, command = to_start_run(
        _input(
            messages=[
                {"id": "old", "role": "user", "content": "ignore"},
                {"id": "new", "role": "user", "content": "hello"},
            ]
        ),
        composition_hash="sha256:test",
        default_agent_id="main",
    )
    assert thread_id == "thread-1"
    assert run_id == "run-1"
    assert agent_id == "main"
    assert command.session_id == "thread-1"
    assert command.idempotency_key == "run-1"
    assert command.input[0].content[0].text == "hello"
    assert command.config.enabled_skills is None


def test_maps_enabled_skills_from_catalog_bindings():
    *_, command = to_start_run(
        _input(),
        composition_hash="sha256:test",
        default_agent_id="main",
        enabled_skills=("demo",),
    )
    assert command.config.enabled_skills == ("demo",)


def test_rejects_invalid_run_id():
    with pytest.raises(ServerV2Error):
        to_start_run(
            _input(runId="r" * 200),
            composition_hash="sha256:test",
            default_agent_id="main",
        )


def test_rewrites_client_run_identity():
    frame = ProtocolFrame(
        protocol="ag-ui",
        protocol_version="0.1",
        frame_kind="event",
        name="RUN_STARTED",
        payload={"threadId": "sage-session", "runId": "sage-run"},
        source_event_id="event_1",
        source_run_sequence=1,
    )
    event = frame_to_agui_event(frame, thread_id="thread-1", run_id="run-1")
    assert event == {
        "type": "RUN_STARTED",
        "threadId": "thread-1",
        "runId": "run-1",
    }


def test_skips_client_owned_user_text_but_keeps_assistant():
    filt = ClientOwnedUserTextFilter()
    assert filt.allow({"type": "TEXT_MESSAGE_START", "messageId": "u1", "role": "user"}) is False
    assert filt.allow({"type": "TEXT_MESSAGE_CONTENT", "messageId": "u1", "delta": "hi"}) is False
    assert filt.allow({"type": "TEXT_MESSAGE_END", "messageId": "u1"}) is False
    assert filt.allow({"type": "TEXT_MESSAGE_START", "messageId": "a1", "role": "assistant"}) is True
    assert filt.allow({"type": "TEXT_MESSAGE_CONTENT", "messageId": "a1", "delta": "hello"}) is True
    assert filt.allow({"type": "RUN_ERROR", "message": "no model"}) is True


@pytest.mark.asyncio
async def test_canonical_stream_keeps_idle_connection_alive():
    async def delayed_events():
        await asyncio.Event().wait()
        if False:
            yield None

    stream = canonical_agui_sse(
        delayed_events(),
        thread_id="thread-1",
        run_id="run-1",
        last_event_id=None,
        heartbeat_seconds=0.001,
    )

    assert await anext(stream) == ": heartbeat\n\n"
    await stream.aclose()

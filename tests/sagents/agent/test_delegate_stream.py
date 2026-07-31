import asyncio
import json

import pytest

from sagents.agent.fibre.delegate_stream import (
    ChildSessionObservation,
    consume_backend_child_stream,
    load_child_history_fallback,
    merge_history_with_fallback,
)
from sagents.context.messages.message import MessageChunk


class _HangingBackendClient:
    """Yields one batch then blocks until the consumer task is cancelled."""

    def __init__(self):
        self.was_cancelled = False
        self.messages = None

    async def stream_chat(self, **kwargs):
        self.messages = kwargs.get("messages")
        yield [
            MessageChunk(
                role="assistant",
                content="child working",
                type="assistant_text",
                session_id=kwargs.get("session_id"),
            )
        ]
        try:
            # Hang forever to simulate missing HTTP EOF.
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.was_cancelled = True
            raise


class _StreamEndBackendClient:
    async def stream_chat(self, **kwargs):
        yield [
            MessageChunk(
                role="assistant",
                content="almost done",
                type="assistant_text",
                session_id=kwargs.get("session_id"),
            )
        ]
        yield [{"type": "stream_end", "session_id": kwargs.get("session_id")}]
        # Would hang if helper kept waiting on EOF after stream_end.
        await asyncio.Event().wait()


class _SilentHangingBackendClient:
    """Never yields chunks; hangs until cancelled (stale-completed reuse)."""

    def __init__(self):
        self.was_cancelled = False

    async def stream_chat(self, **kwargs):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.was_cancelled = True
            raise
        yield []  # pragma: no cover — unreachable


@pytest.mark.asyncio
async def test_consume_completes_when_child_terminal_even_without_http_eof(
    monkeypatch,
):
    client = _HangingBackendClient()
    published = []
    observations = iter(
        [
            ChildSessionObservation(status="completed", persisted_revision="old"),
            ChildSessionObservation(status="running", request_id="req-new"),
            ChildSessionObservation(status="completed", request_id="req-new"),
        ]
    )

    monkeypatch.setattr(
        "sagents.agent.fibre.delegate_stream.read_child_session_observation",
        lambda session_id, parent_session_id=None: next(
            observations,
            ChildSessionObservation(status="completed", request_id="req-new"),
        ),
    )

    async def on_chunks(chunks):
        published.extend(chunks)

    result = await consume_backend_child_stream(
        backend_client=client,
        agent_id="video-asset-agent",
        messages=[{"role": "user", "content": "hi"}],
        session_id="parent_sub_1",
        parent_session_id="parent",
        max_loop_count=3,
        on_chunks=on_chunks,
        watch_poll_seconds=0.01,
    )

    assert result.reason == "child_terminal"
    assert result.child_status == "completed"
    assert any(
        isinstance(c, MessageChunk) and c.content == "child working" for c in published
    )
    assert client.messages[0]["metadata"]["delegate_round_id"] == result.round_id
    assert client.was_cancelled


@pytest.mark.asyncio
async def test_stale_completed_status_does_not_finish_before_round_is_active(
    monkeypatch,
):
    """Reusing a completed *_sub_* must not treat prior completed as this round."""

    client = _SilentHangingBackendClient()
    monkeypatch.setattr(
        "sagents.agent.fibre.delegate_stream.read_child_session_observation",
        lambda session_id, parent_session_id=None: ChildSessionObservation(
            status="completed", persisted_revision="old"
        ),
    )

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(
            consume_backend_child_stream(
                backend_client=client,
                agent_id="interaction-agent",
                messages=[{"role": "user", "content": "redo interaction"}],
                session_id="parent_sub_2_sub_3",
                parent_session_id="parent_sub_2",
                max_loop_count=3,
                watch_poll_seconds=0.01,
            ),
            timeout=0.15,
        )


@pytest.mark.asyncio
async def test_stale_completed_status_is_not_unlocked_by_stream_chunks(monkeypatch):
    client = _HangingBackendClient()
    monkeypatch.setattr(
        "sagents.agent.fibre.delegate_stream.read_child_session_observation",
        lambda session_id, parent_session_id=None: ChildSessionObservation(
            status="completed", persisted_revision="old"
        ),
    )

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(
            consume_backend_child_stream(
                backend_client=client,
                agent_id="interaction-agent",
                messages=[{"role": "user", "content": "redo interaction"}],
                session_id="parent_sub_2_sub_3",
                parent_session_id="parent_sub_2",
                max_loop_count=3,
                watch_poll_seconds=0.01,
            ),
            timeout=0.15,
        )


@pytest.mark.asyncio
async def test_new_persisted_revision_accepts_fast_terminal_without_running(
    monkeypatch,
):
    client = _SilentHangingBackendClient()
    observations = iter(
        [
            ChildSessionObservation(status="completed", persisted_revision="old"),
            ChildSessionObservation(status="completed", persisted_revision="new"),
        ]
    )
    monkeypatch.setattr(
        "sagents.agent.fibre.delegate_stream.read_child_session_observation",
        lambda session_id, parent_session_id=None: next(
            observations,
            ChildSessionObservation(status="completed", persisted_revision="new"),
        ),
    )

    result = await asyncio.wait_for(
        consume_backend_child_stream(
            backend_client=client,
            agent_id="interaction-agent",
            messages=[{"role": "user", "content": "fast redo"}],
            session_id="parent_sub_2_sub_3",
            parent_session_id="parent_sub_2",
            max_loop_count=3,
            watch_poll_seconds=0.01,
        ),
        timeout=1.0,
    )

    assert result.reason == "child_terminal"
    assert result.child_status == "completed"
    assert client.was_cancelled


@pytest.mark.asyncio
async def test_reused_completed_session_waits_for_running_then_terminal(
    monkeypatch,
):
    client = _HangingBackendClient()
    observations = iter(
        [
            ChildSessionObservation(status="completed", persisted_revision="old"),
            ChildSessionObservation(status="completed", persisted_revision="old"),
            ChildSessionObservation(status="running", request_id="req-new"),
            ChildSessionObservation(status="completed", request_id="req-new"),
        ]
    )
    observed_statuses = []

    def read_observation(session_id, parent_session_id=None):
        observation = next(
            observations,
            ChildSessionObservation(status="completed", request_id="req-new"),
        )
        observed_statuses.append(observation.status)
        return observation

    monkeypatch.setattr(
        "sagents.agent.fibre.delegate_stream.read_child_session_observation",
        read_observation,
    )

    result = await asyncio.wait_for(
        consume_backend_child_stream(
            backend_client=client,
            agent_id="interaction-agent",
            messages=[{"role": "user", "content": "redo"}],
            session_id="parent_sub_2_sub_3",
            parent_session_id="parent_sub_2",
            max_loop_count=3,
            watch_poll_seconds=0.01,
        ),
        timeout=2.0,
    )
    assert result.reason == "child_terminal"
    assert result.child_status == "completed"
    assert "running" in observed_statuses
    assert client.was_cancelled


@pytest.mark.asyncio
async def test_consume_completes_on_stream_end_without_waiting_for_eof():
    client = _StreamEndBackendClient()
    result = await asyncio.wait_for(
        consume_backend_child_stream(
            backend_client=client,
            agent_id="agent",
            messages=[{"role": "user", "content": "hi"}],
            session_id="child",
            max_loop_count=3,
            watch_poll_seconds=0.5,
        ),
        timeout=2.0,
    )
    assert result.reason == "stream_end"
    assert result.batch_count == 2


def test_load_child_history_fallback_from_messages_json(tmp_path, monkeypatch):
    session_id = "parent_sub_1"
    workspace = tmp_path / "sub_sessions" / session_id
    workspace.mkdir(parents=True)
    messages = [
        {
            "role": "assistant",
            "content": "old turn answer",
            "type": "do_subtask_result",
            "session_id": session_id,
            "message_id": "old-message",
        },
        {
            "role": "assistant",
            "content": "new turn summary",
            "type": "do_subtask_result",
            "session_id": session_id,
            "message_id": "new-message",
            "metadata": {"delegate_round_id": "round-new"},
        },
    ]
    (workspace / "messages.json").write_text(
        json.dumps(messages, ensure_ascii=False), encoding="utf-8"
    )

    monkeypatch.setattr(
        "sagents.agent.fibre.delegate_stream.resolve_child_workspace",
        lambda sid, parent_session_id=None: str(workspace),
    )

    history = load_child_history_fallback(session_id, parent_session_id="parent")
    assert "old turn answer" in history
    assert "new turn summary" in history

    # Without a pre-round checkpoint, a non-empty stream must never be replaced
    # by an ambiguous full ledger.
    merged_new_turn = merge_history_with_fallback(
        "new turn summary",
        session_id,
        parent_session_id="parent",
    )
    assert merged_new_turn == "new turn summary"

    # With a pre-round checkpoint, fallback may recover the current round only.
    merged_current_round = merge_history_with_fallback(
        "new turn summary",
        session_id,
        parent_session_id="parent",
        round_id="round-new",
    )
    assert "old turn answer" not in merged_current_round
    assert "new turn summary" in merged_current_round

    # A truncated current-round stream may use the longer scoped fallback.
    merged_truncated = merge_history_with_fallback(
        "new turn",
        session_id,
        parent_session_id="parent",
        round_id="round-new",
    )
    assert "old turn answer" not in merged_truncated
    assert "new turn summary" in merged_truncated

import asyncio
import json

import pytest

from sagents.agent.fibre.delegate_stream import (
    consume_backend_child_stream,
    load_child_history_fallback,
    merge_history_with_fallback,
)
from sagents.context.messages.message import MessageChunk


class _HangingBackendClient:
    """Yields one batch then blocks until the consumer task is cancelled."""

    def __init__(self):
        self.was_cancelled = False

    async def stream_chat(self, **kwargs):
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


@pytest.mark.asyncio
async def test_consume_completes_when_child_terminal_even_without_http_eof(
    monkeypatch,
):
    client = _HangingBackendClient()
    published = []

    monkeypatch.setattr(
        "sagents.agent.fibre.delegate_stream.read_child_session_status",
        lambda session_id, parent_session_id=None: "completed",
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
    assert len(result.chunk_batches) == 2


def test_load_child_history_fallback_from_messages_json(tmp_path, monkeypatch):
    session_id = "parent_sub_1"
    workspace = tmp_path / "sub_sessions" / session_id
    workspace.mkdir(parents=True)
    messages = [
        {
            "role": "assistant",
            "content": "final child answer",
            "type": "do_subtask_result",
            "session_id": session_id,
        }
    ]
    (workspace / "messages.json").write_text(
        json.dumps(messages, ensure_ascii=False), encoding="utf-8"
    )

    monkeypatch.setattr(
        "sagents.agent.fibre.delegate_stream.resolve_child_workspace",
        lambda sid, parent_session_id=None: str(workspace),
    )

    history = load_child_history_fallback(session_id, parent_session_id="parent")
    assert "final child answer" in history

    merged = merge_history_with_fallback(
        "short",
        session_id,
        parent_session_id="parent",
    )
    assert "final child answer" in merged

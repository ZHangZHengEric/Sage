import asyncio
import json
import sys
from types import SimpleNamespace

import pytest

from sagents.agent.fibre.backend_client import FibreBackendClient
from sagents.context.messages.message import MessageChunk


class _FakeContent:
    def __init__(self, chunks):
        # Accept either NDJSON text lines or raw byte chunks.
        encoded = []
        for chunk in chunks:
            if isinstance(chunk, (bytes, bytearray)):
                encoded.append(bytes(chunk))
            else:
                text = str(chunk)
                if not text.endswith("\n"):
                    text += "\n"
                encoded.append(text.encode("utf-8"))
        self._lines = encoded

    def __aiter__(self):
        self._iter = iter(self._lines)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


class _FakeResponse:
    status = 200

    def __init__(self, lines):
        self.content = _FakeContent(lines)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeClientSession:
    def __init__(self, lines):
        self._lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def post(self, *args, **kwargs):
        return _FakeResponse(self._lines)


@pytest.mark.asyncio
async def test_backend_client_preserves_roleless_control_events(monkeypatch):
    lines = [
        json.dumps(
            {"type": "stream_end", "session_id": "child", "total_stream_count": 2}
        ),
        json.dumps(
            {
                "role": "assistant",
                "type": "assistant_text",
                "content": "done",
                "message_id": "m-child",
                "session_id": "child",
            }
        ),
    ]
    monkeypatch.setitem(
        sys.modules,
        "aiohttp",
        SimpleNamespace(ClientSession=lambda: _FakeClientSession(lines)),
    )

    client = FibreBackendClient()
    client.base_url = "http://localhost:1"
    client._available = True

    received = []
    async for chunks in client.stream_chat(
        agent_id="agent",
        messages=[{"role": "user", "content": "hi"}],
        session_id="child",
        max_loop_count=3,
    ):
        received.extend(chunks)

    assert received[0]["type"] == "stream_end"
    assert received[0]["session_id"] == "child"
    assert isinstance(received[1], MessageChunk)
    assert received[1].content == "done"


@pytest.mark.asyncio
async def test_backend_client_backfills_session_id_for_complete_role_messages(
    monkeypatch,
):
    lines = [
        json.dumps(
            {
                "role": "assistant",
                "type": "token_usage",
                "content": "",
                "message_id": "m-token",
                "metadata": {"session_id": "child", "token_usage": {}},
            }
        ),
        json.dumps(
            {
                "role": "assistant",
                "type": "assistant_text",
                "content": "done",
                "message_id": "m-child",
            }
        ),
    ]
    monkeypatch.setitem(
        sys.modules,
        "aiohttp",
        SimpleNamespace(ClientSession=lambda: _FakeClientSession(lines)),
    )

    client = FibreBackendClient()
    client.base_url = "http://localhost:1"
    client._available = True

    received = []
    async for chunks in client.stream_chat(
        agent_id="agent",
        messages=[{"role": "user", "content": "hi"}],
        session_id="child",
        max_loop_count=3,
    ):
        received.extend(chunks)

    assert all(isinstance(item, MessageChunk) for item in received)
    assert [item.session_id for item in received] == ["child", "child"]


@pytest.mark.asyncio
async def test_backend_client_reassembles_ndjson_split_across_tcp_chunks(monkeypatch):
    payload = {
        "role": "assistant",
        "type": "assistant_text",
        "content": "reassembled",
        "message_id": "m-split",
        "session_id": "child",
    }
    raw = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
    chunks = [raw[:17], raw[17:40], raw[40:]]
    assert b"".join(chunks) == raw

    monkeypatch.setitem(
        sys.modules,
        "aiohttp",
        SimpleNamespace(ClientSession=lambda: _FakeClientSession(chunks)),
    )

    client = FibreBackendClient()
    client.base_url = "http://localhost:1"
    client._available = True

    received = []
    async for batch in client.stream_chat(
        agent_id="agent",
        messages=[{"role": "user", "content": "hi"}],
        session_id="child",
        max_loop_count=3,
    ):
        received.extend(batch)

    assert len(received) == 1
    assert isinstance(received[0], MessageChunk)
    assert received[0].content == "reassembled"


@pytest.mark.asyncio
async def test_backend_client_stops_when_cancel_event_set(monkeypatch):
    lines = [
        json.dumps(
            {
                "role": "assistant",
                "type": "assistant_text",
                "content": "one",
                "message_id": "m1",
            }
        ),
        json.dumps(
            {
                "role": "assistant",
                "type": "assistant_text",
                "content": "two",
                "message_id": "m2",
            }
        ),
    ]

    class _CancelAwareContent(_FakeContent):
        def __init__(self, chunks, cancel_event):
            super().__init__(chunks)
            self._cancel_event = cancel_event
            self._index = 0

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self._index >= len(self._lines):
                raise StopAsyncIteration
            if self._index == 1:
                self._cancel_event.set()
            item = self._lines[self._index]
            self._index += 1
            await asyncio.sleep(0)
            return item

    cancel_event = asyncio.Event()

    class _CancelSession(_FakeClientSession):
        def post(self, *args, **kwargs):
            response = _FakeResponse(self._lines)
            response.content = _CancelAwareContent(self._lines, cancel_event)
            return response

    monkeypatch.setitem(
        sys.modules,
        "aiohttp",
        SimpleNamespace(ClientSession=lambda: _CancelSession(lines)),
    )

    client = FibreBackendClient()
    client.base_url = "http://localhost:1"
    client._available = True

    received = []
    async for batch in client.stream_chat(
        agent_id="agent",
        messages=[{"role": "user", "content": "hi"}],
        session_id="child",
        max_loop_count=3,
        cancel_event=cancel_event,
    ):
        received.extend(batch)

    assert [item.content for item in received if isinstance(item, MessageChunk)] == [
        "one"
    ]

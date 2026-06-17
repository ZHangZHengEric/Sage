import json
import sys
from types import SimpleNamespace

import pytest

from sagents.agent.fibre.backend_client import FibreBackendClient
from sagents.context.messages.message import MessageChunk


class _FakeContent:
    def __init__(self, lines):
        self._lines = [line.encode("utf-8") for line in lines]

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
        json.dumps({"type": "stream_end", "session_id": "child", "total_stream_count": 2}),
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

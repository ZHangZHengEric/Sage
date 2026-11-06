"""Host-boundary tests; AstrBot remains an optional external application."""

from __future__ import annotations

import importlib
import json
import logging
import sys
from dataclasses import dataclass
from types import ModuleType, SimpleNamespace

import httpx
import pytest

from tests.integrations.test_astrbot_bridge import MemoryStore, config, task


@dataclass
class Plain:
    text: str


@dataclass
class Image:
    path: str

    async def convert_to_file_path(self):
        return self.path


@dataclass
class At:
    qq: str


@dataclass
class Reply:
    message_str: str


class Event:
    def __init__(
        self,
        *,
        sender="alice",
        platform="lark-team-a",
        private=True,
        wake=False,
        text="hi",
        components=None,
    ):
        self.sender = sender
        self.platform = platform
        self.private = private
        self.is_at_or_wake_command = wake
        self.message_str = text
        self.components = components if components is not None else [Plain(text)]
        self.message_obj = SimpleNamespace(message_id="message-1")
        self.unified_msg_origin = f"{platform}:GroupMessage:group-1"
        self.stopped = False
        self.llm = True
        self.sent = []

    def get_platform_id(self):
        return self.platform

    def get_sender_id(self):
        return self.sender

    def get_self_id(self):
        return "bot-1"

    def is_private_chat(self):
        return self.private

    def get_messages(self):
        return self.components

    def plain_result(self, text):
        return text

    def should_call_llm(self, enabled):
        self.llm = enabled

    def stop_event(self):
        self.stopped = True

    async def send(self, message):
        self.sent.append(message)


@pytest.fixture
def plugin_class(monkeypatch):
    """Replace only the optional host API, retaining all bridge implementation."""

    class Star(MemoryStore):
        def __init__(self, context):
            super().__init__()
            self.logger = logging.getLogger("test.sage_bridge")

    def event_message_type(kind, **kwargs):
        return lambda handler: handler

    modules = {
        "astrbot": {},
        "astrbot.api": {"AstrBotConfig": dict},
        "astrbot.api.event": {
            "AstrMessageEvent": Event,
            "filter": SimpleNamespace(
                EventMessageType=SimpleNamespace(ALL="all"),
                event_message_type=event_message_type,
            ),
        },
        "astrbot.api.message_components": {
            "Plain": Plain,
            "Image": Image,
            "At": At,
            "Reply": Reply,
        },
        "astrbot.api.star": {"Context": object, "Star": Star},
    }
    for name, attributes in modules.items():
        module = ModuleType(name)
        module.__dict__.update(attributes)
        monkeypatch.setitem(sys.modules, name, module)
    name = "integrations.astrbot_plugin_sage.main"
    monkeypatch.delitem(sys.modules, name, raising=False)
    module = importlib.import_module(name)
    yield module.SagePlugin
    sys.modules.pop(name, None)


@pytest.fixture
async def plugin(plugin_class, monkeypatch):
    monkeypatch.setenv("SAGE_TEAM_A_KEY", "sage_a2a.team-a.secret")
    plugin = plugin_class(None, config().model_dump())
    await plugin.http.aclose()
    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        message = body["params"]["message"]
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {"task": task(message["contextId"])},
            },
        )

    plugin.http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    plugin.bridge.client.http = plugin.http
    yield plugin, requests
    await plugin.terminate()
    assert plugin.http.is_closed


async def test_plugin_takes_ownership_of_bound_messages_and_returns_text(plugin):
    instance, requests = plugin
    event = Event()
    await instance.on_message(event)
    assert event.stopped and not event.llm
    assert event.sent == ["hello"]
    assert requests[0]["params"]["message"]["parts"] == [{"text": "hi"}]


@pytest.mark.parametrize(
    "event, stopped, denied",
    [
        (Event(platform="other-bot"), False, False),
        (Event(private=False), True, False),
        (Event(sender="mallory"), True, True),
        (Event(sender="bot-1"), True, False),
    ],
)
async def test_ignored_or_unauthorized_messages_never_reach_sage(
    plugin, event, stopped, denied
):
    instance, requests = plugin
    await instance.on_message(event)
    assert not requests
    assert event.stopped is stopped
    assert bool(event.sent) is denied


async def test_group_mentions_and_images_preserve_content_without_forwarding_local_paths(
    plugin, tmp_path
):
    instance, requests = plugin
    path = tmp_path / "sample.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\nexample")
    event = Event(
        private=False,
        wake=True,
        components=[At("bot-1"), Plain("describe"), Image(str(path))],
    )
    await instance.on_message(event)
    parts = requests[0]["params"]["message"]["parts"]
    assert parts[0] == {"text": "describe"}
    assert parts[1]["mediaType"] == "image/png"
    assert parts[1]["url"].startswith("data:image/png;base64,")
    assert str(path) not in json.dumps(requests)


@pytest.mark.parametrize(
    "components",
    [
        [Plain("summarize"), object()],
        [Plain("x" * 20_001)],
    ],
)
async def test_unsupported_or_oversized_input_is_rejected_as_a_whole(
    plugin, components
):
    instance, requests = plugin
    event = Event(components=components)
    await instance.on_message(event)
    assert not requests
    assert len(event.sent) == 1


async def test_help_and_status_do_not_create_an_agent_run(plugin):
    instance, requests = plugin
    for command in ("/sage", "/sage status", "/sage new", "/sage approve"):
        event = Event(private=False, text=command)
        await instance.on_message(event)
        assert event.stopped and event.sent
    assert not requests

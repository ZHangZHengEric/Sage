"""Exercise the standalone bridge against the real Sage A2A router and runtime."""

from __future__ import annotations

import asyncio
import base64
import json

import httpx
import pytest

from integrations.astrbot_plugin_sage.bridge import SageBridge
from integrations.astrbot_plugin_sage.client import SageClient
from integrations.astrbot_plugin_sage.client import BridgeError
from tests.app.v2.server.conftest import register_and_login
from tests.app.v2.server.test_a2a_card import make_a2a_client, mint_key, rpc
from tests.integrations.test_astrbot_bridge import MemoryStore, config, source


def test_two_tenant_bridge_round_trip_with_images_reset_and_redelivery(
    tmp_path, monkeypatch
):
    with make_a2a_client(tmp_path, steps=8) as server:
        _, first_key = mint_key(server, register_and_login(server, "tenant-a"))
        _, second_key = mint_key(server, register_and_login(server, "tenant-b"))
        monkeypatch.setenv("SAGE_TEAM_A_KEY", first_key)
        monkeypatch.setenv("SAGE_TEAM_B_KEY", second_key)
        settings = config(
            wait_seconds=5,
            poll_interval_seconds=0.01,
            bindings=[
                {
                    "platform_id": "lark-team-a",
                    "api_key_env": "SAGE_TEAM_A_KEY",
                    "allowed_sender_ids": ["alice"],
                },
                {
                    "platform_id": "lark-team-b",
                    "api_key_env": "SAGE_TEAM_B_KEY",
                    "allowed_sender_ids": ["alice"],
                },
            ],
        )
        store = MemoryStore()

        def transport(request):
            response = server.post(
                request.url.path, content=request.content, headers=dict(request.headers)
            )
            return httpx.Response(response.status_code, content=response.content)

        async def run():
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(transport)
            ) as http:
                bridge = SageBridge(settings, SageClient(http, settings), store)
                image = base64.b64encode(b"\x89PNG\r\n\x1a\nexample").decode()
                parts = [
                    {"text": "describe"},
                    {"url": f"data:image/png;base64,{image}", "mediaType": "image/png"},
                ]
                assert (await bridge.handle(source(), parts)).text == "hello"
                # Duplicate platform delivery reuses the original task.
                assert (await bridge.handle(source(), parts)).text == "hello"
                await bridge.handle(
                    source(message_id="message-2"), [{"text": "follow-up"}]
                )
                await bridge.handle(source(), parts)
                other = source(
                    platform_id="lark-team-b", origin="lark-team-b:GroupMessage:group-1"
                )
                assert (
                    await bridge.handle(other, [{"text": "other tenant"}])
                ).text == "hello"
                await bridge.handle(source(message_id="new-1"), command="new")
                # A late redelivery still belongs to the original context.
                await bridge.handle(source(), parts)
                assert (
                    await bridge.handle(
                        source(message_id="message-3"), [{"text": "new topic"}]
                    )
                ).text == "hello"

        asyncio.run(run())
        tasks_a = rpc(server, first_key, "ListTasks", {})["result"]["tasks"]
        tasks_b = rpc(server, second_key, "ListTasks", {})["result"]["tasks"]
        assert len(tasks_a) == 3
        assert len(tasks_b) == 1
        assert len({task["contextId"] for task in tasks_a}) == 2
        assert not (
            {task["contextId"] for task in tasks_a}
            & {task["contextId"] for task in tasks_b}
        )
        denied = rpc(server, second_key, "GetTask", {"id": tasks_a[0]["id"]})
        assert "error" in denied and "result" not in denied
        # KV storage contains no API key; only a credential fingerprint scopes it.
        assert first_key not in json.dumps(store.values)
        assert second_key not in json.dumps(store.values)


def test_sage_rejects_read_only_key_before_admitting_a_task(tmp_path, monkeypatch):
    with make_a2a_client(tmp_path) as server:
        _, key = mint_key(server, register_and_login(server), scopes=["a2a:read"])
        monkeypatch.setenv("SAGE_TEAM_A_KEY", key)

        def transport(request):
            response = server.post(
                request.url.path, content=request.content, headers=dict(request.headers)
            )
            return httpx.Response(response.status_code, content=response.content)

        async def run():
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(transport)
            ) as http:
                bridge = SageBridge(config(), SageClient(http, config()), MemoryStore())
                with pytest.raises(BridgeError) as raised:
                    await bridge.handle(source(), [{"text": "cannot invoke"}])
                assert raised.value.code == "http_403"
                assert (
                    "新"
                    in (
                        await bridge.handle(source(message_id="new-1"), command="new")
                    ).text
                )

        asyncio.run(run())
        assert not rpc(server, key, "ListTasks", {})["result"].get("tasks")

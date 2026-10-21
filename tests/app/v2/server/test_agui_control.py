"""Browser Run cancellation uses the existing runtime and preserves Session history."""

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from anyio.from_thread import BlockingPortal

import asyncio
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from app.v2.server.main import create_app
from tests.app.v2.server.conftest import make_test_service, register_and_login
from tests.app.v2.server.test_agui_resume import _ask, _asking_service
from tests.app.v2.server.test_a2a_resume import _step
from sagents.v2.testing.plugins import ScriptedModelProvider


class GatedModel:
    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.requests = []
        self.scripted = ScriptedModelProvider((
            _step(1, "先检查目录", "list_dir", {}),
            _step(2, "已按补充要求完成"),
        ))

    async def capabilities(self, binding):
        return await self.scripted.capabilities(binding)

    async def stream(self, request):
        self.requests.append(request)
        if len(self.requests) == 1:
            self.started.set()
            await self.release.wait()
        async for event in self.scripted.stream(request):
            yield event


def test_browser_steering_is_delivered_once_at_the_next_model_step(tmp_path):
    model = GatedModel()
    host = make_test_service(tmp_path, model_provider=model)
    with TestClient(create_app(service=host)) as client, ThreadPoolExecutor() as pool:
        token = register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        agent = client.get("/api/agents", headers=headers).json()["data"][0]
        client.put(f"/api/agents/{agent['id']}", json={"name": agent["name"], "tools": ["list_dir"]}, headers=headers)
        running = pool.submit(client.post, "/api/agent", headers=headers, json={
            "threadId": "live", "runId": "live-run",
            "messages": [{"id": "initial", "role": "user", "content": "开始检查"}],
        })
        cast('BlockingPortal', client.portal).call(model.started.wait)
        body = {"runId": "live-run", "messageId": "m" * 128, "text": "补充要求：使用中文"}
        try:
            accepted = client.post("/api/threads/live/steer", headers=headers, json=body)
            assert accepted.status_code == 200, accepted.text
            assert accepted.json()["data"]["state"] == "pending"
            repeated = client.post("/api/threads/live/steer", headers=headers, json=body)
            assert repeated.json()["data"] == accepted.json()["data"]
            changed = client.post("/api/threads/live/steer", headers=headers, json={**body, "text": "different"})
            assert changed.status_code == 409, changed.text
            assert client.post("/api/threads/live/steer", headers=headers, json={**body, "runId": "other"}).status_code == 404
            assert client.post("/api/threads/live/steer", headers=headers, json={**body, "text": "  "}).status_code == 422
        finally:
            cast('BlockingPortal', client.portal).call(model.release.set)
        response = running.result(timeout=15)
        assert 'sage.steer.applied' in response.text
        assert response.text.count('"delta":"补充要求：使用中文"') == 1
        received = [block.text for message in model.requests[1].messages
                    if message.role == "user" for block in message.content if hasattr(block, "text")]
        assert any(body["text"] in text for text in received), received
        replay = client.post("/api/threads/live/steer", headers=headers, json=body)
        assert replay.json()["data"]["state"] == "applied"
        assert client.post("/api/threads/live/steer", headers=headers, json={**body, "messageId": "too-late"}).status_code == 409
        history = client.get("/api/threads/live/events?offset=0", headers=headers).json()["data"]["events"]
        assert sum(event.get("delta") == body["text"] for event in history) == 1


def test_browser_cancel_ends_a_live_stream_without_waiting_for_the_model(tmp_path):
    model = GatedModel()
    host = make_test_service(tmp_path, model_provider=model)
    with TestClient(create_app(service=host)) as client, ThreadPoolExecutor() as pool:
        token = register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        running = pool.submit(client.post, "/api/agent", headers=headers, json={
            "threadId": "live", "runId": "live-run",
            "messages": [{"id": "initial", "role": "user", "content": "开始检查"}],
        })
        cast('BlockingPortal', client.portal).call(model.started.wait)
        try:
            cancelled = client.post("/api/threads/live/cancel", headers=headers, json={"runId": "live-run"})
            assert cancelled.status_code == 200, cancelled.text
            response = running.result(timeout=5)
            assert 'sage.run.cancelled' in response.text
            assert 'RUN_FINISHED' not in response.text
        finally:
            cast('BlockingPortal', client.portal).call(model.release.set)


def test_browser_cancel_is_exact_owned_idempotent_and_allows_the_next_run(tmp_path):
    with TestClient(create_app(service=_asking_service(tmp_path))) as client:
        alice = register_and_login(client)
        headers = {"Authorization": f"Bearer {alice}"}
        _ask(client, alice)
        bob = register_and_login(client, "bob")
        denied = client.post("/api/threads/thread-1/cancel", json={"runId": "run-1"},
                             headers={"Authorization": f"Bearer {bob}"})
        assert denied.status_code == 404, denied.text
        missing = client.post("/api/threads/thread-1/cancel", json={"runId": "wrong"}, headers=headers)
        assert missing.status_code == 404, missing.text
        response = client.post("/api/threads/thread-1/cancel", json={"runId": "run-1"}, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["data"]["cancelled"] is True
        result = client.get("/api/threads/thread-1/result?runId=run-1", headers=headers)
        assert result.json()["data"]["state"] == "cancelled"
        history = client.get("/api/threads/thread-1/events?offset=0", headers=headers).json()["data"]["events"]
        assert any(event.get("name") == "sage.run.cancelled" for event in history)
        native_id = next(event["runId"] for event in history if event["type"] == "RUN_STARTED")
        again = client.post("/api/threads/thread-1/cancel", json={"runId": native_id}, headers=headers)
        assert again.status_code == 200, again.text
        assert again.json()["data"]["cancelled"] is False
        next_run = client.post("/api/agent", headers=headers, json={
            "threadId": "thread-1", "runId": "next-run",
            "messages": [{"id": "next-message", "role": "user", "content": "继续整理"}],
        })
        assert next_run.status_code == 200, next_run.text
        assert 'RUN_FINISHED' in next_run.text


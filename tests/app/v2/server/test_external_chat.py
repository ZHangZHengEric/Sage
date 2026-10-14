from fastapi.testclient import TestClient

from app.v2.server.bootstrap import ServerHost
from app.v2.server.database import Database, DatabaseSettings
from app.v2.server.main import create_app
from tests.app.v2.server.conftest import (
    CompletingJudgeModel,
    make_settings,
    register_and_login,
    scripted_hello,
)
from tests.app.v2.server.test_agui_chat import _parse_sse


def make_host(path, steps=4):
    return ServerHost(
        make_settings(path),
        model_provider=CompletingJudgeModel(scripted_hello(steps)),
        database=Database(DatabaseSettings(url=f"sqlite+aiosqlite:///{path}/host.db")),
    )


def setup_agent(client):
    token = register_and_login(client)
    response = client.post(
        "/api/agents",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Palune", "instructions": "Say hello"},
    )
    assert response.status_code == 200, response.text
    client.cookies.clear()
    client.headers["SAGE-AGENT-ID"] = response.json()["data"]["id"]


def headers(user="business-user-123"):
    return {"SAGE-TENANT-ID": user}


def send(client, session="work-1", request="create-1", user="business-user-123"):
    return client.post(
        "/api/agent",
        headers=headers(user),
        json={
            "threadId": session,
            "runId": request,
            "messages": [{"id": request, "role": "user", "content": "hello"}],
        },
    )


def result(client, session="work-1", request=None, user="business-user-123"):
    return client.get(
        f"/api/threads/{session}/result",
        headers=headers(user),
        params={"request_id": request} if request else {},
    )


def test_external_chat_unregistered_user_edits_and_restart(tmp_path):
    with TestClient(create_app(make_host(tmp_path))) as client:
        setup_agent(client)
        agent_id = client.headers["SAGE-AGENT-ID"]
        first = send(client)
        assert first.status_code == 200, first.text
        events = _parse_sse(first.text)
        assert events[0]["threadId"] == "work-1"
        assert events[-1]["type"] == "RUN_FINISHED"
        assert events[-1]["runId"] == "create-1"
        workspace = tmp_path / "tenants" / "business-user-123" / agent_id / "workspace"
        assert workspace.is_dir()
        (workspace / "shared.txt").write_text("shared across this user's sessions")
        original = result(client, request="create-1")
        assert original.status_code == 200, original.text
        data = original.json()["data"]
        assert data["state"] == "completed" and data["text"] == "hello"
        assert send(client, request="edit-2").status_code == 200
        latest = result(client).json()["data"]
        assert latest["request_id"] == "edit-2" and latest["run_id"] != data["run_id"]
        assert (
            result(client, request="create-1").json()["data"]["run_id"]
            == data["run_id"]
        )
        replay = send(client, request="edit-2")
        assert (
            replay.status_code == 200
            and _parse_sse(replay.text)[-1]["type"] == "RUN_FINISHED"
        )
        assert result(client).json()["data"]["run_id"] == latest["run_id"]
        assert result(client, user="other-business-user").status_code == 404
        assert result(client, request="missing").status_code == 404
        assert send(client, session="work-2").status_code == 200
        assert (workspace / "shared.txt").read_text() == "shared across this user's sessions"
        # Identical external session IDs owned by different business users stay separate.
        assert send(client, user="other-business-user").status_code == 200
        other_workspace = tmp_path / "tenants" / "other-business-user" / agent_id / "workspace"
        assert other_workspace.is_dir()
        assert not (other_workspace / "shared.txt").exists()
        assert (
            result(client, user="other-business-user").json()["data"]["run_id"]
            != data["run_id"]
        )
    # Reopen both runtime and SQL repositories; no Python objects carry the results.
    with TestClient(create_app(make_host(tmp_path))) as restarted:
        restarted.headers["SAGE-AGENT-ID"] = agent_id
        restored = result(restarted, request="edit-2")
        assert restored.status_code == 200, restored.text
        assert restored.json()["data"] == latest
        assert result(restarted, request="create-1").json()["data"] == data


def test_external_headers_required_and_existing_chat_still_authenticated(tmp_path):
    with TestClient(create_app(make_host(tmp_path))) as client:
        setup_agent(client)
        del client.headers["SAGE-AGENT-ID"]
        body = {
            "threadId": "work-1",
            "runId": "create-1",
            "messages": [{"id": "m", "role": "user", "content": "hello"}],
        }
        assert client.post("/api/agent", json=body).status_code == 401
        assert (
            client.post(
                "/api/agent",
                json=body,
                headers={"SAGE-AGENT-ID": "unknown", "SAGE-TENANT-ID": "business-user"},
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/api/agent", json={"threadId": "t", "runId": "r", "messages": []}
            ).status_code
            == 401
        )


async def test_disconnect_only_detaches_reader(tmp_path):
    import asyncio
    from ag_ui.core import RunAgentInput

    gate = asyncio.Event()
    scripted = scripted_hello()

    class GatedModel:
        async def capabilities(self, binding):
            return await scripted.capabilities(binding)

        async def stream(self, request):
            await gate.wait()
            async for event in scripted.stream(request):
                yield event

    host = make_host(tmp_path)
    host.execution.fallback_model = CompletingJudgeModel(GatedModel())
    await host.database.start()
    await host.start()
    try:
        owner = await host.identity.register("owner", "secret1")
        agent = await host.catalog.create_agent(
            owner.user_id, {"id": "palune-agent", "name": "Palune"}
        )
        service = host.conversations
        request = RunAgentInput(
            thread_id="session",
            run_id="request",
            state={},
            tools=[],
            context=[],
            messages=[{"id": "message", "role": "user", "content": "hello"}],
            forwarded_props={},
        )
        stream = await service.start(
            request, user_id="not-a-sage-user", agent_id=agent.id
        )
        first = await anext(stream)
        assert "RUN_STARTED" in first
        await stream.aclose()
        running = await service.result(
            user_id="not-a-sage-user", agent_id=agent.id, session_id="session"
        )
        assert running["state"] in {"queued", "running"}
        assert running["text"] == ""
        gate.set()
        async with asyncio.timeout(5):
            while True:
                result = await service.result(
                    user_id="not-a-sage-user",
                    agent_id=agent.id,
                    session_id="session",
                )
                if result["state"] == "completed":
                    break
                await asyncio.sleep(0.01)
        assert result["text"] == "hello"
    finally:
        gate.set()
        await host.close()
        await host.database.stop()


def test_original_chat_result_and_header_contract(tmp_path):
    with TestClient(create_app(make_host(tmp_path))) as client:
        token = register_and_login(client)
        body = {
            "threadId": "native-thread",
            "runId": "native-run",
            "messages": [{"id": "m", "role": "user", "content": "hello"}],
        }
        response = client.post(
            "/api/agent", headers={"Authorization": f"Bearer {token}"}, json=body
        )
        assert response.status_code == 200
        result = client.get(
            "/api/threads/native-thread/result",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert result.status_code == 200 and result.json()["data"]["text"] == "hello"
        client.cookies.clear()
        assert client.get("/api/threads/native-thread/result").status_code == 401
        partial = client.post("/api/agent", headers={"SAGE-TENANT-ID": "business"}, json=body)
        assert partial.status_code == 422
        parameters = client.get("/openapi.json").json()["paths"]["/api/agent"]["post"][
            "parameters"
        ]
        assert {p["name"] for p in parameters if p["in"] == "header"} >= {
            "SAGE-AGENT-ID",
            "SAGE-TENANT-ID",
        }

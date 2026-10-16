"""Session identity survives transport, storage, tools and legacy lookup."""
import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from app.v2.server.main import create_app
from app.v2.server.conversations.bindings import SessionBinding
from sagents.v2.testing.plugins import ScriptedModelProvider
from tests.app.v2.server.conftest import CompletingJudgeModel
from tests.app.v2.server.test_a2a_resume import _step
from tests.app.v2.server.test_agui_chat import _parse_sse
from tests.app.v2.server.test_external_chat import make_host, setup_agent, headers, result, send


def body(**ids):
    return {"runId": "request-1", "messages": [{"id": "m", "role": "user", "content": "hello"}], **ids}


@pytest.mark.parametrize("route", ["chat", "agent", "native"])
def test_session_id_alias_generation_and_reuse(tmp_path, route):
    host = make_host(tmp_path, steps=8)
    with TestClient(create_app(host)) as client:
        token = setup_agent(client)
        request_headers = headers()
        if route == "native":
            del client.headers["SAGE-AGENT-ID"]
            client.headers["Authorization"] = f"Bearer {token}"
            request_headers = {}
        url = "/api/agent" if route in {"chat", "native"} else f"/api/agents/{client.headers['SAGE-AGENT-ID']}/runs"
        for index, ids in enumerate(({"session_id": "kept-ID"}, {"threadId": "compatible-ID"}, {})):
            response = client.post(url, headers=request_headers, json={**body(**ids), "runId": f"start-{index}"})
            assert response.status_code == 200, response.text
            frame = _parse_sse(response.text)[0]
            session_id = frame["session_id"]
            assert session_id == frame["threadId"]
            assert session_id == (ids.get("session_id") or ids.get("threadId") or session_id)
            assert not session_id.startswith("external_")
            again = client.post(url, headers=request_headers, json={**body(session_id=session_id), "runId": f"edit-{index}"})
            assert again.status_code == 200, again.text
            assert _parse_sse(again.text)[0]["session_id"] == session_id
            selected = (client.get(f"/api/threads/{session_id}/result") if route == "native"
                        else result(client, session=session_id))
            assert selected.json()["data"]["session_id"] == session_id
        conflict = client.post(url, headers=request_headers, json=body(session_id="left", threadId="right"))
        assert conflict.status_code == 422
        assert "must match" in conflict.text
        for invalid in ("", "  spaced  ", "../escape"):
            assert client.post(url, headers=request_headers, json=body(session_id=invalid)).status_code == 422


def test_todo_write_uses_durable_id_instead_of_model_argument(tmp_path):
    host = make_host(tmp_path)
    model = ScriptedModelProvider((_step(1, "", "todo_write", {
        "session_id": "wrong-model-session", "tasks": [{"id": "1", "content": "keep identity", "status": "completed"}],
    }), *(_step(i, "done") for i in range(2, 6))))
    host.execution.fallback_model = CompletingJudgeModel(model)
    with TestClient(create_app(host)) as client:
        token = setup_agent(client)
        agent = client.headers["SAGE-AGENT-ID"]
        policy = client.put("/api/auth/execution-policy", headers={"Authorization": f"Bearer {token}"},
                            json={"shell": "sandboxed"})
        assert policy.status_code == 200, policy.text
        response = client.post(f"/api/agents/{agent}/runs", headers=headers(),
                               json={**body(session_id="Todo-ID"), "runtimeContext": {"session_id": "Todo-ID"}})
        assert response.status_code == 200, response.text
        base = f"/api/agents/{agent}/runs/Todo-ID/request-1"
        detail = client.get(base, headers=headers()).json()["data"]
        assert detail["state"] == "suspended", response.text
        pending = detail["interaction"]
        assert pending["request"]["payload"]["arguments"]["session_id"] == "Todo-ID"
        reply = client.post(base + "/reply", headers=headers(), json={
            "interaction_id": pending["request"]["interaction_id"],
            "decision": "approve_once", "expected": pending["expected"],
        })
        assert reply.status_code == 200, reply.text

        async def completed_result():
            import asyncio
            async with asyncio.timeout(5):
                while True:
                    current = await host.conversations.result(
                        user_id="business-user-123", agent_id=agent, session_id="Todo-ID")
                    if current["state"] == "completed":
                        return current
                    await asyncio.sleep(0.01)
        assert client.portal.call(completed_result)["session_id"] == "Todo-ID"
        path = tmp_path / "tenants" / "business-user-123" / agent / "workspace" / ".sage" / "todos"
        assert json.loads((path / "Todo-ID.json").read_text())[0]["content"] == "keep identity"
        assert not (path / "wrong-model-session.json").exists()
        store = host.application.entrypoint().runtime.session_store
        runs = client.portal.call(store.list_session_runs, "Todo-ID")
        assert runs and all(run.session_id == "Todo-ID" for run in runs)
        command = client.portal.call(store.get_start_command, runs[0].run_id)
        assert command.config.metadata["system_context"]["session_id"] == "Todo-ID"
        events = client.portal.call(store.read_events, runs[0].run_id)
        assert all(event.session_id == "Todo-ID" for event in events)
        assert not any(event.type == "tool.call.unknown" for event in events)
        # The Web diagnostic bundle includes the dispatched override and result
        # after suspension/resume, while the model request keeps its original proposal.
        from io import BytesIO
        from zipfile import ZipFile
        from tests.app.v2.server.test_session_diagnostics import admin_headers

        download = client.get("/api/threads/Todo-ID/download", headers=admin_headers(client))
        assert download.status_code == 200, download.text
        with ZipFile(BytesIO(download.content)) as archive:
            tools = json.loads(archive.read("Todo-ID/tools.json"))
            proposals = [row["event"]["data"] for row in tools
                         if row["event"]["type"] == "tool.call.proposed"]
            assert proposals[0]["arguments"]["session_id"] == "Todo-ID"
            assert any(row["event"]["type"] == "tool.call.succeeded" for row in tools)
            assert any(row["event"]["type"] == "item.completed" for row in tools)
            assert json.loads(archive.read("Todo-ID/models.json"))
            assert json.loads(archive.read("Todo-ID/logs.json"))



def test_runtime_context_mismatch_has_no_run_or_workspace_side_effect(tmp_path):
    host = make_host(tmp_path)
    with TestClient(create_app(host)) as client:
        setup_agent(client)
        agent = client.headers["SAGE-AGENT-ID"]
        response = client.post(f"/api/agents/{agent}/runs?workspace_path=projects/new", headers=headers(),
                               json={**body(session_id="rejected"), "runtimeContext": {"session_id": "wrong"}})
        assert response.status_code == 422
        assert not (tmp_path / "tenants" / "business-user-123" / agent / "workspace" / "projects" / "new").exists()
        assert client.portal.call(host.threads.find, "rejected") is None


def test_legacy_hash_lookup_reuses_history_workspace_and_todo(tmp_path, monkeypatch):
    host = make_host(tmp_path, steps=8)
    with TestClient(create_app(host)) as client:
        setup_agent(client)
        agent = client.headers["SAGE-AGENT-ID"]
        identity = json.dumps(["business-user-123", agent, "old-id"], separators=(",", ":"))
        legacy = "external_" + hashlib.sha256(identity.encode()).hexdigest()
        # Seed the old physical identity and pre-upgrade command metadata.
        import app.v2.server.conversations.agui.service as agui_service
        original_mapping = agui_service.to_start_run
        def old_mapping(request, **kwargs):
            metadata = dict(kwargs["metadata"])
            metadata.pop("system_context", None)
            return original_mapping(request, **{**kwargs, "metadata": metadata})
        with monkeypatch.context() as patch:
            patch.setattr(agui_service, "to_start_run", old_mapping)
            assert send(client, session=legacy).status_code == 200
        async def remove_new_binding():
            from app.v2.server.conversations.orm import SessionBindingRow
            async with host.database.transaction() as session:
                await session.delete(await session.get(SessionBindingRow, legacy))
        client.portal.call(remove_new_binding)
        workspace = tmp_path / "tenants" / "business-user-123" / agent / "workspace"
        todos = workspace / ".sage" / "todos"
        todos.mkdir(parents=True, exist_ok=True)
        (todos / f"{legacy}.json").write_text('[{"id":"1","content":"history"}]')
        old = result(client, session="old-id", request="create-1")
        assert old.status_code == 200, old.text
        assert old.json()["data"]["session_id"] == legacy
        assert send(client, session="old-id").status_code == 200
        store = host.application.entrypoint().runtime.session_store
        assert len(client.portal.call(store.list_session_runs, legacy)) == 1
        assert send(client, session="old-id", request="edit-2").status_code == 200
        assert result(client, session="old-id").json()["data"]["session_id"] == legacy
        assert (todos / f"{legacy}.json").is_file()
        assert client.portal.call(host.threads.find, "old-id") is None
        assert result(client, session=legacy, user="other-tenant").status_code == 404


async def test_concurrent_database_claims_cannot_overwrite_tenant(tmp_path):
    import asyncio
    from app.v2.server.database.schema import create_host_schema
    from app.v2.server.conversations.repository import DatabaseThreadIndex
    from sagents.v2.contracts.errors import SageV2Error

    host = make_host(tmp_path)
    await host.database.start()
    try:
        await create_host_schema(host.database)
        index = DatabaseThreadIndex(host.database)
        claims = [SessionBinding("same-ID", "owner", tenant, "agent") for tenant in ("a", "b")]
        results = await asyncio.gather(*(index.bind(claim) for claim in claims), return_exceptions=True)
        assert sum(value is None for value in results) == 1
        assert sum(isinstance(value, SageV2Error) for value in results) == 1
        assert await index.binding("same-ID") in claims
    finally:
        await host.database.stop()


def test_legacy_suspended_todo_restores_after_restart(tmp_path):
    """Keep physical IDs and pending operations while accepting the old alias."""
    host = make_host(tmp_path)
    host.execution.fallback_model = CompletingJudgeModel(ScriptedModelProvider((
        _step(1, "", "todo_write", {"session_id": "old-id", "tasks": [
            {"id": "new", "content": "resumed", "status": "completed"},
        ]}),
    )))
    with TestClient(create_app(host)) as client:
        setup_agent(client)
        agent = client.headers["SAGE-AGENT-ID"]
        authorization = client.headers["Authorization"]
        identity = json.dumps(["business-user-123", agent, "old-id"], separators=(",", ":"))
        legacy = "external_" + hashlib.sha256(identity.encode()).hexdigest()
        first = client.post("/api/agent", headers=headers(), json=body(session_id=legacy))
        assert first.status_code == 200
        assert result(client, session=legacy).json()["data"]["state"] == "suspended"
        todos = tmp_path / "tenants" / "business-user-123" / agent / "workspace" / ".sage" / "todos"
        todos.mkdir(parents=True, exist_ok=True)
        (todos / f"{legacy}.json").write_text('[{"id":"old","content":"kept","status":"completed"}]')
        async def remove_claim():
            from app.v2.server.conversations.orm import SessionBindingRow
            async with host.database.transaction() as session:
                await session.delete(await session.get(SessionBindingRow, legacy))
        client.portal.call(remove_claim)
    restarted = make_host(tmp_path, steps=8)
    with TestClient(create_app(restarted)) as client:
        client.headers["SAGE-AGENT-ID"] = agent
        client.headers["Authorization"] = authorization
        base = f"/api/agents/{agent}/runs/old-id/request-1"
        detail = client.get(base, headers=headers())
        assert detail.status_code == 200, detail.text
        data = detail.json()["data"]
        assert data["session_id"] == legacy and data["state"] == "suspended"
        pending = data["interaction"]
        assert client.post(base + "/reply", headers=headers(), json={
            "interaction_id": pending["request"]["interaction_id"], "decision": "approve_once",
            "expected": pending["expected"],
        }).status_code == 200
        async def wait_finished():
            import asyncio
            async with asyncio.timeout(5):
                while True:
                    current = await restarted.conversations.result(
                        user_id="business-user-123", agent_id=agent, session_id="old-id")
                    if current["state"] == "completed":
                        return current
                    assert current["state"] not in {"failed", "cancelled"}
                    await asyncio.sleep(0.01)
        assert client.portal.call(wait_finished)["session_id"] == legacy
        tasks = json.loads((todos / f"{legacy}.json").read_text())
        assert {task["id"] for task in tasks} == {"old", "new"}
        assert client.portal.call(restarted.threads.find, "old-id") is None


def test_questionnaire_and_followup_keep_session_identity(tmp_path):
    host = make_host(tmp_path)
    host.execution.fallback_model = CompletingJudgeModel(ScriptedModelProvider((
        _step(1, "", "questionnaire_async", {
            "session_id": "model-value", "questions": [{"id": "q1", "type": "text", "title": "Name?"}],
        }), *(_step(i, "done") for i in range(2, 6)),
    )))
    with TestClient(create_app(host)) as client:
        token = setup_agent(client)
        configured = client.put(f"/api/agents/{client.headers['SAGE-AGENT-ID']}",
                                headers={"Authorization": f"Bearer {token}"},
                                json={"name": "Palune", "tools": ["questionnaire_async"]})
        assert configured.status_code == 200, configured.text
        first = client.post("/api/agent", headers=headers(), json=body(session_id="Question-ID"))
        assert first.status_code == 200, first.text
        frames = _parse_sse(first.text)
        proposal = next(frame["value"] for frame in frames
                        if frame.get("name") == "tool.call.proposed")
        assert proposal["arguments"]["session_id"] == "Question-ID"
        assert result(client, session="Question-ID").json()["data"]["state"] == "completed"
        assert any('"question_count":1' in frame.get("content", "").replace(" ", "")
                   for frame in frames if frame["type"] == "TOOL_CALL_RESULT")
        followup = client.post("/api/agent", headers=headers(), json={**body(session_id="Question-ID"),
                               "runId": "answer-2", "messages": [{"id": "answer", "role": "user", "content": "Alice"}]})
        assert followup.status_code == 200, followup.text
        assert _parse_sse(followup.text)[0]["session_id"] == "Question-ID"

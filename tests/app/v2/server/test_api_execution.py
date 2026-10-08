"""API authorization, durable approval, and per-drive resource cleanup."""

from datetime import timedelta

from fastapi.testclient import TestClient
import pytest

from app.v2.server.main import create_app
from app.v2.server.database import Database, DatabaseSettings
from app.v2.server.database.schema import create_host_schema
from app.v2.server.identity.repository import DatabaseUserStore
from app.v2.server.identity.users import UserRecord
from app.v2.server.runtime.policy import ExecutionPolicy
from tests.app.v2.server.conftest import make_test_service, register_and_login
from tests.app.v2.server.test_a2a_resume import _step, asking_client, ask, reply
from tests.app.v2.server.test_a2a_send import send
from sagents.v2.testing.plugins import ScriptedModelProvider
from sagents.v2.contracts.common import utc_now


def issue(client, token, *, policy=None, scopes=None, agent_id=None):
    headers = {"Authorization": f"Bearer {token}"}
    if agent_id is None:
        agent_id = client.post("/api/agents", headers=headers,
            json={"name": "Worker", "tools": ["file_write", "execute_shell_command"]}).json()["data"]["id"]
    if policy is not None:
        response = client.put("/api/auth/execution-policy", headers=headers, json=policy)
        assert response.status_code == 200, response.text
    body = {"agent_id": agent_id, "name": "worker"}
    if scopes is not None:
        body["scopes"] = scopes
    response = client.post("/api/keys", headers=headers, json=body)
    assert response.status_code == 200, response.text
    return response.json()["data"]


@pytest.mark.parametrize("policy,waiting,written", [
    ({}, True, False),
    ({"shell": "sandboxed"}, False, True),
    ({"shell": "sandboxed", "on_approval_required": "deny"}, False, True),
    ({"on_approval_required": "deny"}, False, False),
])
def test_api_workspace_authorization_and_drive_cleanup(tmp_path, policy, waiting, written):
    provider = ScriptedModelProvider((_step(1, "write", "file_write",
        {"file_path": "result.txt", "content": "blue"}), _step(2, "done")))
    host = make_test_service(tmp_path, model_provider=provider)
    with TestClient(create_app(service=host)) as client:
        token = register_and_login(client)
        record = issue(client, token, policy=policy)
        task = send(client, record["api_key"], "write")["result"]["task"]
        assert task["status"]["state"] == ("TASK_STATE_INPUT_REQUIRED" if waiting else "TASK_STATE_COMPLETED")
        # The stream settles only after resource shutdown; inspect in its own loop.
        async def settled():
            for _ in range(100):
                if not host.execution.driving(task["id"]):
                    break
                import asyncio
                await asyncio.sleep(0.01)
            return host.execution.driving(task["id"]), len(host.execution.sandbox_provider._rows)
        driving, sandboxes = client.portal.call(settled)
        assert not driving
        assert sandboxes == 0
        files = list(tmp_path.rglob("result.txt"))
        assert bool(files) == written
        if written:
            assert files[0].read_text() == "blue"


def test_request_cannot_expand_user_authorization(tmp_path):
    with asking_client(tmp_path) as client:
        token = register_and_login(client)
        record = issue(client, token)
        task = send(client, record["api_key"], "write",
                    metadata={"sage.executionPolicy": {"shell": "sandboxed"}})["result"]["task"]
        assert task["status"]["state"] == "TASK_STATE_INPUT_REQUIRED"


def test_machine_approval_requires_its_own_scope(tmp_path):
    with asking_client(tmp_path) as client:
        token = register_and_login(client)
        key, task = ask(client, token, scopes=["a2a:invoke", "a2a:read"])
        assert "error" in reply(client, key, task, "approve", **{"sage.decision": "approve_once"})
        assert not list(tmp_path.rglob("note.txt"))


def test_owner_approval_is_revision_bound_and_tenant_isolated(tmp_path):
    with asking_client(tmp_path) as client:
        token = register_and_login(client)
        _, task = ask(client, token)
        headers = {"Authorization": f"Bearer {token}"}
        item = client.get("/api/approvals", headers=headers).json()["data"]["items"][0]
        other = register_and_login(client, "other")
        assert client.get("/api/approvals", headers={"Authorization": f"Bearer {other}"}).json()["data"]["items"] == []
        body = {"decision": "approve_once", "expected": item["expected"]}
        stale = {**body, "expected": {**item["expected"], "revision": 0}}
        assert client.post(f"/api/approvals/{task['id']}/decisions", headers=headers, json=stale).status_code == 409
        assert not list(tmp_path.rglob("note.txt"))
        response = client.post(f"/api/approvals/{task['id']}/decisions", headers=headers, json=body)
        assert response.status_code == 200, response.text
        async def wait_for_completion():
            import asyncio
            for _ in range(200):
                run = await client.app.state.service.application.entrypoint().runtime.get_run(task["id"])
                if run.state.value == "completed":
                    return
                await asyncio.sleep(0.01)
            raise AssertionError("approved task did not finish")
        client.portal.call(wait_for_completion)
        assert next(tmp_path.rglob("note.txt")).read_text() == "blue"


def test_revoked_origin_key_cannot_be_approved_by_owner(tmp_path):
    with asking_client(tmp_path) as client:
        token = register_and_login(client)
        _, task = ask(client, token)
        headers = {"Authorization": f"Bearer {token}"}
        item = client.get("/api/approvals", headers=headers).json()["data"]["items"][0]
        key = client.get("/api/keys", headers=headers).json()["data"][0]
        client.delete(f"/api/keys/{key['key_id']}", headers=headers)
        response = client.post(f"/api/approvals/{task['id']}/decisions", headers=headers,
            json={"decision": "approve_once", "expected": item["expected"]})
        assert response.status_code == 403
        assert not list(tmp_path.rglob("note.txt"))
        response = client.post(f"/api/approvals/{task['id']}/decisions", headers=headers,
            json={"decision": "cancel", "expected": item["expected"]})
        assert response.status_code == 200, response.text


async def test_execution_grant_persists_in_database(tmp_path):
    database = Database(DatabaseSettings(url=f"sqlite+aiosqlite:///{tmp_path}/keys.db"))
    await database.start()
    try:
        await create_host_schema(database)
        store = DatabaseUserStore(database)
        original = UserRecord(user_id="user", username="alice", password_hash="hash",
            execution_policy=ExecutionPolicy(shell="deny", on_approval_required="deny"))
        await store.save(original)
        reloaded = await DatabaseUserStore(database).get_by_id("user")
        assert reloaded.execution_policy == original.execution_policy
    finally:
        await database.stop()


def test_expired_approval_is_cancelled_without_execution(tmp_path, monkeypatch):
    with asking_client(tmp_path) as client:
        token = register_and_login(client)
        _, task = ask(client, token)
        headers = {"Authorization": f"Bearer {token}"}
        item = client.get("/api/approvals", headers=headers).json()["data"]["items"][0]
        now = utc_now() + timedelta(days=2)
        monkeypatch.setattr("app.v2.server.conversations.runs.utc_now", lambda: now)
        response = client.post(f"/api/approvals/{task['id']}/decisions", headers=headers,
            json={"decision": "approve_once", "expected": item["expected"]})
        assert response.status_code == 409
        assert not list(tmp_path.rglob("note.txt"))


def test_approval_maintenance_cancels_expired_waiters(tmp_path, monkeypatch):
    with asking_client(tmp_path) as client:
        token = register_and_login(client)
        _, task = ask(client, token)
        monkeypatch.setattr("app.v2.server.conversations.runs.utc_now",
                            lambda: utc_now() + timedelta(days=2))
        host = client.app.state.service
        client.portal.call(host.conversations.runs.expire_approvals, host.threads, host.contexts.for_user)
        async def state():
            return (await host.application.entrypoint().runtime.get_run(task["id"])).state.value
        assert client.portal.call(state) == "cancelled"
        assert not list(tmp_path.rglob("note.txt"))


def test_invalid_policy_and_unsupported_network_grants_are_rejected(client):
    token = register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    for policy in [{"shell": "approve_all"}, {"network": "all"}, {"approval_timeout_seconds": 0}]:
        assert client.put("/api/auth/execution-policy", headers=headers, json=policy).status_code == 422


def test_agent_ceiling_blocks_user_auto_authorization(tmp_path):
    with asking_client(tmp_path) as client:
        token = register_and_login(client)
        record = issue(client, token, policy={"shell": "sandboxed"})
        headers = {"Authorization": f"Bearer {token}"}
        client.put(f"/api/agents/{record['agent_id']}", headers=headers,
            json={"name": "Worker", "tools": ["file_write"], "execution_policy": {"shell": "ask"}})
        task = send(client, record["api_key"], "write")["result"]["task"]
        assert task["status"]["state"] == "TASK_STATE_INPUT_REQUIRED"


def test_user_settings_are_isolated_and_keys_cannot_change_them(client):
    token = register_and_login(client)
    other = register_and_login(client, "other")
    headers = {"Authorization": f"Bearer {token}"}
    key = issue(client, token, policy={"shell": "sandboxed"})
    assert "execution_policy" not in key
    other_headers = {"Authorization": f"Bearer {other}"}
    assert client.get("/api/auth/execution-policy", headers=other_headers).json()["data"]["shell"] == "ask"
    response = client.put("/api/auth/execution-policy",
        headers={"Authorization": f"Bearer {key['api_key']}"}, json={"shell": "deny"})
    assert response.status_code == 401
    assert client.get("/api/auth/execution-policy", headers=headers).json()["data"]["shell"] == "sandboxed"
    assert client.post("/api/keys", headers=headers,
                       json={"execution_policy": {"shell": "sandboxed"}}).status_code == 422


def test_web_conversation_uses_the_users_execution_policy(tmp_path):
    from tests.app.v2.server.test_agui_resume import _asking_service, _ask, _kinds
    with TestClient(create_app(service=_asking_service(tmp_path))) as client:
        token = register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        assert client.put("/api/auth/execution-policy", headers=headers,
                          json={"shell": "sandboxed"}).status_code == 200
        frames = _ask(client, token)
        assert "sage.interaction.requested" not in _kinds(frames)
        assert next(tmp_path.rglob("note.txt")).read_text() == "blue"


def test_existing_keys_share_changed_user_settings(tmp_path):
    provider = ScriptedModelProvider((_step(1, "write", "file_write",
        {"file_path": "shared.txt", "content": "blue"}), _step(2, "done"),
        _step(3, "write", "file_write", {"file_path": "shared.txt", "content": "green"}),
        _step(4, "done")))
    with TestClient(create_app(service=make_test_service(tmp_path, model_provider=provider))) as client:
        token = register_and_login(client)
        first = issue(client, token)
        second = issue(client, token, agent_id=first["agent_id"])
        client.put("/api/auth/execution-policy", headers={"Authorization": f"Bearer {token}"},
                   json={"shell": "sandboxed"})
        for key in [first, second]:
            response = send(client, key["api_key"], "write", message_id=key["key_id"])
            assert "result" in response, response
            task = response["result"]["task"]
            assert task["status"]["state"] == "TASK_STATE_COMPLETED"
        assert next(tmp_path.rglob("shared.txt")).read_text() == "green"


def test_pending_run_cannot_gain_permission_from_user_setting_changes(tmp_path):
    from app.v2.server.runtime.policy import frozen_execution, live_execution_policy
    with asking_client(tmp_path) as client:
        token = register_and_login(client)
        _, task = ask(client, token)
        headers = {"Authorization": f"Bearer {token}"}
        client.put("/api/auth/execution-policy", headers=headers, json={"shell": "sandboxed"})
        host = client.app.state.service
        user_id = client.get("/api/auth/session", headers=headers).json()["data"]["user_id"]
        async def policies():
            command = await host.application.entrypoint().runtime.session_store.get_start_command(task["id"])
            _, frozen = frozen_execution(command)
            live = await live_execution_policy(command, users=host.users, keys=host.credentials.keys,
                catalog=host.catalog, settings=host.settings, user_id=user_id)
            return frozen.shell, live.shell
        assert client.portal.call(policies) == ("ask", "ask")
        client.put("/api/auth/execution-policy", headers=headers, json={"shell": "deny"})
        assert client.portal.call(policies) == ("ask", "deny")


def test_automatic_shell_runs_and_preserves_workspace_after_cleanup(tmp_path):
    provider = ScriptedModelProvider((_step(1, "run", "execute_shell_command",
        {"command": "printf blue > shell_result.txt"}), _step(2, "done")))
    host = make_test_service(tmp_path, model_provider=provider)
    with TestClient(create_app(service=host)) as client:
        token = register_and_login(client)
        key = issue(client, token, policy={"shell": "sandboxed"})
        task = send(client, key["api_key"], "run")["result"]["task"]
        assert task["status"]["state"] == "TASK_STATE_COMPLETED"
        files = list(tmp_path.rglob("shell_result.txt"))
        assert len(files) == 1
        assert files[0].read_text() == "blue"

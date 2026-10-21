"""Actual Server Package authority and workspace lifecycle boundaries."""

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from anyio.from_thread import BlockingPortal
    from app.v2.server.conversations.agui.service import ConversationService
    from app.v2.server.identity.users import UserRecord
    from app.v2.server.packages.management import ServerAgentManagement

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.v2.server.main import create_app
from app.v2.server.routers.files import workspace_identity
from app.v2.server.conversations.bindings import WorkspaceSessionPage
from tests.app.v2.server.conftest import register_and_login
from tests.app.v2.server.test_external_chat import make_host, setup_agent


def _body(session, agent=None, package=None):
    body = {"threadId": session, "runId": "first", "messages": [{"id": "m", "role": "user", "content": "hello"}]}
    if agent:
        body["forwardedProps"] = {"agentId": agent}
    if package:
        body["agent_package"] = package
    return body


def test_independent_react_package_runs_and_owns_its_files_without_catalog_agent(tmp_path):
    host = make_host(tmp_path)
    with TestClient(create_app(host)) as client:
        client.headers["Authorization"] = "Bearer " + register_and_login(client)
        package = client.get("/api/agent-packages/template").json()["data"]
        response = client.post("/api/agent-package", json=_body("package-workspace", package=package))
        assert response.status_code == 200, response.text
        async def state():
            return (await host.application.runtime.session_store.list_session_runs("package-workspace"))[0].state.value
        assert cast('BlockingPortal', client.portal).call(state) == "completed", response.text
        assert '"RUN_FINISHED"' in response.text
        thread = client.get("/api/threads/package-workspace").json()["data"]
        workspace = host.paths.workspace_path(thread["user_id"], thread["agent_id"])
        (workspace / "owned.txt").write_text("owned")
        response = client.delete("/api/workspace/files", params={"thread_id": thread["thread_id"], "path": "owned.txt"})
        assert response.status_code == 200, response.text
        assert not (workspace / "owned.txt").exists()


def test_native_delete_cannot_cross_unfinished_completion_callback(tmp_path):
    host = make_host(tmp_path)
    with TestClient(create_app(host)) as client:
        token = setup_agent(client)
        agent = client.headers.pop("SAGE-AGENT-ID")
        client.headers["Authorization"] = "Bearer " + token
        async def gates():
            return asyncio.Event(), asyncio.Event()
        entered, release = cast('BlockingPortal', client.portal).call(gates)
        original = host.threads.upsert
        calls = 0
        async def upsert(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                entered.set()
                await release.wait()
            return await original(*args, **kwargs)
        host.threads.upsert = upsert
        try:
            response = client.post("/api/agent", json=_body("delete-race", agent=agent))
            assert response.status_code == 200, response.text
            async def wait():
                await asyncio.wait_for(entered.wait(), 3)
            cast('BlockingPortal', client.portal).call(wait)
            response = client.delete("/api/threads/delete-race")
            assert response.status_code == 409, response.text
        finally:
            async def finish():
                release.set()
                async with asyncio.timeout(3):
                    while host.execution._drives:
                        await asyncio.sleep(.01)
            cast('BlockingPortal', client.portal).call(finish)
        response = client.delete("/api/threads/delete-race")
        assert response.status_code == 200, response.text
        assert client.get("/api/threads/delete-race").status_code == 404


async def test_workspace_path_uses_authorized_latest_projection_without_loading_history():
    command = SimpleNamespace(agent_id="agent", config=SimpleNamespace(metadata={"server_v2.workspace_user_id": "tenant"}))
    access = SimpleNamespace(
        latest_session_start_command=AsyncMock(return_value=command),
        get_session=AsyncMock(side_effect=AssertionError("assembled Session history for a path lookup")),
        list_session_runs=AsyncMock(side_effect=AssertionError("listed all historical Runs for a path lookup")),
    )
    record = SimpleNamespace(user_id="owner", thread_id="s", agent_id="agent")
    host = SimpleNamespace(threads=SimpleNamespace(find=AsyncMock(return_value=record)),
        conversations=SimpleNamespace(session_access=access, context_for=lambda owner: owner))
    user = SimpleNamespace(user_id="owner", role="user")
    assert await workspace_identity(host, user, user, "s", None) == ("tenant", "agent")
    access.latest_session_start_command.assert_awaited_once_with("s", "owner")


async def test_idle_probe_uses_target_binding_pages_and_never_loads_owner_history():
    from app.v2.server.conversations.cleanup import require_idle
    threads = SimpleNamespace(
        workspace_session_page=AsyncMock(return_value=WorkspaceSessionPage(["root"], [], None)),
        list_for=AsyncMock(side_effect=AssertionError("scanned every thread owned by the user")),
    )
    store = SimpleNamespace(has_nonterminal_session_trees=AsyncMock(return_value=False),
        list_dispatchable_runs=AsyncMock(side_effect=AssertionError("scanned global dispatchable Runs")))
    service = SimpleNamespace(threads=threads, application=SimpleNamespace(runtime=SimpleNamespace(session_store=store)),
        runs=SimpleNamespace(execution=SimpleNamespace(workspace_driving=lambda *_: False)))
    await require_idle(service, "tenant", "agent", owner_id="owner")
    store.has_nonterminal_session_trees.assert_awaited_once_with(["root"])
    threads.workspace_session_page.assert_awaited_once_with("tenant", "agent", owner_id="owner", cursor=None, limit=200)


@pytest.mark.parametrize("change", [None, "package", "user", "server"])
def test_independent_package_approval_respects_current_authority_and_workspace(tmp_path, change):
    from sagents.v2.testing.plugins import ScriptedModelProvider
    from tests.app.v2.server.conftest import CompletingJudgeModel
    from tests.app.v2.server.test_a2a_resume import _step
    host = make_host(tmp_path)
    host.execution.fallback_model = CompletingJudgeModel(ScriptedModelProvider((
        _step(1, "", "file_write", {"file_path": "approved.txt", "content": "kept"}),
        _step(2, "done"),
    )))
    with TestClient(create_app(host)) as client:
        client.headers["Authorization"] = "Bearer " + register_and_login(client)
        assert client.put("/api/auth/execution-policy", json={"shell": "ask"}).status_code == 200
        package = client.get("/api/agent-packages/template").json()["data"]
        package["manifest"]["agents"]["assistant"]["tools"] = ["file_write"]
        response = client.post("/api/agent-package", json=_body("package-approval", package=package))
        assert response.status_code == 200, response.text
        listed = client.get("/api/approvals")
        assert listed.status_code == 200, listed.text
        item = listed.json()["data"]["items"][0]
        if change == "package":
            async def reject(action, bundle, context):
                raise PermissionError("package execution revoked")
            cast('ServerAgentManagement', host.agent_management).policy.package_authorizer = reject
        elif change == "user":
            assert client.put("/api/auth/execution-policy", json={"shell": "deny", "on_approval_required": "deny"}).status_code == 200
        elif change == "server":
            from dataclasses import replace
            host.settings = replace(host.settings, execution_shell_mode="deny")
            cast('ConversationService', host.conversations).runs.settings = host.settings
        response = client.post(f"/api/approvals/{item['run_id']}/decisions", json={"decision": "approve_once", "expected": item["expected"]})
        if change == "package":
            assert response.status_code == 403, response.text
            assert not list(tmp_path.rglob("approved.txt"))
            return
        assert response.status_code == 200, response.text
        async def wait():
            async with asyncio.timeout(3):
                while (await host.application.runtime.get_run(item["run_id"])).state.value in {"resuming", "running", "queued"}:
                    await asyncio.sleep(.01)
        cast('BlockingPortal', client.portal).call(wait)
        if change:
            assert not list(tmp_path.rglob("approved.txt"))
        else:
            assert next(tmp_path.rglob("approved.txt")).read_text() == "kept"


@pytest.mark.parametrize("empty_session", [True, False])
def test_native_history_can_be_deleted_without_a_live_catalog_agent_or_session(tmp_path, empty_session):
    host = make_host(tmp_path)
    with TestClient(create_app(host)) as client:
        token = setup_agent(client)
        agent = client.headers.pop("SAGE-AGENT-ID")
        client.headers["Authorization"] = "Bearer " + token
        if empty_session:
            async def index_only():
                users = await host.users.get_by_username("alice")
                await host.threads.upsert("empty-history", cast('UserRecord', users).user_id, agent_id=agent)
            cast('BlockingPortal', client.portal).call(index_only)
        else:
            response = client.post("/api/agent", json=_body("empty-history", agent=agent))
            assert response.status_code == 200, response.text
            async def settled():
                async with asyncio.timeout(3):
                    while host.execution._drives:
                        await asyncio.sleep(.01)
            cast('BlockingPortal', client.portal).call(settled)
        response = client.delete(f"/api/agents/{agent}")
        assert response.status_code == 200, response.text
        response = client.delete("/api/threads/empty-history")
        assert response.status_code == 200, response.text
        assert client.get("/api/threads/empty-history").status_code == 404


async def test_legacy_workspace_roots_require_the_same_tenant_even_with_the_same_owner():
    from app.v2.server.conversations.cleanup import require_idle
    def cmd(tenant):
        return SimpleNamespace(agent_id="agent", config=SimpleNamespace(metadata={"server_v2.workspace_user_id": tenant}))
    service = SimpleNamespace(
        threads=SimpleNamespace(workspace_session_page=AsyncMock(return_value=WorkspaceSessionPage([], ["other", "own"], None))),
        session_access=SimpleNamespace(latest_session_start_command=AsyncMock(side_effect=[cmd("other-tenant"), cmd("tenant")])),
        context_for=lambda _: "owner-context",
        application=SimpleNamespace(runtime=SimpleNamespace(session_store=SimpleNamespace(has_nonterminal_session_trees=AsyncMock(return_value=False)))),
        runs=SimpleNamespace(execution=SimpleNamespace(workspace_driving=lambda *_: False)))
    await require_idle(service, "tenant", "agent", owner_id="owner")
    service.application.runtime.session_store.has_nonterminal_session_trees.assert_awaited_once_with(["own"])


@pytest.mark.parametrize("cancel_prepare", [False, True])
async def test_legacy_resume_uses_claimed_workspace_and_releases_its_drive(cancel_prepare):
    from app.v2.server.conversations.runs import RunService
    from app.v2.server.conversations.bindings import SessionBinding
    from app.v2.server.runtime.execution import ProcessExecution
    from app.v2.server.identity.context import RequestContexts
    from sagents.v2.contracts.commands import StartRun
    from sagents.v2.contracts.run_state import RunState
    command = StartRun(agent_id="agent", session_id="external_" + "a" * 64, input=(),
        resolved_spec_hash="sha256:test", idempotency_key="legacy")
    threads = SimpleNamespace(binding=AsyncMock(return_value=SessionBinding(cast(str, command.session_id), "owner", "physical-tenant", "agent")))
    entered, release = asyncio.Event(), asyncio.Event()
    future = asyncio.get_running_loop().create_future()
    async def load(*args):
        entered.set()
        if cancel_prepare:
            await release.wait()
        return "loaded"
    app = SimpleNamespace(runtime=SimpleNamespace(get_run=AsyncMock(return_value=SimpleNamespace(state=RunState.RESUMING))),
        agent_for_run=load, entrypoint=lambda: SimpleNamespace(continue_run=AsyncMock(return_value=future)))
    execution = ProcessExecution()
    service = RunService(application=app, session_access=SimpleNamespace(get_start_command=AsyncMock(return_value=command)),
        execution=execution, host=SimpleNamespace(threads=threads))
    task = asyncio.create_task(service.continue_detached_run("run", RequestContexts("en").for_user("owner"),
        user_id="owner", session_id=cast(str, command.session_id), label="legacy"))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        if cancel_prepare:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert not execution.workspace_driving("physical-tenant", "agent")
        else:
            await task
            assert execution.workspace_driving("physical-tenant", "agent")
            assert not execution.workspace_driving("owner", "agent")
            future.set_result(SimpleNamespace(state=RunState.COMPLETED))
            await asyncio.gather(*execution._tasks)
            assert not execution.workspace_driving("physical-tenant", "agent")
        assert not service.workspace_lock("physical-tenant", "agent").locked()
        assert not command.config.metadata, "claim resolution must not mutate the durable legacy command"
    finally:
        release.set()
        await execution.close()
        await asyncio.gather(task, return_exceptions=True)


async def test_workspace_claim_page_never_includes_another_owner_same_package_id(tmp_path):
    from app.v2.server.conversations.repository import DatabaseThreadIndex
    from app.v2.server.database import Database, DatabaseSettings
    from app.v2.server.database.schema import create_host_schema
    from app.v2.server.conversations.bindings import SessionBinding
    database = Database(DatabaseSettings(url=f"sqlite+aiosqlite:///{tmp_path}/workspace-index.db"))
    await database.start()
    try:
        await create_host_schema(database)
        index = DatabaseThreadIndex(database)
        await index.upsert("other-legacy", "other", agent_id="assistant")
        await index.upsert("owned-legacy", "owner", agent_id="assistant")
        await index.bind(SessionBinding("owned-claim-only", "owner", "owner", "assistant"))
        page = await index.workspace_session_page("owner", "assistant", owner_id="owner")
        assert page.session_ids == ["owned-claim-only"]
        assert page.legacy_session_ids == ["owned-legacy"]
        assert page.next_cursor is None
    finally:
        await database.stop()

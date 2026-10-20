"""Run admission and deletion must not cross while a filesystem worker runs."""
import asyncio
from types import SimpleNamespace

import pytest

from app.v2.server.conversations.cleanup import finish_file_operation, require_idle
from app.v2.server.conversations.runs import RunService
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.commands import StartRun
from sagents.v2.contracts.run_state import RunState


@pytest.mark.asyncio
@pytest.mark.parametrize("state,driving", [
    (RunState.RUNNING, False), (RunState.SUSPENDED, False),
    (RunState.CANCELLED, True), (RunState.COMPLETED, True),
])
async def test_idle_check_includes_suspended_and_unwinding_runs(state, driving):
    async def bindings(*args, **kwargs):
        from app.v2.server.conversations.bindings import WorkspaceSessionPage
        return WorkspaceSessionPage(["session"], [], None)
    async def nonterminal(session_ids):
        assert session_ids == ["session"]
        return state not in {RunState.CANCELLED, RunState.COMPLETED}
    store = SimpleNamespace(has_nonterminal_session_trees=nonterminal)
    service = SimpleNamespace(
        threads=SimpleNamespace(workspace_session_page=bindings),
        application=SimpleNamespace(runtime=SimpleNamespace(session_store=store)),
        runs=SimpleNamespace(execution=SimpleNamespace(workspace_driving=lambda *_: driving)),
    )
    with pytest.raises(SageV2Error, match="unfinished"):
        await require_idle(service, "tenant", "agent", owner_id="owner")


@pytest.mark.asyncio
async def test_cancelled_delete_keeps_admission_locked_until_worker_finishes():
    from threading import Event
    from app.v2.server.identity.context import RequestContexts
    entered, release = Event(), Event()
    ran = asyncio.Event()

    async def run_interface(*args, **kwargs):
        ran.set()
        async def detach():
            pass
        return SimpleNamespace(handle=SimpleNamespace(run_id="r", state=RunState.COMPLETED), detach=detach)

    service = RunService(application=SimpleNamespace(run_interface=run_interface,
        resolved_plan=SimpleNamespace(entrypoint_agent_id="agent")),
        session_access=None, execution=SimpleNamespace(driving=lambda _: False))

    async def load_agent(*args):
        return SimpleNamespace(id="agent", composition_hash="sha256:test")
    service._load_run_agent = load_agent

    def delete():
        entered.set()
        release.wait(5)

    async def cleanup():
        async with service.workspace_lock("u", "agent"):
            await finish_file_operation(delete)

    deletion = asyncio.create_task(cleanup())
    start = None
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        deletion.cancel()
        start = asyncio.create_task(service.start_detached_run(
            "ag-ui", StartRun(agent_id="agent", session_id="s", input=(), resolved_spec_hash="sha256:test", idempotency_key="cleanup"),
            RequestContexts("en").for_user("u"),
            user_id="u", session_id="s", label="test"))
        await asyncio.sleep(0.02)
        assert not ran.is_set()
        assert service.workspace_lock("u", "agent").locked()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await deletion
        await start
        assert ran.is_set()
    finally:
        release.set()
        await asyncio.gather(deletion, *([start] if start else []), return_exceptions=True)


async def test_unrelated_workspace_admission_proceeds_while_another_workspace_is_mutating():
    from app.v2.server.identity.context import RequestContexts

    async def run_interface(*args, **kwargs):
        async def detach():
            pass
        return SimpleNamespace(handle=SimpleNamespace(run_id="r", state=RunState.COMPLETED), detach=detach)

    service = RunService(application=SimpleNamespace(run_interface=run_interface),
        session_access=None, execution=SimpleNamespace(driving=lambda _: False))
    async def load_agent(command, owner):
        return SimpleNamespace(id=command.agent_id, composition_hash="sha256:test")
    service._load_run_agent = load_agent
    async with service.workspace_lock("first-tenant", "agent"):
        await asyncio.wait_for(service.start_detached_run(
            "ag-ui", StartRun(agent_id="agent", input=(), resolved_spec_hash="sha256:test", idempotency_key="other"),
            RequestContexts("en").for_user("other-tenant"),
            user_id="other-tenant", session_id="s", label="test"), 1)

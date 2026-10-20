from types import SimpleNamespace

import pytest

from app.v2.server.conversations.runs import RunService
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.contracts.run_state import RunState


@pytest.mark.asyncio
@pytest.mark.parametrize("waiting", [("waiting_a", "waiting_b"), ("waiting_b",), ()])
async def test_approval_maintenance_only_loads_suspended_candidates_as_their_owner(waiting):
    threads = [
        SimpleNamespace(thread_id="completed_history", user_id="owner_old"),
        SimpleNamespace(thread_id="waiting_a", user_id="owner_a"),
        SimpleNamespace(thread_id="waiting_b", user_id="owner_b"),
    ]
    contexts = {thread.user_id: RequestContext(actor=ActorRef(
        principal_id=thread.user_id, principal_type=PrincipalType.USER,
    )) for thread in threads}
    filtered, loaded, cancelled, authorized = [], [], [], []

    async def scan(**kwargs):
        return SimpleNamespace(items=threads, next_cursor=None)

    async def scan_snapshot():
        return "waiting_b", len(threads)

    async def filter_suspended_session_ids(session_ids):
        filtered.extend(session_ids)
        return set(waiting)

    async def list_session_runs(session_id, context):
        loaded.append(session_id)
        authorized.append((session_id, context))
        if session_id == "completed_history":
            return [SimpleNamespace(state=RunState.COMPLETED)]
        return [SimpleNamespace(run_id=f"run:{session_id}", state=RunState.SUSPENDED,
                                suspension_id=f"suspension:{session_id}", revision=3)]

    async def get_suspension(suspension_id, context):
        session_id = suspension_id.split(":", 1)[1]
        authorized.append((session_id, context))
        return SimpleNamespace(interaction_id=f"interaction:{session_id}")

    async def get_interaction(interaction_id, context):
        session_id = interaction_id.split(":", 1)[1]
        authorized.append((session_id, context))
        return SimpleNamespace(interaction_id=interaction_id)

    async def approval_expired(run, interaction):
        return True

    async def cancel_run(run_id, context, *, expected_revision, reason):
        session_id = run_id.split(":", 1)[1]
        authorized.append((session_id, context))
        cancelled.append((run_id, expected_revision, reason))

    service = RunService(
        application=SimpleNamespace(runtime=SimpleNamespace(session_store=SimpleNamespace(
            filter_suspended_session_ids=filter_suspended_session_ids))),
        session_access=SimpleNamespace(list_session_runs=list_session_runs,
            get_suspension=get_suspension, get_interaction=get_interaction),
        execution=None,
    )
    service.approval_expired = approval_expired
    service.cancel_run = cancel_run

    await service.expire_approvals(SimpleNamespace(scan=scan, scan_snapshot=scan_snapshot), contexts.__getitem__)

    assert loaded == list(waiting), "Maintenance loaded sessions without suspended runs"
    assert set(filtered) == {thread.thread_id for thread in threads}
    assert cancelled == [(f"run:{session_id}", 3, "approval_timeout") for session_id in waiting]
    owners = {thread.thread_id: thread.user_id for thread in threads}
    assert all(context is contexts[owners[session_id]] for session_id, context in authorized)


@pytest.mark.asyncio
async def test_approval_maintenance_rotates_bounded_primary_key_pages():
    scans = []
    async def scan(*, limit, cursor, through):
        assert through == "z"
        scans.append((limit, cursor))
        return SimpleNamespace(items=[], next_cursor='next' if cursor is None else None)
    async def scan_snapshot():
        return "z", 400
    service = RunService(application=SimpleNamespace(runtime=SimpleNamespace(session_store=SimpleNamespace())),
        session_access=None, execution=None)
    service.approval_scan_seconds = 0
    for _ in range(3):
        await service.expire_approvals(SimpleNamespace(scan=scan, scan_snapshot=scan_snapshot), lambda _: None)
    assert scans == [(200, None), (200, 'next'), (200, None)]

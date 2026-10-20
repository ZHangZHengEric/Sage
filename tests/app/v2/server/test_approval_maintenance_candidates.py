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

    batches = []
    async def read_session_views(session_contexts, *, suspended_only, skip_inaccessible):
        assert suspended_only and skip_inaccessible
        batches.append(session_contexts)
        loaded.extend(session_contexts)
        authorized.extend(session_contexts.items())
        return {sid: (SimpleNamespace(
            run=SimpleNamespace(run_id=f"run:{sid}", state=RunState.SUSPENDED,
                                suspension_id=f"suspension:{sid}", revision=3),
            suspension=SimpleNamespace(interaction_id=f"interaction:{sid}"),
            interaction=SimpleNamespace(interaction_id=f"interaction:{sid}"), command=sid,
        ),) for sid in session_contexts}

    async def approval_expired(run, interaction, *, command):
        assert command == run.run_id.split(":", 1)[1]
        return True

    async def cancel_run(run_id, context, *, expected_revision, reason):
        session_id = run_id.split(":", 1)[1]
        authorized.append((session_id, context))
        cancelled.append((run_id, expected_revision, reason))

    service = RunService(
        application=SimpleNamespace(runtime=SimpleNamespace(session_store=SimpleNamespace(
            filter_suspended_session_ids=filter_suspended_session_ids))),
        session_access=SimpleNamespace(read_session_views=read_session_views),
        execution=None,
    )
    service.approval_expired = approval_expired
    service.cancel_run = cancel_run

    await service.expire_approvals(SimpleNamespace(scan=scan, scan_snapshot=scan_snapshot), contexts.__getitem__)

    assert loaded == list(waiting), "Maintenance loaded sessions without suspended runs"
    assert len(batches) == bool(waiting), "Maintenance queried each owner separately"
    assert set(filtered) == {thread.thread_id for thread in threads}
    assert cancelled == [(f"run:{session_id}", 3, "approval_timeout") for session_id in waiting]
    owners = {thread.thread_id: thread.user_id for thread in threads}
    assert all(context is contexts[owners[session_id]] for session_id, context in authorized)


@pytest.mark.parametrize("count", [1, 50])
async def test_pending_approvals_read_one_batch_and_preserve_reply_revisions(count):
    from unittest.mock import AsyncMock
    from datetime import timedelta
    from app.v2.server.conversations.agui.service import ConversationService
    from sagents.v2.contracts.commands import StartRun
    from sagents.v2.contracts.common import utc_now
    from sagents.v2.contracts.interactions import InteractionRequest

    requested_at = utc_now()
    context = RequestContext(actor=ActorRef(principal_id="owner", principal_type=PrincipalType.USER))
    threads = [SimpleNamespace(thread_id=f"t{i}", title=f"Title {i}") for i in range(count)]
    views = {}
    for thread in threads:
        sid = thread.thread_id
        interaction = InteractionRequest(interaction_id=f"i:{sid}", run_id=f"r:{sid}",
            interaction_type="approval", allowed_decisions=("approve", "deny"),
            payload={"tool": "shell"}, expected_revision=4, requested_at=requested_at)
        views[sid] = (SimpleNamespace(
            run=SimpleNamespace(run_id=f"r:{sid}", state=RunState.SUSPENDED, revision=7),
            suspension=SimpleNamespace(expected_revision=3), interaction=interaction,
            command=StartRun(agent_id="a", input=(), resolved_spec_hash="sha256:test", idempotency_key=sid),
        ),)
    read = AsyncMock(return_value=views)
    api = ConversationService(threads=SimpleNamespace(scan=AsyncMock(
        return_value=SimpleNamespace(items=threads, next_cursor="next-page"))),
        admission=None, runs=SimpleNamespace(settings=SimpleNamespace(approval_timeout_seconds=60)),
        application=SimpleNamespace(runtime=SimpleNamespace(session_store=SimpleNamespace(
            filter_suspended_session_ids=AsyncMock(return_value=set(views))))),
        session_access=SimpleNamespace(read_session_views=read),
        log_sink=None, context_for=lambda _: context, language="en")
    page = await api.pending_approvals("owner")
    read.assert_awaited_once_with({thread.thread_id: context for thread in threads},
                                 suspended_only=True, skip_inaccessible=True)
    assert page["next_cursor"] == "next-page"
    assert len(page["items"]) == count
    assert page["items"][0]["expected"] == {"interaction_id": "i:t0", "revision": 7,
        "suspension_revision": 3, "interaction_revision": 4}
    assert page["items"][0]["expires_at"] == (requested_at + timedelta(seconds=60)).isoformat()


async def test_broken_approval_does_not_prevent_other_owners_from_expiring():
    from unittest.mock import AsyncMock
    from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
    records = [SimpleNamespace(thread_id=sid, user_id=sid) for sid in ("broken", "healthy")]
    view = SimpleNamespace(run=SimpleNamespace(run_id="run", revision=2),
        suspension=object(), interaction=object(), command=object())
    async def read_session_views(contexts, **options):
        if "broken" in contexts:
            raise SageV2Error(RuntimeErrorInfo(code="suspension.not_found",
                category=ErrorCategory.VALIDATION, message="missing suspension"))
        return {"healthy": (view,)}
    service = RunService(application=SimpleNamespace(runtime=SimpleNamespace(session_store=SimpleNamespace())),
        session_access=SimpleNamespace(read_session_views=read_session_views), execution=None)
    service.approval_expired = AsyncMock(return_value=True)
    service.cancel_run = AsyncMock()
    await service._expire_thread_approvals(records, lambda uid: uid)
    service.cancel_run.assert_awaited_once_with("run", "healthy", expected_revision=2, reason="approval_timeout")


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

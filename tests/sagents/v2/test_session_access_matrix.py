from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from sagents.v2.runtime.session.contracts import DerivedStateStore, SessionStore

import pytest

from sagents.v2.contracts.commands import InputItem, StartRun
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import (
    ActorRef,
    PrincipalType,
    RequestContext,
)
from sagents.v2.contracts.run_state import EventCursor, RunState
from sagents.v2.runtime import HarnessRuntime
from sagents.v2.runtime.session import AuthorizedSessionAccess, EphemeralSessionStore


OWNER = RequestContext(
    actor=ActorRef(
        principal_id="owner",
        principal_type=PrincipalType.USER,
        tenant_id="tenant-a",
    )
)
OTHER = RequestContext(
    actor=ActorRef(
        principal_id="other",
        principal_type=PrincipalType.USER,
        tenant_id="tenant-b",
    )
)
ADMIN = RequestContext(
    actor=ActorRef(
        principal_id="admin",
        principal_type=PrincipalType.SERVICE,
        tenant_id="operations",
        scopes=("session.admin",),
    )
)
SAME_ID_SERVICE = RequestContext(
    actor=ActorRef(
        principal_id="owner",
        principal_type=PrincipalType.SERVICE,
        tenant_id="tenant-a",
    )
)


async def setup_access():
    store = EphemeralSessionStore()
    runtime = HarnessRuntime(cast('SessionStore', store))
    handle = await runtime.start_run(
        StartRun(
            agent_id="agent",
            input=(
                InputItem(
                    role="user",
                    content=(TextBlock(text="tenant private input"),),
                ),
            ),
            resolved_spec_hash="sha256:access",
            idempotency_key="access-start",
        ),
        OWNER,
    )
    return store, AuthorizedSessionAccess(cast('SessionStore', store), runtime=runtime), handle


@pytest.mark.asyncio
async def test_owner_and_admin_can_read_through_authorized_access():
    _, access, handle = await setup_access()

    assert (await access.get_run(handle.run_id, OWNER)).run_id == handle.run_id
    assert (await access.get_session(handle.session_id, ADMIN)).session_id == (
        handle.session_id
    )
    events = await access.read_events(handle.run_id, OWNER)
    assert events[0].type == "run.accepted"
    assert await access.list_session_commit_proposals(handle.session_id, OWNER) == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ("run", "events", "proposals", "delete"))
async def test_cross_tenant_read_subscribe_and_delete_are_rejected(operation):
    _, access, handle = await setup_access()

    with pytest.raises(SageV2Error) as denied:
        if operation == "run":
            await access.get_run(handle.run_id, OTHER)
        elif operation == "events":
            await access.read_events(handle.run_id, OTHER)
        elif operation == "proposals":
            await access.list_session_commit_proposals(handle.session_id, OTHER)
        else:
            await access.delete_session(handle.session_id, OTHER)

    assert denied.value.info.code == "session.actor_not_authorized"


@pytest.mark.asyncio
async def test_authorized_delete_forgets_all_independent_derived_state():
    class DerivedState:
        def __init__(self):
            self.forgotten = []

        async def forget_session(self, session_id):
            self.forgotten.append(session_id)

    store, _, handle = await setup_access()
    derived_state = DerivedState()
    session_memory = DerivedState()
    access = AuthorizedSessionAccess(
        cast('SessionStore', store),
        runtime=HarnessRuntime(cast('SessionStore', store)),
        derived_state=cast('DerivedStateStore | None', derived_state),
        derived_state_cleaners=(session_memory,),
    )
    run = await store.get_run(handle.run_id)
    await store.commit_run(
        run_id=handle.run_id,
        expected_revision=run.revision,
        expected_states={RunState.QUEUED},
        new_state=RunState.CANCELLED,
        drafts=(),
        context=OWNER,
        idempotency_key="finish-before-delete",
    )

    await access.delete_session(handle.session_id, OWNER)

    assert derived_state.forgotten == [handle.session_id]
    assert session_memory.forgotten == [handle.session_id]


@pytest.mark.asyncio
async def test_session_tree_subscription_authorizes_before_first_event():
    _, access, handle = await setup_access()

    denied_stream = access.subscribe_session_tree(handle.session_id, OTHER)
    with pytest.raises(SageV2Error) as denied:
        await anext(denied_stream)
    assert denied.value.info.code == "session.actor_not_authorized"

    owner_stream = access.subscribe_session_tree(handle.session_id, OWNER)
    first = await anext(owner_stream)
    assert first.session.session_id == handle.session_id
    await getattr(owner_stream, 'aclose')()


@pytest.mark.asyncio
async def test_principal_type_is_part_of_owner_and_start_idempotency_scope():
    store, access, first = await setup_access()
    runtime = HarnessRuntime(cast('SessionStore', store))
    second = await runtime.start_run(
        StartRun(
            agent_id="agent",
            input=(InputItem(role="user", content=(TextBlock(text="service input"),)),),
            resolved_spec_hash="sha256:access",
            idempotency_key="access-start",
        ),
        SAME_ID_SERVICE,
    )

    assert second.run_id != first.run_id
    assert second.session_id != first.session_id
    with pytest.raises(SageV2Error) as denied:
        await access.get_session(first.session_id, SAME_ID_SERVICE)
    assert denied.value.info.code == "session.actor_not_authorized"


@pytest.mark.asyncio
async def test_event_subscription_authorizes_before_replay():
    _, access, handle = await setup_access()
    stream = access.subscribe_events(
        EventCursor(run_id=handle.run_id, run_sequence=0), OTHER
    )
    with pytest.raises(SageV2Error) as denied:
        await anext(stream)
    assert denied.value.info.code == "session.actor_not_authorized"


@pytest.mark.asyncio
async def test_owner_and_principal_type_persist_with_legacy_derivation():
    store, _, handle = await setup_access()
    payload = await store.export_state()
    owner = payload["sessions"][0]["owner"]
    assert owner == {
        "principal_id": "owner",
        "principal_type": "user",
        "tenant_id": "tenant-a",
        "delegated_by": None,
        "scopes": [],
    }
    assert payload["start_idempotency"][0]["principal_type"] == "user"

    payload["sessions"][0].pop("owner")
    payload["start_idempotency"][0].pop("principal_type")
    restored = EphemeralSessionStore()
    await restored.load_state(payload)
    await restored.authorize_session_actor(handle.session_id, OWNER)
    with pytest.raises(SageV2Error):
        await restored.authorize_session_actor(handle.session_id, SAME_ID_SERVICE)
    # Loading legacy v4 facts derives owner only in memory; the caller's
    # read-side payload is not rewritten as a migration side effect.
    assert "owner" not in payload["sessions"][0]
    assert "principal_type" not in payload["start_idempotency"][0]


async def suspend_access_run(store, access, run_id):
    from sagents.v2.contracts.checkpoint import Checkpoint, Suspension, SuspensionReason
    from sagents.v2.contracts.common import new_id, utc_now

    run = await store.get_run(run_id)
    running = await store.commit_run(
        run_id=run_id, expected_revision=run.revision,
        expected_states={RunState.QUEUED}, new_state=RunState.RUNNING,
        drafts=(), context=OWNER, idempotency_key=f"running:{run_id}",
    )
    run = running.run
    checkpoint = Checkpoint(
        checkpoint_id=new_id("checkpoint"), checkpoint_codec_version="test/1",
        session_id=run.session_id, run_id=run_id,
        run_sequence=run.last_run_sequence,
        session_revision=(await store.get_session(run.session_id)).revision,
        state={}, resolved_spec_hash=run.resolved_spec_hash, created_at=utc_now(),
    )
    return await access.runtime.commit_suspension(
        run_id=run_id, expected_revision=run.revision, checkpoint=checkpoint,
        suspension=Suspension(
            suspension_id=new_id("suspension"), run_id=run_id,
            reason=SuspensionReason.MANUAL_PAUSE, blocking_scope="run",
            checkpoint_id=checkpoint.checkpoint_id,
            checkpoint_sequence=run.last_run_sequence,
            resume_policy="explicit", requested_at=utc_now(),
        ), context=OWNER, idempotency_key=f"suspend:{run_id}",
    )


def replacement_command(session_id, key="replacement"):
    return StartRun(
        session_id=session_id, agent_id="agent",
        input=(InputItem(role="user", content=(TextBlock(text="new direction"),)),),
        resolved_spec_hash="sha256:access", idempotency_key=key,
    )


@pytest.mark.asyncio
async def test_fresh_user_input_cancels_suspended_run_before_starting_same_session():
    store, access, handle = await setup_access()
    old = await suspend_access_run(store, access, handle.run_id)
    command = replacement_command(handle.session_id)
    await access.supersede_suspended_run(command, OWNER)
    assert (await store.get_run(old.run_id)).state == RunState.CANCELLED
    assert (await store.get_suspension(old.suspension_id)).status.value == "cancelled"
    fresh = await access.runtime.start_run(command, OWNER)
    assert fresh.session_id == handle.session_id
    assert fresh.run_id != old.run_id
    assert (await store.read_events(old.run_id))[-1].data.reason == "superseded_by_user_message"
    await suspend_access_run(store, access, fresh.run_id)
    # A replay of either admitted request cannot cancel the active suspended Run.
    original = await store.get_start_command(old.run_id)
    await access.supersede_suspended_run(original.model_copy(update={"session_id": handle.session_id}), OWNER)
    await access.supersede_suspended_run(command, OWNER)
    assert (await store.get_run(fresh.run_id)).state == RunState.SUSPENDED


@pytest.mark.asyncio
async def test_fresh_input_never_cancels_running_or_foreign_runs():
    store, access, handle = await setup_access()
    command = replacement_command(handle.session_id)
    await access.supersede_suspended_run(command, OWNER)
    assert (await store.get_run(handle.run_id)).state == RunState.QUEUED
    await suspend_access_run(store, access, handle.run_id)
    with pytest.raises(SageV2Error, match="does not own"):
        await access.supersede_suspended_run(command, OTHER)
    assert (await store.get_run(handle.run_id)).state == RunState.SUSPENDED


@pytest.mark.asyncio
async def test_replacement_does_not_cancel_a_run_that_resumed_concurrently(monkeypatch):
    store, access, handle = await setup_access()
    old = await suspend_access_run(store, access, handle.run_id)
    cancel = access.runtime.cancel_run

    async def race(command, context):
        await store.commit_run(
            run_id=old.run_id, expected_revision=old.revision,
            expected_states={RunState.SUSPENDED}, new_state=RunState.RESUMING,
            drafts=(), context=context, idempotency_key="concurrent-resume",
        )
        return await cancel(command, context)

    monkeypatch.setattr(access.runtime, "cancel_run", race)
    with pytest.raises(SageV2Error) as rejected:
        await access.supersede_suspended_run(replacement_command(handle.session_id), OWNER)
    assert rejected.value.info.code == "run.revision_conflict"
    assert (await store.get_run(old.run_id)).state == RunState.RESUMING
    assert len(await store.list_session_runs(handle.session_id)) == 1

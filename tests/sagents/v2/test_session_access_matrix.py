from __future__ import annotations

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
    runtime = HarnessRuntime(store)
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
    return store, AuthorizedSessionAccess(store, runtime=runtime), handle


@pytest.mark.asyncio
async def test_owner_and_admin_can_read_through_authorized_access():
    _, access, handle = await setup_access()

    assert (await access.get_run(handle.run_id, OWNER)).run_id == handle.run_id
    assert (await access.get_session(handle.session_id, ADMIN)).session_id == (
        handle.session_id
    )
    events = await access.read_events(handle.run_id, OWNER)
    assert events[0].type == "run.accepted"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ("run", "events", "delete"))
async def test_cross_tenant_read_subscribe_and_delete_are_rejected(operation):
    _, access, handle = await setup_access()

    with pytest.raises(SageV2Error) as denied:
        if operation == "run":
            await access.get_run(handle.run_id, OTHER)
        elif operation == "events":
            await access.read_events(handle.run_id, OTHER)
        else:
            await access.delete_session(handle.session_id, OTHER)

    assert denied.value.info.code == "session.actor_not_authorized"


@pytest.mark.asyncio
async def test_authorized_delete_forgets_independent_derived_state():
    class DerivedState:
        def __init__(self):
            self.forgotten = []

        async def forget_session(self, session_id):
            self.forgotten.append(session_id)

    store, _, handle = await setup_access()
    derived_state = DerivedState()
    access = AuthorizedSessionAccess(
        store,
        runtime=HarnessRuntime(store),
        derived_state=derived_state,
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
    await owner_stream.aclose()


@pytest.mark.asyncio
async def test_principal_type_is_part_of_owner_and_start_idempotency_scope():
    store, access, first = await setup_access()
    runtime = HarnessRuntime(store)
    second = await runtime.start_run(
        StartRun(
            agent_id="agent",
            input=(
                InputItem(role="user", content=(TextBlock(text="service input"),)),
            ),
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

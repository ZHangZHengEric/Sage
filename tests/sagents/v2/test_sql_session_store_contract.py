"""Public persistence contracts shared by the SQL SessionStore backends."""

import os
import uuid
from unittest.mock import AsyncMock

import pytest

from sagents.v2.contracts.commands import InputItem, StartRun
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.events import RunEventData
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import (
    ActorRef,
    PrincipalType,
    RequestContext,
    TraceContext,
)
from sagents.v2.contracts.run_state import RunState
from sagents.v2.runtime.session.contracts import EventDraft
from sagents.v2.runtime.session.plugins.mysql import MysqlSessionStore
from sagents.v2.runtime.session.plugins.postgres import PostgresSessionStore
from sagents.v2.runtime.session.state import SessionStoreCoordinator


CONTEXT = RequestContext(
    actor=ActorRef(
        principal_id="user_test",
        principal_type=PrincipalType.USER,
        tenant_id="tenant_test",
    ),
    trace=TraceContext(correlation_id="correlation_test"),
)


def command():
    return StartRun(
        agent_id="agent_test",
        input=(InputItem(role="user", content=(TextBlock(text="hello"),)),),
        resolved_spec_hash="sha256:spec",
        idempotency_key="start_1",
    )


@pytest.fixture(
    params=(MysqlSessionStore, PostgresSessionStore), ids=("mysql", "postgres")
)
def sql_backend(request):
    return request.param


@pytest.fixture
async def durable_store_factory(sql_backend):
    backend = "MYSQL" if sql_backend is MysqlSessionStore else "POSTGRES"
    variable = f"SAGE_V2_TEST_{backend}_DSN"
    dsn = os.environ.get(variable, "").strip()
    if not dsn:
        pytest.skip(f"set {variable} to run live {backend} tests")
    namespace = f"sage_v2_{uuid.uuid4().hex[:12]}"
    options = {
        "table_prefix" if sql_backend is MysqlSessionStore else "schema": namespace
    }
    stores = []

    def open_store():
        store = sql_backend(dsn, **options)
        stores.append(store)
        return store

    try:
        yield open_store
    finally:
        for store in reversed(stores):
            await store.close()


async def test_authorization_loads_persisted_session_before_owner_check(sql_backend):
    source = SessionStoreCoordinator()
    created = await source.create_run(command(), CONTEXT)
    session_id = created.handle.session_id
    dsn = (
        "mysql://unused/test"
        if sql_backend is MysqlSessionStore
        else "postgresql://unused/test"
    )
    reopened = sql_backend(dsn)
    reopened._coordinator._ensure_ready = AsyncMock()
    reopened._coordinator._fetch_session = AsyncMock(
        return_value=source._dump_state_locked()
    )

    try:
        assert session_id not in reopened._coordinator._sessions
        await reopened.authorize_session_actor(session_id, CONTEXT)
        assert session_id in reopened._coordinator._sessions
        reopened._coordinator._fetch_session.assert_awaited_once_with(session_id)

        other = CONTEXT.model_copy(
            update={
                "actor": CONTEXT.actor.model_copy(update={"principal_id": "other_user"})
            }
        )
        with pytest.raises(SageV2Error) as denied:
            await reopened.authorize_session_actor(session_id, other)
        assert denied.value.info.code == "session.actor_not_authorized"
    finally:
        await reopened.close()


async def test_restart_round_trip_and_idempotent_start(durable_store_factory):
    first = durable_store_factory()
    created = await first.create_run(command(), CONTEXT)
    await first.put_derived_state(created.handle.session_id, "notes", "title", "hello")
    await first.close()

    second = durable_store_factory()
    await second.authorize_session_actor(created.handle.session_id, CONTEXT)
    run = await second.get_run(created.handle.run_id)
    session = await second.get_session(created.handle.session_id)
    events = await second.read_events(created.handle.run_id)
    duplicate = await second.create_run(command(), CONTEXT)

    assert second.capabilities["durable_across_process_restart"] is True
    assert second.capabilities["multi_process_writes"] is False
    assert run.state == RunState.QUEUED
    assert session.revision == 1
    assert [event.type for event in events] == [
        "run.accepted",
        "run.queued",
        "message.completed",
    ]
    assert duplicate.duplicate is True
    assert duplicate.handle.run_id == created.handle.run_id
    assert (
        await second.get_derived_state(created.handle.session_id, "notes", "title")
        == "hello"
    )


@pytest.mark.parametrize(
    "explicit_event", [False, True], ids=("state-transition", "explicit-event")
)
async def test_run_events_are_appended_across_commits(
    durable_store_factory, explicit_event
):
    store = durable_store_factory()
    created = await store.create_run(command(), CONTEXT)
    committed = await store.commit_run(
        run_id=created.handle.run_id,
        expected_revision=created.handle.run_revision,
        expected_states={RunState.QUEUED},
        new_state=RunState.RUNNING,
        drafts=(EventDraft(type="run.started", data=RunEventData(state="running")),)
        if explicit_event
        else (),
        context=CONTEXT,
        idempotency_key="start-execution",
    )
    assert [event.type for event in committed.events] == (
        ["run.started"] if explicit_event else []
    )
    await store.close()

    restored = durable_store_factory()
    assert (await restored.get_run(created.handle.run_id)).state == RunState.RUNNING
    events = await restored.read_events(created.handle.run_id)
    assert [event.type for event in events] == [
        "run.accepted",
        "run.queued",
        "message.completed",
    ] + (["run.started"] if explicit_event else [])
    assert [event.run_sequence for event in events] == list(range(1, len(events) + 1))


async def test_delete_session_removes_durable_rows(durable_store_factory):
    store = durable_store_factory()
    created = await store.create_run(command(), CONTEXT)
    await store.commit_run(
        run_id=created.handle.run_id,
        expected_revision=created.handle.run_revision,
        expected_states={RunState.QUEUED},
        new_state=RunState.CANCELLED,
        drafts=(),
        context=CONTEXT,
        idempotency_key="cancel-run",
    )
    session_id = created.handle.session_id
    await store.delete_session(session_id)
    with pytest.raises(SageV2Error) as missing:
        await store.get_session(session_id)
    assert missing.value.info.code == "session.not_found"
    await store.close()

    restored = durable_store_factory()
    with pytest.raises(SageV2Error) as missing:
        await restored.get_session(session_id)
    assert missing.value.info.code == "session.not_found"

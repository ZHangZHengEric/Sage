"""External Run lookup stays scoped and avoids loading every historical command."""

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from sagents.v2.contracts.run_state import RunSnapshot
    from sagents.v2.runtime.session.contracts import SessionStore

from ag_ui.core import Message

import hashlib
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from ag_ui.core import RunAgentInput

from app.v2.server.conversations.agui.service import ConversationService
from app.v2.server.conversations.bindings import SessionBinding
from app.v2.server.identity.context import RequestContexts
from sagents.v2.contracts.commands import InputItem, RunConfig, StartRun
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.run_state import RunState, SessionConcurrencyMode
from sagents.v2.runtime.observability.plugins.logging_noop import NoopLogSink
from sagents.v2.runtime.session.access import AuthorizedSessionAccess
from sagents.v2.runtime.session.state import SessionStoreCoordinator
from sagents.v2.runtime.session.plugins.filesystem import FilesystemSessionStore
from tests.app.v2.server.fakes import MemoryThreadIndex


def _key(session, client_id):
    return "external_" + hashlib.sha256(f"{session}:{client_id}".encode()).hexdigest()


def _service(store):
    access = AuthorizedSessionAccess(store)
    runs = SimpleNamespace(
        catalog=SimpleNamespace(agent_owner=AsyncMock(return_value="owner")),
        workspace_guard=lambda *_: nullcontext(),
        start_detached_run=AsyncMock(return_value="dispatched-run"),
    )
    api = ConversationService(
        threads=MemoryThreadIndex(), runs=runs,
        admission=SimpleNamespace(prepare=AsyncMock(return_value=SimpleNamespace(
            skills=(), enabled_skills=(), metadata={"new-admission": True}, agent_id="agent", max_steps=3,
            model_ready=True))),
        application=SimpleNamespace(composition_hash="sha256:new-spec"),
        session_access=access, log_sink=NoopLogSink(),
        context_for=lambda user, **_: RequestContexts("en").for_user(user), language="en",
    )
    return api


async def _seed(api, session="work", client_id="first", *, legacy=False, tenant="tenant"):
    command = StartRun(
        session_id=session, agent_id="agent",
        input=(InputItem(role="user", content=(TextBlock(text="hello"),)),),
        idempotency_key=client_id if legacy else _key(session, client_id),
        resolved_spec_hash="sha256:old-spec",
        session_concurrency_mode=SessionConcurrencyMode.SNAPSHOT_ISOLATED,
        config=RunConfig(metadata={"server_v2.external.run_id": client_id,
            "server_v2.workspace_user_id": tenant, "system_context": {"session_id": session}}),
    )
    created = await api.session_access._session_store.create_run(command, api.context_for("owner"))
    await api.threads.upsert(session, "owner", agent_id="agent")
    await api.threads.bind(SessionBinding(session, "owner", tenant, "agent"))
    return created.handle.run_id, command


def _request(client_id="first", text="hello"):
    return RunAgentInput(thread_id="work", run_id=client_id, state={}, tools=[],
        context=[], messages=cast(list[Message], [{"id": "message", "role": "user", "content": text}]),
        forwarded_props={})


@pytest.mark.parametrize("client_id", ["first", "next"])
async def test_external_start_and_retry_do_not_walk_historical_commands(client_id):
    api = _service(SessionStoreCoordinator())
    _, stored = await _seed(api)
    api.session_access.list_session_runs = AsyncMock(side_effect=AssertionError("loaded all historical Runs"))
    api.session_access.get_start_command = AsyncMock(side_effect=AssertionError("read historical commands individually"))
    stream = await api.start(_request(client_id), user_id="tenant", agent_id="agent")
    await getattr(stream, 'aclose')()
    dispatched = api.runs.start_detached_run.call_args.args[1]
    assert dispatched.idempotency_key == _key("work", client_id)
    if client_id == "first":
        assert dispatched == stored, "a retry must retain its original admitted configuration"


async def test_external_reused_client_id_rejects_changed_input_before_dispatch():
    api = _service(SessionStoreCoordinator())
    await _seed(api)
    with pytest.raises(SageV2Error) as error:
        await api.start(_request(text="different"), user_id="tenant", agent_id="agent")
    assert error.value.info.code.endswith("idempotency_conflict")
    api.runs.start_detached_run.assert_not_awaited()


async def test_external_legacy_retry_preserves_original_key_and_admitted_configuration():
    api = _service(SessionStoreCoordinator())
    _, stored = await _seed(api, legacy=True)
    api.session_access.list_session_runs = AsyncMock(side_effect=AssertionError("loaded all historical Runs"))
    stream = await api.start(_request(), user_id="tenant", agent_id="agent")
    await getattr(stream, 'aclose')()
    assert api.runs.start_detached_run.call_args.args[1] == stored


@pytest.mark.parametrize("legacy", [False, True], ids=["hashed-key", "legacy-client-key"])
async def test_external_result_uses_scoped_key_lookup_instead_of_run_history(legacy):
    api = _service(SessionStoreCoordinator())
    expected_id, _ = await _seed(api, legacy=legacy)
    await _seed(api, client_id="newer")
    api.session_access.list_session_runs = AsyncMock(side_effect=AssertionError("loaded all historical Runs"))
    api.session_access.get_start_command = AsyncMock(side_effect=AssertionError("read historical commands individually"))
    result, native_id = await api._result_with_native_run(
        user_id="tenant", agent_id="agent", session_id="work", run_id="first")
    assert native_id == expected_id
    assert result["runId"] == "first" and result["state"] == "queued"


async def test_latest_result_uses_latest_command_projection_and_its_original_key():
    api = _service(SessionStoreCoordinator())
    await _seed(api)
    expected_id, command = await _seed(api, client_id="newer", legacy=True)
    api.session_access.latest_session_start_command = AsyncMock(return_value=command)
    api.session_access.list_session_runs = AsyncMock(side_effect=AssertionError("loaded all historical Runs"))
    result, native_id = await api._result_with_native_run(
        user_id="tenant", agent_id="agent", session_id="work")
    api.session_access.latest_session_start_command.assert_awaited_once_with("work", api.context_for("owner"))
    assert result["runId"] == command.config.metadata["server_v2.external.run_id"]
    assert native_id == expected_id


@pytest.mark.parametrize("session,tenant", [("other-work", "tenant"), ("work", "another-tenant")])
async def test_external_result_never_returns_another_session_or_tenant_run(session, tenant):
    api = _service(SessionStoreCoordinator())
    await _seed(api)
    await _seed(api, session="other-work", client_id="other", tenant="tenant")
    with pytest.raises(SageV2Error) as error:
        await api.result(user_id=tenant, agent_id="agent", session_id=session, run_id="first")
    assert error.value.info.code.endswith("result_not_found")


async def test_start_lookup_checks_principal_scope_and_session_even_for_an_existing_key():
    api = _service(SessionStoreCoordinator())
    native_id, command = await _seed(api)
    access = api.session_access
    found = await access.find_start_run("work", command.idempotency_key, api.context_for("owner"))
    assert found[0].run_id == native_id and found[1] == command
    assert await access.find_start_run("other-work", command.idempotency_key, api.context_for("owner")) is None
    assert await access.find_start_run("work", command.idempotency_key, api.context_for("other-owner")) is None


@pytest.mark.parametrize("scope_change", [{"principal_id": "stranger"},
    {"principal_type": "service"}, {"tenant_id": "another-tenant"}])
async def test_start_lookup_never_crosses_any_principal_scope_dimension(scope_change):
    api = _service(SessionStoreCoordinator())
    _, command = await _seed(api)
    context = api.context_for("owner")
    actor = context.actor.model_copy(update=scope_change)
    assert await api.session_access.find_start_run("work", command.idempotency_key,
        context.model_copy(update={"actor": actor})) is None


async def test_start_lookup_restores_existing_idempotency_index_after_filesystem_restart(tmp_path):
    store = FilesystemSessionStore(tmp_path)
    try:
        api = _service(store)
        native_id, command = await _seed(api)
    finally:
        await store.close()
    restored = FilesystemSessionStore(tmp_path)
    try:
        access = AuthorizedSessionAccess(cast('SessionStore', restored))
        found = await access.find_start_run("work", command.idempotency_key, api.context_for("owner"))
        assert cast('tuple[RunSnapshot, StartRun]', found)[0].run_id == native_id and cast('tuple[RunSnapshot, StartRun]', found)[1] == command
        assert await access.find_start_run("missing", command.idempotency_key, api.context_for("owner")) is None
    finally:
        await restored.close()


async def test_start_lookup_reads_existing_redis_state_after_local_eviction():
    import fakeredis.aioredis
    from tests.sagents.v2.test_redis_mysql_session_store import Archive, store as redis_store

    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    store = redis_store(redis, Archive())
    try:
        api = _service(store)
        native_id, command = await _seed(api)
        store._evict_session_locked("work")
        found = await api.session_access.find_start_run("work", command.idempotency_key,
            api.context_for("owner"))
        assert found[0].run_id == native_id and found[1] == command
        run = found[0]
        await store.commit_run(run_id=run.run_id, expected_revision=run.revision,
            expected_states={run.state}, new_state=RunState.CANCELLED, drafts=(),
            context=api.context_for("owner"), idempotency_key="cancel-before-delete")
        await store.delete_session("work")
        assert await api.session_access.find_start_run("work", command.idempotency_key,
            api.context_for("owner")) is None
    finally:
        await store.close()


@pytest.mark.parametrize("foreign_last_run", [False, True])
async def test_unbound_legacy_session_checks_all_ownership_pages_before_binding(foreign_last_run):
    api = _service(SessionStoreCoordinator())
    for index in range(201):
        await _seed(api, client_id=f"request-{index}")
    if foreign_last_run:
        # Legacy data has no durable host binding. A late foreign tenant Run
        # must invalidate the whole Session instead of passing the first page.
        last = next(reversed(api.session_access._session_store._runs.values()))
        last.start_command.config.metadata["server_v2.workspace_user_id"] = "stranger"
    api.threads._bindings.clear()
    original = api.session_access.run_metadata_page
    api.session_access.run_metadata_page = AsyncMock(wraps=original)
    api.session_access.list_session_runs = AsyncMock(side_effect=AssertionError("loaded all historical Runs"))
    if foreign_last_run:
        with pytest.raises(SageV2Error) as error:
            await api.result(user_id="tenant", agent_id="agent", session_id="work", run_id="request-0")
        assert error.value.info.code.endswith("result_not_found")
        assert await api.threads.binding("work") is None
    else:
        result = await api.result(user_id="tenant", agent_id="agent", session_id="work", run_id="request-0")
        assert result["runId"] == "request-0"
        assert await api.threads.binding("work") == SessionBinding("work", "owner", "tenant", "agent")
    assert api.session_access.run_metadata_page.await_count == 2
    first, second = api.session_access.run_metadata_page.await_args_list
    assert first.kwargs["limit"] == 200 and second.kwargs["after"] is not None


async def test_legacy_session_with_filtered_metadata_is_never_claimed_as_an_empty_session():
    api = _service(SessionStoreCoordinator())
    # An old host index alone cannot grant access to the canonical Session.
    legacy_id = "external_" + hashlib.sha256(b'["tenant","agent","work"]').hexdigest()
    await api.session_access._session_store.create_run(StartRun(
        session_id=legacy_id, agent_id="agent", input=(), idempotency_key="first",
        resolved_spec_hash="sha256:old-spec"), api.context_for("different-owner"))
    await api.threads.upsert(legacy_id, "owner", agent_id="agent")
    assert await api.session_access.run_metadata_page([legacy_id], api.context_for("owner")) == ()
    with pytest.raises(SageV2Error):
        await api.result(user_id="tenant", agent_id="agent", session_id="work", run_id="first")
    assert await api.threads.binding(legacy_id) is None

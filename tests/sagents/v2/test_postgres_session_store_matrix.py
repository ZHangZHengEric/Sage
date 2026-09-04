from __future__ import annotations

import os
import uuid

import pytest

from sagents.v2 import SAgentBuilder
from sagents.v2.contracts.commands import InputItem, StartRun
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import (
    ActorRef,
    PrincipalType,
    RequestContext,
    TraceContext,
)
from sagents.v2.contracts.run_state import RunState, SessionConcurrencyMode
from sagents.v2.package.presets import BuiltinPackageFactory
from sagents.v2.package.manifest.runtime import CapabilitySelection
from sagents.v2.runtime.extensions.official import builtin_extension_registry
from sagents.v2.runtime.session.plugins.postgres import (
    PostgresSessionStore,
    StoreInUseError,
    _PostgresSessionState,
)
from sagents.v2.testing.plugins.scripted_model import ScriptedModelProvider


ACTOR = ActorRef(
    principal_id="user_test",
    principal_type=PrincipalType.USER,
    tenant_id="tenant_test",
)
CONTEXT = RequestContext(
    actor=ACTOR,
    trace=TraceContext(correlation_id="correlation_test"),
)


def _schema() -> str:
    return f"sage_v2_{uuid.uuid4().hex[:12]}"


def command(
    key: str = "start_1",
    *,
    session_id: str | None = None,
    mode: SessionConcurrencyMode = SessionConcurrencyMode.SERIAL,
) -> StartRun:
    return StartRun(
        session_id=session_id,
        agent_id="agent_test",
        input=(InputItem(role="user", content=(TextBlock(text="hello"),)),),
        session_concurrency_mode=mode,
        resolved_spec_hash="sha256:spec",
        idempotency_key=key,
    )


async def _cancel(store, created, key: str) -> None:
    await store.commit_run(
        run_id=created.handle.run_id,
        expected_revision=created.handle.run_revision,
        expected_states={RunState.QUEUED},
        new_state=RunState.CANCELLED,
        drafts=(),
        context=CONTEXT,
        idempotency_key=key,
    )


def test_postgres_plugin_requires_dsn_in_declaration():
    inventory = {
        value["plugin_id"]: value for value in builtin_extension_registry().inventory()
    }
    plugin = inventory["sage.session.postgres"]
    assert plugin["version"] == "2.2.0"
    assert plugin["capabilities"]["durable"] is True
    assert plugin["capabilities"]["global_session_index"] is False
    assert plugin["capabilities"]["multi_process_writes"] is False
    assert "dsn" in plugin["config_schema"]["required"]
    assert "dsn_env" not in plugin["config_schema"]["properties"]
    assert "lock_key" not in plugin["config_schema"]["properties"]
    assert "table_prefix" in plugin["config_schema"]["properties"]
    assert "SAGE_V2_POSTGRES_DSN" not in str(plugin)


def test_postgres_store_requires_explicit_dsn():
    with pytest.raises(TypeError):
        PostgresSessionStore()
    with pytest.raises(ValueError, match="plugin declaration"):
        PostgresSessionStore("   ")


@pytest.mark.asyncio
async def test_postgres_store_fails_closed_after_writer_lock_connection_loss():
    class ClosedConnection:
        @staticmethod
        def is_closed():
            return True

    state = _PostgresSessionState(
        "postgresql://unused/unused", schema="sage_v2_demo"
    )
    state._pool = object()
    state._lock_conn = ClosedConnection()

    with pytest.raises(SageV2Error) as exc_info:
        await state._ensure_ready()

    assert exc_info.value.info.code == "session_store.writer_lock_lost"


async def test_postgres_plugin_start_opens_schema_before_first_write():
    store = PostgresSessionStore("postgresql://unused/unused", schema="sage_v2_demo")
    called: list[str] = []

    async def fake_ready():
        called.append("ready")

    store._coordinator._ensure_ready = fake_ready
    produced = await store.start(None, None)
    assert called == ["ready"]
    assert produced["session.store"] is store


def test_postgres_capabilities_claim_single_process_without_connecting():
    store = PostgresSessionStore("postgresql://unused/unused", schema="sage_v2_demo")
    assert store.capabilities["durable_across_process_restart"] is True
    assert store.capabilities["multi_process_writes"] is False
    assert store.capabilities["cross_process_subscribe"] is False
    assert store.capabilities["global_session_index"] is False
    assert store.table_prefix == "sagent"
    assert store._table("sessions") == "sage_v2_demo.sagent_sessions"
    assert not hasattr(store, "list_sessions")
    with pytest.raises(ValueError, match="table_prefix"):
        PostgresSessionStore("postgresql://unused/unused", table_prefix="Bad-Prefix")


def test_filter_session_state_drops_only_one_tree():
    dump = {
        "session_format_version": "sage.session-aggregate/v2",
        "sessions": [
            {"session_id": "s1"},
            {"session_id": "s2"},
        ],
        "runs": [
            {"session_id": "s1", "run_id": "r1"},
            {"session_id": "s2", "run_id": "r2"},
        ],
        "run_events": {"r1": [{"run_sequence": 1}], "r2": [{"run_sequence": 1}]},
        "fork_base_events": {},
        "steer_inbox": {},
        "start_idempotency": [{"run_id": "r1"}, {"run_id": "r2"}],
        "command_results": [{"run_id": "r1"}, {"run_id": "r2"}],
        "checkpoints": [],
        "suspensions": [],
        "interactions": [],
        "interaction_resolutions": [],
        "session_commit_proposals": [{"session_id": "s1", "proposal_id": "p1"}],
        "session_commit_command_results": [
            {"target_id": "r1", "proposal": {"proposal_id": "p1"}},
            {"target_id": "r2", "proposal": {"proposal_id": "p2"}},
        ],
    }
    filtered = _PostgresSessionState._filter_session_state(dump, "s1")
    assert [row["session_id"] for row in filtered["sessions"]] == ["s2"]
    assert [row["run_id"] for row in filtered["runs"]] == ["r2"]
    assert set(filtered["run_events"]) == {"r2"}
    assert [row["run_id"] for row in filtered["command_results"]] == ["r2"]
    assert filtered["session_commit_proposals"] == []
    assert [row["target_id"] for row in filtered["session_commit_command_results"]] == [
        "r2"
    ]


@pytest.mark.asyncio
async def test_builder_rejects_postgres_plugin_without_dsn():
    plugin = builtin_extension_registry().get("sage.session.postgres")
    if not plugin.descriptor.availability.available:
        pytest.skip("sage.session.postgres is unavailable without asyncpg")
    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.postgres-missing-dsn",
        model="test-model",
        base_url="https://model.invalid/v1",
    )
    package = package.model_copy(
        update={
            "runtime": package.runtime.model_copy(
                update={
                    "capabilities": {
                        "session.store": CapabilitySelection(
                            plugin="sage.session.postgres",
                            config={},
                        )
                    }
                }
            )
        }
    )
    with pytest.raises(SageV2Error) as exc_info:
        await SAgentBuilder().with_model_provider(ScriptedModelProvider(())).build(
            package
        )
    assert exc_info.value.info.code == "extension.config_invalid"


@pytest.fixture
def postgres_dsn():
    dsn = os.environ.get("SAGE_V2_TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("set SAGE_V2_TEST_POSTGRES_DSN to run live PostgreSQL tests")
    return dsn


@pytest.mark.asyncio
async def test_restart_round_trip_and_idempotent_start(postgres_dsn):
    schema = _schema()
    first = PostgresSessionStore(postgres_dsn, schema=schema)
    created = await first.create_run(command(), CONTEXT)
    await first.put_derived_state(created.handle.session_id, "notes", "title", "hello")
    await first.close()

    second = PostgresSessionStore(postgres_dsn, schema=schema)
    run = await second.get_run(created.handle.run_id)
    session = await second.get_session(created.handle.session_id)
    events = await second.read_events(created.handle.run_id)
    duplicate = await second.create_run(command(), CONTEXT)
    derived = await second.get_derived_state(
        created.handle.session_id, "notes", "title"
    )

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
    assert derived == "hello"
    await second.close()


@pytest.mark.asyncio
async def test_get_run_does_not_refetch_an_already_loaded_session(postgres_dsn):
    schema = _schema()
    store = PostgresSessionStore(postgres_dsn, schema=schema)
    created = await store.create_run(command("loaded-once"), CONTEXT)
    fetches = 0
    original = store._fetch_session

    async def wrapped(session_id):
        nonlocal fetches
        fetches += 1
        return await original(session_id)

    store._fetch_session = wrapped
    first = await store.get_run(created.handle.run_id)
    second = await store.get_run(created.handle.run_id)
    assert first.run_id == second.run_id
    assert fetches == 0
    await store.close()


@pytest.mark.asyncio
async def test_run_events_are_appended_across_commits(postgres_dsn):
    schema = _schema()
    store = PostgresSessionStore(postgres_dsn, schema=schema)
    created = await store.create_run(command(), CONTEXT)
    await store.commit_run(
        run_id=created.handle.run_id,
        expected_revision=created.handle.run_revision,
        expected_states={RunState.QUEUED},
        new_state=RunState.RUNNING,
        drafts=(),
        context=CONTEXT,
        idempotency_key="start-execution",
    )
    await store.close()

    restored = PostgresSessionStore(postgres_dsn, schema=schema)
    run = await restored.get_run(created.handle.run_id)
    events = await restored.read_events(created.handle.run_id)
    assert run.state == RunState.RUNNING
    assert [event.type for event in events][:4] == [
        "run.accepted",
        "run.queued",
        "message.completed",
        "run.started",
    ]
    await restored.close()


@pytest.mark.asyncio
async def test_advisory_lock_rejects_a_second_writer(postgres_dsn):
    schema = _schema()
    first = PostgresSessionStore(postgres_dsn, schema=schema)
    await first.create_run(command(), CONTEXT)
    second = PostgresSessionStore(postgres_dsn, schema=schema)
    with pytest.raises(StoreInUseError) as exc_info:
        await second.create_run(command("other"), CONTEXT)
    assert exc_info.value.info.code == "session_store.in_use"
    await first.close()
    await second.close()


@pytest.mark.asyncio
async def test_failed_commit_does_not_leak_state_or_events(postgres_dsn):
    schema = _schema()
    store = PostgresSessionStore(postgres_dsn, schema=schema)
    created = await store.create_run(command(), CONTEXT)

    async def boom(*args, **kwargs):
        raise RuntimeError("injected storage failure")

    store._replace_locations = boom
    with pytest.raises(RuntimeError, match="injected storage failure"):
        await store.commit_run(
            run_id=created.handle.run_id,
            expected_revision=created.handle.run_revision,
            expected_states={RunState.QUEUED},
            new_state=RunState.RUNNING,
            drafts=(),
            context=CONTEXT,
            idempotency_key="start-execution",
        )

    run = await store.get_run(created.handle.run_id)
    events = await store.read_events(created.handle.run_id)
    assert run.state == RunState.QUEUED
    assert "run.started" not in [event.type for event in events]
    await store.close()

    restored = PostgresSessionStore(postgres_dsn, schema=schema)
    run = await restored.get_run(created.handle.run_id)
    events = await restored.read_events(created.handle.run_id)
    assert run.state == RunState.QUEUED
    assert "run.started" not in [event.type for event in events]
    await restored.close()


@pytest.mark.asyncio
async def test_parent_delete_cascades_to_child_sessions(postgres_dsn):
    schema = _schema()
    store = PostgresSessionStore(postgres_dsn, schema=schema)
    parent = await store.create_run(command("parent"), CONTEXT)
    await _cancel(store, parent, "cancel-parent")
    child = await store.create_run(
        command(
            "fork-child",
            session_id=parent.handle.session_id,
            mode=SessionConcurrencyMode.FORK,
        ),
        CONTEXT,
    )
    grandchild = await store.create_run(
        command(
            "fork-grandchild",
            session_id=child.handle.session_id,
            mode=SessionConcurrencyMode.FORK,
        ),
        CONTEXT,
    )
    await _cancel(store, child, "cancel-child")
    await _cancel(store, grandchild, "cancel-grandchild")

    descendants = await store.list_descendant_sessions(parent.handle.session_id)
    assert [value.session_id for value in descendants] == [
        child.handle.session_id,
        grandchild.handle.session_id,
    ]
    await store.delete_session(parent.handle.session_id)
    await store.close()

    restored = PostgresSessionStore(postgres_dsn, schema=schema)
    for deleted_session_id in (
        parent.handle.session_id,
        child.handle.session_id,
        grandchild.handle.session_id,
    ):
        with pytest.raises(SageV2Error) as missing:
            await restored.get_session(deleted_session_id)
        assert missing.value.info.code == "session.not_found"
    await restored.close()


@pytest.mark.asyncio
async def test_delete_session_removes_durable_rows(postgres_dsn):
    schema = _schema()
    store = PostgresSessionStore(postgres_dsn, schema=schema)
    created = await store.create_run(command(), CONTEXT)
    await _cancel(store, created, "cancel-run")
    session_id = created.handle.session_id
    await store.delete_session(session_id)
    with pytest.raises(SageV2Error) as exc_info:
        await store.get_session(session_id)
    assert exc_info.value.info.code == "session.not_found"
    await store.close()

    restored = PostgresSessionStore(postgres_dsn, schema=schema)
    with pytest.raises(SageV2Error) as exc_info:
        await restored.get_session(session_id)
    assert exc_info.value.info.code == "session.not_found"
    await restored.close()


@pytest.mark.asyncio
async def test_builder_can_select_postgres_session_store(postgres_dsn):
    schema = _schema()
    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.postgres-builder",
        model="test-model",
        base_url="https://model.invalid/v1",
    )
    package = package.model_copy(
        update={
            "runtime": package.runtime.model_copy(
                update={
                    "capabilities": {
                        "session.store": CapabilitySelection(
                            plugin="sage.session.postgres",
                            config={"dsn": postgres_dsn, "schema_name": schema},
                        )
                    }
                }
            )
        }
    )
    application = await (
        SAgentBuilder()
        .with_model_provider(ScriptedModelProvider(()))
        .build(package)
    )
    store = application.entrypoint().runtime.session_store
    assert store.schema_name == schema
    assert store.capabilities["durable_across_process_restart"] is True
    assert store.capabilities["multi_process_writes"] is False
    bindings = {
        (value.capability, value.plugin_id)
        for value in application.resolved_plan.providers
    }
    assert ("session.store", "sage.session.postgres") in bindings
    await application.close()

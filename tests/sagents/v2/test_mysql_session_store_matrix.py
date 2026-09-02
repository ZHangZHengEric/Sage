from __future__ import annotations

import os
import uuid
from pathlib import Path

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
from sagents.v2.contracts.run_state import RunState
from sagents.v2.package.presets import BuiltinPackageFactory
from sagents.v2.package.manifest.runtime import CapabilitySelection
from sagents.v2.runtime.extensions.official import builtin_extension_registry
from sagents.v2.runtime.session.plugins import mysql as mysql_plugin
from sagents.v2.runtime.session.plugins.mysql import (
    MysqlSessionStore,
    StoreInUseError,
    _MysqlSessionState,
    parse_mysql_dsn,
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


def _prefix() -> str:
    return f"sage_v2_{uuid.uuid4().hex[:12]}"


def command(key: str = "start_1") -> StartRun:
    return StartRun(
        agent_id="agent_test",
        input=(InputItem(role="user", content=(TextBlock(text="hello"),)),),
        resolved_spec_hash="sha256:spec",
        idempotency_key=key,
    )


def test_mysql_plugin_requires_dsn_in_declaration():
    inventory = {
        value["plugin_id"]: value for value in builtin_extension_registry().inventory()
    }
    plugin = inventory["sage.session.mysql"]
    assert plugin["capabilities"]["durable"] is True
    assert plugin["capabilities"]["global_session_index"] is False
    assert plugin["capabilities"]["multi_process_writes"] is False
    assert "dsn" in plugin["config_schema"]["required"]
    assert "dsn_env" not in plugin["config_schema"]["properties"]
    assert "table_prefix" in plugin["config_schema"]["properties"]
    store = MysqlSessionStore("mysql://root@127.0.0.1/sage")
    assert store.table_prefix == "sagent"
    assert store._table("sessions") == "`sagent_sessions`"
    bare = MysqlSessionStore("mysql://root@127.0.0.1/sage", table_prefix="")
    assert bare.table_prefix == ""
    assert bare._table("sessions") == "`sessions`"
    assert bare._constraint("run_events_session") == "run_events_session"


def test_mysql_store_requires_explicit_dsn():
    with pytest.raises(TypeError):
        MysqlSessionStore()
    with pytest.raises(ValueError, match="plugin declaration"):
        MysqlSessionStore("   ")
    with pytest.raises(ValueError, match="mysql://"):
        MysqlSessionStore("postgresql://unused/unused")
    with pytest.raises(ValueError, match="table_prefix"):
        MysqlSessionStore("mysql://root@127.0.0.1/sage", table_prefix="Bad-Prefix")


def test_parse_mysql_dsn_requires_database():
    parsed = parse_mysql_dsn("mysql://user:p%40ss@db.example:3307/sage_app")
    assert parsed["host"] == "db.example"
    assert parsed["port"] == 3307
    assert parsed["user"] == "user"
    assert parsed["password"] == "p@ss"
    assert parsed["db"] == "sage_app"
    with pytest.raises(ValueError, match="mysql://"):
        parse_mysql_dsn("mariadb://user@db.example/sage_app")


@pytest.mark.asyncio
async def test_mysql_store_fails_closed_after_writer_lock_connection_loss():
    class ClosedConnection:
        closed = True

    state = _MysqlSessionState("mysql://root@127.0.0.1/sage")
    state._pool = object()
    state._lock_conn = ClosedConnection()

    with pytest.raises(SageV2Error) as exc_info:
        await state._ensure_ready()

    assert exc_info.value.info.code == "session_store.writer_lock_lost"


class _FakeCursor:
    def __init__(self, existing: set[str]) -> None:
        self.existing = existing
        self.statements: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def execute(self, statement, params=None):
        del params
        self.statements.append(statement)

    async def fetchall(self):
        return [(name,) for name in sorted(self.existing)]


class _FakeConnection:
    def __init__(self, existing: set[str]) -> None:
        self.cursor_obj = _FakeCursor(existing)
        self.committed = False

    def cursor(self):
        return self.cursor_obj

    async def commit(self):
        self.committed = True


async def test_mysql_plugin_start_opens_schema_before_first_write():
    store = MysqlSessionStore("mysql://root@127.0.0.1/sage", table_prefix="")
    called: list[str] = []

    async def fake_ready():
        called.append("ready")

    store._coordinator._ensure_ready = fake_ready
    produced = await store.start(None, None)
    assert called == ["ready"]
    assert produced["session.store"] is store


async def test_bootstrap_skips_existing_tables():
    state = _MysqlSessionState("mysql://root@127.0.0.1/sage", table_prefix="")
    connection = _FakeConnection(
        {"sessions", "run_events", "locations", "start_idempotency", "derived_state"}
    )
    created = await state._bootstrap(connection)
    assert created == ()
    assert connection.committed is True
    creates = [
        statement
        for statement in connection.cursor_obj.statements
        if "CREATE TABLE" in statement
    ]
    assert creates == []


async def test_bootstrap_creates_missing_tables_only():
    state = _MysqlSessionState("mysql://root@127.0.0.1/sage", table_prefix="")
    connection = _FakeConnection({"sessions"})
    created = await state._bootstrap(connection)
    assert created == (
        "run_events",
        "locations",
        "start_idempotency",
        "derived_state",
    )
    creates = [
        statement
        for statement in connection.cursor_obj.statements
        if "CREATE TABLE" in statement
    ]
    assert len(creates) == 4
    assert all("IF NOT EXISTS" not in statement for statement in creates)


def test_mysql_upsert_uses_row_alias_instead_of_values_function():
    source = Path(mysql_plugin.__file__).read_text(encoding="utf-8")
    assert "AS incoming" in source
    assert "VALUES(parent_session_id)" not in source
    assert "VALUES(value)" not in source


def test_mysql_capabilities_claim_single_process_without_connecting():
    store = MysqlSessionStore("mysql://root@127.0.0.1/sage", table_prefix="sage_v2_demo")
    assert store.capabilities["durable_across_process_restart"] is True
    assert store.capabilities["multi_process_writes"] is False
    assert store.capabilities["cross_process_subscribe"] is False
    assert store.capabilities["global_session_index"] is False
    assert store.lock_name.startswith("sage_sess_mysql_")
    assert not hasattr(store, "list_sessions")


@pytest.mark.asyncio
async def test_builder_rejects_mysql_plugin_without_dsn():
    plugin = builtin_extension_registry().get("sage.session.mysql")
    if not plugin.descriptor.availability.available:
        pytest.skip("sage.session.mysql is unavailable without aiomysql")
    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.mysql-missing-dsn",
        model="test-model",
        base_url="https://model.invalid/v1",
    )
    package = package.model_copy(
        update={
            "runtime": package.runtime.model_copy(
                update={
                    "capabilities": {
                        "session.store": CapabilitySelection(
                            plugin="sage.session.mysql",
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
def mysql_dsn():
    dsn = os.environ.get("SAGE_V2_TEST_MYSQL_DSN", "").strip()
    if not dsn:
        pytest.skip("set SAGE_V2_TEST_MYSQL_DSN to run live MySQL tests")
    return dsn


@pytest.mark.asyncio
async def test_restart_round_trip_and_idempotent_start(mysql_dsn):
    prefix = _prefix()
    first = MysqlSessionStore(mysql_dsn, table_prefix=prefix)
    created = await first.create_run(command(), CONTEXT)
    await first.put_derived_state(created.handle.session_id, "notes", "title", "hello")
    await first.close()

    second = MysqlSessionStore(mysql_dsn, table_prefix=prefix)
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
async def test_run_events_are_appended_across_commits(mysql_dsn):
    prefix = _prefix()
    store = MysqlSessionStore(mysql_dsn, table_prefix=prefix)
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

    restored = MysqlSessionStore(mysql_dsn, table_prefix=prefix)
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
async def test_advisory_lock_rejects_a_second_writer(mysql_dsn):
    prefix = _prefix()
    first = MysqlSessionStore(mysql_dsn, table_prefix=prefix)
    await first.create_run(command(), CONTEXT)
    second = MysqlSessionStore(mysql_dsn, table_prefix=prefix)
    with pytest.raises(StoreInUseError) as exc_info:
        await second.create_run(command("other"), CONTEXT)
    assert exc_info.value.info.code == "session_store.in_use"
    await first.close()
    await second.close()


@pytest.mark.asyncio
async def test_delete_session_removes_durable_rows(mysql_dsn):
    prefix = _prefix()
    store = MysqlSessionStore(mysql_dsn, table_prefix=prefix)
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
    with pytest.raises(SageV2Error) as exc_info:
        await store.get_session(session_id)
    assert exc_info.value.info.code == "session.not_found"
    await store.close()

    restored = MysqlSessionStore(mysql_dsn, table_prefix=prefix)
    with pytest.raises(SageV2Error) as exc_info:
        await restored.get_session(session_id)
    assert exc_info.value.info.code == "session.not_found"
    await restored.close()


@pytest.mark.asyncio
async def test_builder_can_select_mysql_session_store(mysql_dsn):
    prefix = _prefix()
    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.mysql-builder",
        model="test-model",
        base_url="https://model.invalid/v1",
    )
    package = package.model_copy(
        update={
            "runtime": package.runtime.model_copy(
                update={
                    "capabilities": {
                        "session.store": CapabilitySelection(
                            plugin="sage.session.mysql",
                            config={"dsn": mysql_dsn, "table_prefix": prefix},
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
    assert store.table_prefix == prefix
    assert store.capabilities["durable_across_process_restart"] is True
    assert store.capabilities["multi_process_writes"] is False
    bindings = {
        (value.capability, value.plugin_id)
        for value in application.resolved_plan.providers
    }
    assert ("session.store", "sage.session.mysql") in bindings
    await application.close()

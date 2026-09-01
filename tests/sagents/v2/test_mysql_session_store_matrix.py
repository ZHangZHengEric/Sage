from __future__ import annotations

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
from sagents.v2.contracts.run_state import RunState
from sagents.v2.package.presets import BuiltinPackageFactory
from sagents.v2.package.manifest.runtime import CapabilitySelection
from sagents.v2.runtime.extensions.defaults import builtin_extension_registry
from sagents.v2.runtime.session.mysql import (
    MysqlSessionStore,
    StoreInUseError,
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
    pytest.skip("live MySQL tests require an explicit plugin dsn")


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
    store = application.service("session.store")
    assert store.table_prefix == prefix
    assert store.capabilities["durable_across_process_restart"] is True
    assert store.capabilities["multi_process_writes"] is False
    bindings = {
        (value.capability, value.plugin_id)
        for value in application.resolved_plan.providers
    }
    assert ("session.store", "sage.session.mysql") in bindings
    await application.close()

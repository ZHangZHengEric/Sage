"""PostgreSQL plugin configuration and live persistence contracts."""

import pytest

from tests.sagents.v2.test_sql_backend_feature_parity import (
    business_store_factory as business_store_factory,
)

from sagents.v2.runtime.extensions.official import builtin_extension_registry
from sagents.v2.runtime.session.plugins.postgres import (
    PostgresSessionStore,
    parse_postgres_dsn,
)


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://user:pass@localhost/sage?sslmode=require",
        "postgres://localhost/sage",
        "postgresql+psycopg://localhost/sage",
    ],
)
def test_postgres_dsn_preserves_connection_options(dsn):
    normalized = parse_postgres_dsn(dsn)
    assert normalized.startswith("postgresql://")
    assert normalized.endswith(dsn.split("/", 3)[-1])


@pytest.mark.parametrize(
    "dsn",
    [
        "",
        "mysql://localhost/sage",
        "postgresql://localhost",
        "postgresql://localhost/sage/extra",
        "postgresql://localhost:99999/sage",
    ],
)
def test_postgres_dsn_rejects_invalid_database_urls(dsn):
    with pytest.raises(ValueError):
        PostgresSessionStore(dsn)


def test_postgres_plugin_declares_honest_capabilities_and_limits():
    inventory = {
        row["plugin_id"]: row for row in builtin_extension_registry().inventory()
    }
    plugin = inventory["sage.session.postgres"]
    assert plugin["capabilities"]["durable"] is True
    assert plugin["capabilities"]["atomic_session_cas"] is True
    assert plugin["capabilities"]["multi_process_writes"] is False
    assert plugin["capabilities"]["cross_process_subscribe"] is False
    assert plugin["config_schema"]["required"] == ["dsn"]
    store = PostgresSessionStore("postgresql://localhost/sage")
    assert store._table("sessions") == '"sagent_sessions"'
    assert store.composition_identity()["plugin"] == "sage.session.postgres"
    with pytest.raises(ValueError, match="table_prefix"):
        PostgresSessionStore("postgresql://localhost/sage", table_prefix='bad"prefix')
    with pytest.raises(ValueError, match="max_connections"):
        PostgresSessionStore("postgresql://localhost/sage", max_connections=1)


@pytest.fixture
async def postgres_stores():
    import os
    from uuid import uuid4

    dsn = os.environ.get("SAGE_V2_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set SAGE_V2_TEST_POSTGRES_DSN to run live PostgreSQL tests")
    prefix = "pgtest_" + uuid4().hex[:12]
    stores = []

    def open_store(**kwargs):
        store = PostgresSessionStore(dsn, table_prefix=prefix, **kwargs)
        stores.append(store)
        return store

    try:
        yield open_store
    finally:
        cleanup = open_store()
        try:
            async with cleanup._writer_connection() as connection:
                for table in (
                    "attachments",
                    "derived_state",
                    "start_idempotency",
                    "locations",
                    "run_events",
                    "session_mutations",
                    "sessions",
                ):
                    await connection.execute(
                        f"DROP TABLE IF EXISTS {cleanup._table(table)}"
                    )
                await connection.commit()
        finally:
            for store in reversed(stores):
                await store.close()


async def test_postgres_cas_rejects_stale_writes_and_preserves_committed_head(
    postgres_stores,
):
    from sagents.v2.contracts.errors import SageV2Error
    from sagents.v2.contracts.run_state import RunState
    from tests.sagents.v2.test_sql_session_store_contract import command, CONTEXT

    first, second = postgres_stores(), postgres_stores()
    created = await first.create_run(command(), CONTEXT)
    await second.get_run(created.handle.run_id)
    await first.commit_run(
        run_id=created.handle.run_id,
        expected_revision=created.handle.run_revision,
        expected_states={RunState.QUEUED},
        new_state=RunState.RUNNING,
        drafts=(),
        context=CONTEXT,
        idempotency_key="first",
    )
    with pytest.raises(SageV2Error) as conflict:
        await second.commit_run(
            run_id=created.handle.run_id,
            expected_revision=created.handle.run_revision,
            expected_states={RunState.QUEUED},
            new_state=RunState.CANCELLED,
            drafts=(),
            context=CONTEXT,
            idempotency_key="stale",
        )
    assert conflict.value.info.code == "session.revision_conflict"
    assert (await second.get_run(created.handle.run_id)).state == RunState.RUNNING
    fresh = postgres_stores()
    assert (await fresh.get_run(created.handle.run_id)).state == RunState.RUNNING


async def test_postgres_snapshot_compaction_and_binary_attachments_survive_restart(
    postgres_stores,
):
    from tests.sagents.v2.test_session_attachments_matrix import (
        create,
        content,
        CONTEXT,
        cancel,
    )

    store = postgres_stores()
    store.snapshot_interval = 2
    created = await create(store, "binary")
    sid = created.handle.session_id
    value = bytes(range(256)) + b"\x00\xff" * 100
    reference = await store.put_attachment(
        sid,
        artifact_id="binary",
        media_type="application/octet-stream",
        content=content(value),
        context=CONTEXT,
    )
    await cancel(store, created)
    for index, data in enumerate(
        ["hello", "123", "null", None, 1, False, {"中文": ["text"]}]
    ):
        await store.put_derived_state(sid, "test", str(index), data)
    await store.close()
    reopened = postgres_stores()
    got, stream = await reopened.get_attachment(sid, "binary", context=CONTEXT)
    assert got == reference
    assert b"".join([chunk async for chunk in stream]) == value
    for index, data in enumerate(
        ["hello", "123", "null", None, 1, False, {"中文": ["text"]}]
    ):
        assert await reopened.get_derived_state(sid, "test", str(index)) == data
    await reopened.delete_derived_state(sid, "test", "0")
    assert await reopened.get_derived_state(sid, "test", "0") is None
    backup = await reopened.export_session_backup(sid, context=CONTEXT)
    assert backup
    await reopened.delete_session(sid)
    async with reopened._reader_connection() as connection:
        for table in (
            "sessions",
            "attachments",
            "derived_state",
            "locations",
            "run_events",
            "session_mutations",
            "start_idempotency",
        ):
            result = await connection.execute(
                f"SELECT count(*) FROM {reopened._table(table)}"
            )
            assert (await result.fetchone())[0] == 0
    restored = await reopened.restore_session_backup(backup, context=CONTEXT)
    assert restored.session_id == sid
    _, restored_stream = await reopened.get_attachment(sid, "binary", context=CONTEXT)
    assert b"".join([chunk async for chunk in restored_stream]) == value


async def test_postgres_read_views_metadata_history_and_workspace_probes_are_cold(
    postgres_stores,
):
    from unittest.mock import AsyncMock
    from tests.sagents.v2.test_managed_session_metadata import populate
    from tests.sagents.v2.test_mysql_session_store_matrix import CONTEXT
    from sagents.v2.contracts.errors import SageV2Error
    from sagents.v2.runtime.session.access import AuthorizedSessionAccess

    store = postgres_stores()
    _, parent, first, second, nested, flow = await populate(store)
    await store.close()
    cold = postgres_stores()
    cold._ensure_session_loaded = AsyncMock(
        side_effect=AssertionError("execution aggregate installed")
    )
    ids = [
        parent.session_id,
        first.session_id,
        second.session_id,
        nested.session_id,
        flow.session_id,
    ]
    views = await cold.read_session_views(
        ids, include_events=True, run_ids=[parent.run_id]
    )
    assert len(views) == 5
    assert views[parent.session_id].runs[0].events[0].type == "run.accepted"
    assert not views[first.session_id].runs
    page = await cold.authorized_run_metadata_page(ids, CONTEXT, limit=2)
    assert len(page) == 2
    last = page[-1]
    rest = await cold.authorized_run_metadata_page(
        ids, CONTEXT, after=(last.session_id, last.created_at.isoformat(), last.run_id)
    )
    assert rest
    rows, owners = await cold._run_metadata_batch(ids)
    assert len(rows) == 7 and set(owners) == set(ids)
    heads = await cold.managed_session_heads(parent.run_id)
    assert len(heads) == 3
    assert set(await cold.list_workspace_descendant_ids([parent.session_id])) == set(
        ids[1:]
    )
    assert await cold.has_nonterminal_session_trees([parent.session_id])
    assert not await cold.filter_suspended_session_ids(ids)
    history = await cold.read_authorized_session_page(
        parent.session_id, CONTEXT, after_sequence=None, limit=1
    )
    assert len(history.events) == 1
    assert (
        await cold.latest_authorized_session_command(parent.session_id, CONTEXT)
    ).agent_id == "agent_test"
    intruder = CONTEXT.model_copy(
        update={"actor": CONTEXT.actor.model_copy(update={"tenant_id": "other"})}
    )
    assert not await cold.authorized_run_metadata_page(ids, intruder)
    with pytest.raises(SageV2Error):
        await cold.read_authorized_session_page(
            parent.session_id, intruder, after_sequence=0, limit=1
        )
    assert not cold._sessions and not cold._runs
    assert await AuthorizedSessionAccess(cold).read_session_views(
        {parent.session_id: CONTEXT}
    )


async def test_postgres_concurrent_bootstrap_and_connection_reuse(postgres_stores):
    import asyncio

    first, second = postgres_stores(), postgres_stores()
    await asyncio.gather(first._ensure_ready(), second._ensure_ready())
    with pytest.raises(RuntimeError, match="abort read"):
        async with first._reader_connection() as connection:
            await connection.execute("SELECT 1")
            raise RuntimeError("abort read")
    async with first._reader_connection() as connection:
        assert (await (await connection.execute("SELECT 2")).fetchone())[0] == 2
    await first.close()
    from sagents.v2.contracts.errors import SageV2Error

    with pytest.raises(SageV2Error) as closed:
        await first._ensure_ready()
    assert closed.value.info.code == "session_store.closed"


@pytest.mark.parametrize("decision", ["approve_once", "deny"])
async def test_postgres_approval_checkpoint_resumes_after_restart(
    business_store_factory, decision
):
    from tests.sagents.v2.test_filesystem_session_store_matrix import (
        command,
        CONTEXT,
        completed,
        loop_for,
        WRITE_TOOL,
        handler,
    )
    from sagents.v2.runtime.kernel import HarnessRuntime
    from sagents.v2.testing.plugins.scripted_model import (
        ScriptedModelProvider,
        ScriptedModelStep,
    )
    from sagents.v2.model.contracts import ModelToolCall
    from sagents.v2.tool.plugins.ephemeral import InMemoryToolExecutor
    from sagents.v2.contracts.commands import ReplyInteraction
    from sagents.v2.contracts.run_state import RunState

    store = business_store_factory()
    runtime = HarnessRuntime(store)
    handle = await runtime.start_run(command(), CONTEXT)
    model = ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(
                    completed(
                        calls=(
                            ModelToolCall(
                                tool_call_id="call_1",
                                name="write_value",
                                arguments={"value": "1"},
                            ),
                        )
                    ),
                )
            ),
        )
    )
    executor = InMemoryToolExecutor(
        {"write_value": WRITE_TOOL}, {"write_value": handler}
    )
    suspended = await loop_for(runtime, model, executor).execute(handle.run_id, CONTEXT)
    assert suspended.state == RunState.SUSPENDED and not executor.calls
    await store.close()
    reopened = business_store_factory()
    if "redis-" in reopened.plugin_id:
        # Force the restored approval/checkpoint through the durable SQL archive
        # rather than retaining this Session's Redis cache across the restart.
        await reopened._redis.delete(reopened._session_key(handle.session_id))
    runtime = HarnessRuntime(reopened)
    run = await runtime.get_run(handle.run_id)
    suspension = await reopened.get_suspension(run.suspension_id)
    interaction = await reopened.get_interaction(suspension.interaction_id)
    checkpoint = await reopened.get_checkpoint(suspension.checkpoint_id)
    assert checkpoint.checkpoint_codec_version == "agent-loop/3"
    assert await reopened.filter_suspended_session_ids([handle.session_id]) == {
        handle.session_id
    }
    assert (
        await reopened.read_session_views([handle.session_id], suspended_only=True)
    )[handle.session_id].runs[0].suspension == suspension
    receipt = await runtime.reply_interaction(
        ReplyInteraction(
            run_id=handle.run_id,
            suspension_id=suspension.suspension_id,
            interaction_id=interaction.interaction_id,
            expected_revision=run.revision,
            expected_suspension_revision=suspension.expected_revision,
            expected_interaction_revision=interaction.expected_revision,
            decision=decision,
            idempotency_key="reply",
        ),
        CONTEXT,
    )
    assert receipt.decision.value == "accepted"
    executor = InMemoryToolExecutor(
        {"write_value": WRITE_TOOL}, {"write_value": handler}
    )
    model = ScriptedModelProvider((ScriptedModelStep(events=(completed("done"),)),))
    result = await loop_for(runtime, model, executor).resume(handle.run_id, CONTEXT)
    assert result.state == RunState.COMPLETED
    assert len(executor.calls) == (1 if decision == "approve_once" else 0)
    assert not await reopened.has_nonterminal_session_trees([handle.session_id])
    events = await reopened.read_events(handle.run_id)
    assert [event.run_sequence for event in events] == list(range(1, len(events) + 1))


async def test_postgres_failed_event_append_rolls_back_head_and_idempotency(
    postgres_stores,
):
    from unittest.mock import AsyncMock
    from tests.sagents.v2.test_sql_session_store_contract import command, CONTEXT
    from sagents.v2.contracts.run_state import RunState

    store = postgres_stores()
    created = await store.create_run(command(), CONTEXT)
    original = store._coordinator._persist_events
    store._persist_events = AsyncMock(side_effect=RuntimeError("event append failed"))
    with pytest.raises(RuntimeError, match="event append failed"):
        await store.commit_run(
            run_id=created.handle.run_id,
            expected_revision=created.handle.run_revision,
            expected_states={RunState.QUEUED},
            new_state=RunState.RUNNING,
            drafts=(),
            context=CONTEXT,
            idempotency_key="retry",
        )
    store._persist_events = original
    fresh = postgres_stores()
    assert (await fresh.get_run(created.handle.run_id)).state == RunState.QUEUED
    result = await store.commit_run(
        run_id=created.handle.run_id,
        expected_revision=created.handle.run_revision,
        expected_states={RunState.QUEUED},
        new_state=RunState.RUNNING,
        drafts=(),
        context=CONTEXT,
        idempotency_key="retry",
    )
    assert result.run.state == RunState.RUNNING


async def test_postgres_idle_eviction_preserves_derived_state_and_reload(
    postgres_stores,
):
    from tests.sagents.v2.test_session_attachments_matrix import create, cancel, CONTEXT

    store = postgres_stores(cache_idle_seconds=0, max_cached_sessions=1)
    created = await create(store, "idle")
    sid = created.handle.session_id
    await store.put_derived_state(sid, "test", "retained", {"value": "durable"})
    await cancel(store, created)
    assert sid not in store._sessions
    assert await store.get_derived_state(sid, "test", "retained") == {
        "value": "durable"
    }
    assert sid not in store._sessions
    await store.authorize_session_actor(sid, CONTEXT)


def test_postgres_dsn_normalizes_query_spaces_without_losing_options():
    from urllib.parse import parse_qs, urlsplit

    normalized = parse_postgres_dsn(
        "postgresql://localhost/sage?options=-csearch_path%3Dpublic+&connect_timeout=2&sslmode=require"
    )
    assert "+" not in urlsplit(normalized).query
    assert parse_qs(urlsplit(normalized).query) == {
        "options": ["-csearch_path=public "],
        "connect_timeout": ["2"],
        "sslmode": ["require"],
    }


async def test_postgres_workspace_cleanup_fails_closed_when_run_state_is_missing(
    postgres_stores,
):
    from tests.sagents.v2.test_sql_session_store_contract import command, CONTEXT
    from sagents.v2.contracts.errors import SageV2Error

    store = postgres_stores()
    created = await store.create_run(command(), CONTEXT)
    sid = created.handle.session_id
    async with store._writer_connection() as connection:
        await connection.execute(
            f"UPDATE {store._table('sessions')} SET compact_state = jsonb_set(compact_state, '{{runs}}', '[]'::jsonb) WHERE session_id = %s",
            (sid,),
        )
        await connection.commit()
    with pytest.raises(SageV2Error) as caught:
        await store.has_nonterminal_session_trees([sid])
    assert caught.value.info.code == "session_store.workspace_state_missing"

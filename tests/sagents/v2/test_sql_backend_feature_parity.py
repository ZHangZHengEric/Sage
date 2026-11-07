"""PostgreSQL must expose the same business storage modes as MySQL."""

import pytest

from sagents.v2.runtime.extensions.official import builtin_extension_registry
from sagents.v2.runtime.session.plugins.postgres.redis import RedisPostgresSessionStore
from sagents.v2.runtime.session.plugins.mysql.redis import RedisMysqlSessionStore


def test_sql_backends_publish_the_same_distributed_capabilities():
    inventory = {
        row["plugin_id"]: row for row in builtin_extension_registry().inventory()
    }
    for left, right in [
        ("sage.session.mysql", "sage.session.postgres"),
        ("sage.session.redis-mysql", "sage.session.redis-postgres"),
    ]:
        assert inventory[left]["capabilities"] == inventory[right]["capabilities"]
        assert inventory[left]["config_schema"] == inventory[right]["config_schema"]


@pytest.mark.parametrize(
    "store_type,dsn",
    [
        (RedisMysqlSessionStore, "mysql://user@localhost/sage"),
        (RedisPostgresSessionStore, "postgresql://user@localhost/sage"),
    ],
)
async def test_distributed_store_configures_archive_and_namespace(store_type, dsn):
    store = store_type(dsn, redis_url="redis://localhost/0", max_connections=3)
    try:
        assert store.capabilities["multi_process_writes"]
        assert store.capabilities["cross_process_subscribe"]
        assert store.capabilities["atomic_worker_fence"]
        assert store._archive._connection_budget.max_connections == 3
        assert store.key_prefix.startswith("sage:session:{")
        assert store.composition_identity()["plugin"] == store_type.plugin_id
    finally:
        await store.close()


@pytest.fixture(params=["mysql", "postgres", "redis-mysql", "redis-postgres"])
async def business_store_factory(request):
    from tests.sagents.v2.sql_storage_fixture import sql_store_factory

    async with sql_store_factory(request.param) as factory:
        yield factory


async def test_snapshot_publication_and_rejection_survive_reopen(
    business_store_factory,
):
    from tests.sagents.v2.test_filesystem_session_store_matrix import (
        command,
        CONTEXT,
        completed,
    )
    from sagents.v2.runtime.kernel import HarnessRuntime
    from sagents.v2.agent.engine import AgentLoopEngine
    from sagents.v2.testing.plugins.scripted_model import (
        ScriptedModelProvider,
        ScriptedModelStep,
    )
    from sagents.v2.tool.plugins.ephemeral import (
        InMemoryToolCatalog,
        InMemoryToolExecutor,
    )
    from sagents.v2.contracts.run_state import SessionConcurrencyMode
    from sagents.v2.contracts.session_commit import (
        ProposeSessionCommit,
        PublishSessionCommit,
        RejectSessionCommit,
        SessionCommitProposalStatus,
    )

    store = business_store_factory()
    runtime = HarnessRuntime(store)

    async def propose(key):
        handle = await runtime.start_run(
            command(key, mode=SessionConcurrencyMode.SNAPSHOT_ISOLATED), CONTEXT
        )
        run = await AgentLoopEngine(
            runtime=runtime,
            model=ScriptedModelProvider(
                (ScriptedModelStep(events=(completed("candidate"),)),)
            ),
            tool_catalog=InMemoryToolCatalog(()),
            tool_executor=InMemoryToolExecutor({}, {}),
        ).execute(handle.run_id, CONTEXT)
        request = ProposeSessionCommit(
            run_id=handle.run_id,
            expected_run_revision=run.revision,
            idempotency_key="propose-" + key,
        )
        proposal = await runtime.propose_session_commit(request, CONTEXT)
        assert await runtime.propose_session_commit(request, CONTEXT) == proposal
        return handle, proposal

    handle, proposal = await propose("publish")
    _, rejected_proposal = await propose("reject")
    session = await store.get_session(handle.session_id)
    publish = PublishSessionCommit(
        proposal_id=proposal.proposal_id,
        expected_proposal_revision=proposal.revision,
        expected_session_revision=session.revision,
        idempotency_key="publish",
    )
    await store.close()
    reopened = business_store_factory()
    published = await reopened.publish_session_commit(publish, CONTEXT)
    assert published.status == SessionCommitProposalStatus.PUBLISHED
    assert await reopened.publish_session_commit(publish, CONTEXT) == published
    reject_session = await reopened.get_session(rejected_proposal.session_id)
    rejection = RejectSessionCommit(
        proposal_id=rejected_proposal.proposal_id,
        expected_proposal_revision=rejected_proposal.revision,
        expected_session_revision=reject_session.revision,
        idempotency_key="reject",
        reason="business decision",
    )
    rejected = await reopened.reject_session_commit(rejection, CONTEXT)
    assert rejected.status == SessionCommitProposalStatus.REJECTED
    await reopened.close()
    cold = business_store_factory()
    assert await cold.get_session_commit_proposal(proposal.proposal_id) == published
    assert await cold.reject_session_commit(rejection, CONTEXT) == rejected


async def test_steering_claim_cursor_survives_reopen(business_store_factory):
    from tests.sagents.v2.test_filesystem_session_store_matrix import command, CONTEXT
    from sagents.v2.runtime.kernel import HarnessRuntime
    from sagents.v2.contracts.commands import SteerRun, InputItem
    from sagents.v2.contracts.items import TextBlock
    from sagents.v2.contracts.events import TurnEventData
    from sagents.v2.runtime.session.contracts import EventDraft
    from sagents.v2.contracts.run_state import RunState

    store = business_store_factory()
    runtime = HarnessRuntime(store)
    handle = await runtime.start_run(command(), CONTEXT)
    running = await runtime.start_execution(
        run_id=handle.run_id,
        expected_revision=handle.run_revision,
        context=CONTEXT,
        idempotency_key="execute",
    )
    current = (
        await store.commit_run(
            run_id=handle.run_id,
            expected_revision=running.revision,
            expected_states={RunState.RUNNING},
            new_state=RunState.RUNNING,
            drafts=(
                EventDraft(
                    type="turn.started",
                    turn_id="turn_1",
                    data=TurnEventData(state="started"),
                ),
            ),
            context=CONTEXT,
            idempotency_key="turn",
        )
    ).run
    receipt = await runtime.steer_run(
        SteerRun(
            run_id=handle.run_id,
            expected_revision=current.revision,
            expected_turn_id="turn_1",
            input=(InputItem(role="user", content=(TextBlock(text="new input"),)),),
            idempotency_key="steer",
        ),
        CONTEXT,
    )
    assert receipt.decision.value == "accepted"
    await store.close()
    reopened = business_store_factory()
    run = await reopened.get_run(handle.run_id)
    claimed = await reopened.claim_steers(
        run_id=run.run_id,
        expected_revision=run.revision,
        turn_id="turn_1",
        context=CONTEXT,
    )
    assert claimed.entries[0].input[0].content[0].text == "new input"
    await reopened.close()
    cold = business_store_factory()
    run = await cold.get_run(handle.run_id)
    again = await cold.claim_steers(
        run_id=run.run_id,
        expected_revision=run.revision,
        turn_id="turn_1",
        context=CONTEXT,
    )
    assert not again.entries


async def test_fork_copies_attachments_and_tree_backup_delete_restore(
    business_store_factory,
):
    from tests.sagents.v2.test_session_attachments_matrix import (
        create,
        cancel,
        content,
        CONTEXT,
    )
    from sagents.v2.contracts.run_state import SessionConcurrencyMode
    from sagents.v2.contracts.errors import SageV2Error

    store = business_store_factory()
    parent = await create(store, "parent")
    sid = parent.handle.session_id
    await store.put_attachment(
        sid,
        artifact_id="image",
        media_type="image/png",
        content=content(b"\x00\xff"),
        context=CONTEXT,
    )
    await cancel(store, parent)
    child = await create(
        store, "fork", session_id=sid, mode=SessionConcurrencyMode.FORK
    )
    child_sid = child.handle.session_id
    await cancel(store, child)
    assert (await store.get_session(child_sid)).parent_session_id == sid
    assert await store.list_direct_child_session_ids(sid) == [child_sid]
    assert set(await store.list_workspace_descendant_ids([sid])) == {child_sid}
    assert not await store.has_nonterminal_sessions([sid, child_sid])
    _, chunks = await store.get_attachment(child_sid, "image", context=CONTEXT)
    assert b"".join([part async for part in chunks]) == b"\x00\xff"
    backup = await store.export_session_backup(sid, context=CONTEXT)
    await store.close()
    reopened = business_store_factory()
    await reopened.delete_session(sid)
    for deleted in (sid, child_sid):
        with pytest.raises(SageV2Error):
            await reopened.get_session(deleted)
    intruder = CONTEXT.model_copy(
        update={"actor": CONTEXT.actor.model_copy(update={"tenant_id": "other"})}
    )
    with pytest.raises(SageV2Error):
        await reopened.restore_session_backup(backup, context=intruder)
    await reopened.restore_session_backup(backup, context=CONTEXT)
    await reopened.close()
    cold = business_store_factory()
    assert (await cold.get_session(child_sid)).parent_session_id == sid
    _, restored = await cold.get_attachment(child_sid, "image", context=CONTEXT)
    assert b"".join([part async for part in restored]) == b"\x00\xff"


async def test_execution_resource_and_idempotent_commit_survive_reopen(
    business_store_factory,
):
    from tests.sagents.v2.test_filesystem_session_store_matrix import command, CONTEXT
    from sagents.v2.runtime.execution.resources import (
        ExecutionResourceRecord,
        ExecutionResourceState,
    )
    from sagents.v2.runtime.execution.sandbox import (
        ResolvedSandboxSpec,
        ResourceLimits,
        FileSystemPolicy,
        FileOperation,
        SandboxRef,
    )
    from sagents.v2.contracts.common import utc_now

    store = business_store_factory()
    created = await store.create_run(command("resource"), CONTEXT)
    rid = created.handle.run_id
    spec = ResolvedSandboxSpec(
        resources=ResourceLimits(require_hard_limits=False),
        spec_hash="sha256:sandbox",
        architecture="native",
        filesystem=FileSystemPolicy(allowed_operations=frozenset(FileOperation)),
        policy_hash="sha256:policy",
    )
    resource = ExecutionResourceRecord(
        run_id=rid,
        generation=1,
        sandbox_ref=SandboxRef(
            sandbox_id="sandbox_1",
            provider_id="sandbox.test",
            provider_version="1",
            tenant_id=CONTEXT.actor.tenant_id,
            owner_run_id=rid,
            spec_hash=spec.spec_hash,
            policy_hash=spec.policy_hash,
        ),
        sandbox_spec=spec,
        run_resolved_spec_hash="sha256:agent",
        state=ExecutionResourceState.ACTIVE,
        updated_at=utc_now(),
    )
    options = dict(
        record=resource,
        expected_run_revision=created.handle.run_revision,
        expected_resource_revision=None,
        event_type="sandbox.ready",
        context=CONTEXT,
        idempotency_key="resource-ready",
    )
    committed = await store.commit_execution_resource(**options)
    await store.close()
    cold = business_store_factory()
    assert await cold.get_execution_resource(rid) == committed
    assert await cold.commit_execution_resource(**options) == committed
    assert any(row.run_id == rid for row in await cold.list_execution_resources())


def test_postgres_exposes_every_mysql_public_business_method():
    from sagents.v2.runtime.session.plugins.mysql.state import _MysqlSessionState
    from sagents.v2.runtime.session.plugins.postgres.state import _PostgresSessionState
    from sagents.v2.runtime.session.plugins.mysql.redis import _RedisMysqlSessionState
    from sagents.v2.runtime.session.plugins.postgres.redis import (
        _RedisPostgresSessionState,
    )

    for mysql, postgres in [
        (_MysqlSessionState, _PostgresSessionState),
        (_RedisMysqlSessionState, _RedisPostgresSessionState),
    ]:
        methods = {
            name
            for name in dir(mysql)
            if not name.startswith("_") and callable(getattr(mysql, name))
        }
        missing = {
            name for name in methods if not callable(getattr(postgres, name, None))
        }
        assert not missing


async def test_backup_restore_cannot_overwrite_a_reused_start_key(
    business_store_factory,
):
    from tests.sagents.v2.test_session_attachments_matrix import create, cancel, CONTEXT
    from sagents.v2.contracts.errors import SageV2Error

    store = business_store_factory()
    first = await create(store, "reused-key")
    await cancel(store, first)
    backup = await store.export_session_backup(first.handle.session_id, context=CONTEXT)
    await store.delete_session(first.handle.session_id)
    second = await create(store, "reused-key")
    assert second.handle.session_id != first.handle.session_id
    await store.close()
    reopened = business_store_factory()
    with pytest.raises(SageV2Error):
        await reopened.restore_session_backup(backup, context=CONTEXT)
    duplicate = await create(reopened, "reused-key")
    assert duplicate.duplicate and duplicate.handle.run_id == second.handle.run_id

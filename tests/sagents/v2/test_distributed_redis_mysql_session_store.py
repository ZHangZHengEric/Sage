"""Multi-instance contracts at the Redis/MySQL external-client boundary.

These cases protect the unified Redis/MySQL plugin: fresh reads, shared admission, durable event
delivery, and authoritative deletion when two coordinators share storage.
"""

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from sagents.v2.sagent import RecoveryAgent

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import timedelta
from unittest.mock import AsyncMock

import fakeredis
import fakeredis.aioredis
import pytest
import pytest_asyncio

from sagents.v2.contracts.commands import InputItem, StartRun
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.events import ItemEventData, RunEventData
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import (
    ActorRef,
    PrincipalType,
    RequestContext,
    TraceContext,
)
from sagents.v2.contracts.run_state import EventCursor, RunState
from sagents.v2.runtime.distributed.redis_coordination import (
    RedisMutationFence,
    active_worker_fence,
)
from sagents.v2.runtime.session.contracts import EventDraft
from sagents.v2.runtime.session.plugins.mysql.redis import RedisMysqlSessionStore


CONTEXT = RequestContext(
    actor=ActorRef(principal_id="user", principal_type=PrincipalType.USER, tenant_id="tenant"),
    trace=TraceContext(correlation_id="distributed-store-test"),
)


def command(key="start", *, session_id=None, text="hello"):
    return StartRun(
        agent_id="agent",
        input=(InputItem(role="user", content=(TextBlock(text=text),)),),
        resolved_spec_hash="sha256:spec",
        idempotency_key=key,
        session_id=session_id,
    )


class Archive:
    """MySQL boundary with the same monotonic archive semantics as production."""

    def __init__(self):
        self.states = {}
        self._session_guards = {}

    @asynccontextmanager
    async def session_guard(self, session_id):
        lock = self._session_guards.setdefault(session_id, asyncio.Lock())
        async with lock:
            yield

    async def _fetch_session(self, session_id):
        return deepcopy(self.states.get(session_id))

    async def _fetch_sessions(self, session_ids):
        return {sid: deepcopy(self.states[sid]) for sid in session_ids if sid in self.states}

    async def read_session_views(self, session_ids, **options):
        from sagents.v2.runtime.session.read_views import views_from_payload

        result = {}
        for sid in session_ids:
            if sid in self.states:
                result.update(views_from_payload(self.states[sid], **options))
        return result

    async def _run_metadata_batch(self, session_ids):
        from sagents.v2.runtime.session.run_metadata import metadata_from_payload

        result, owners = [], {}
        for sid in session_ids:
            if sid in self.states:
                rows, heads = metadata_from_payload(self.states[sid])
                result.extend(rows)
                owners.update(heads)
        return tuple(result), owners

    async def revision(self, session_id):
        state = self.states.get(session_id)
        return None if state is None else state["sessions"][0]["revision"]

    async def revisions(self, session_ids):
        return {sid: self.states[sid]["sessions"][0]["revision"]
                for sid in session_ids if sid in self.states}

    async def archive_session(self, payload, attachments):
        sid = payload["sessions"][0]["session_id"]
        previous = self.states.get(sid)
        if previous is None or previous["sessions"][0]["revision"] < payload["sessions"][0]["revision"]:
            self.states[sid] = deepcopy(payload)

    async def archive_batch(self, sid, mutations):
        from sagents.v2.runtime.session.plugins.mysql.state import _MysqlSessionState
        import json

        rows = [(revision, encoded) for revision, encoded in mutations
                if revision > self.states[sid]["sessions"][0]["revision"]]
        if rows:
            sequence = json.loads(rows[-1][1])["upserts"]["sessions"][0]["last_sequence"]
            self.states[sid] = _MysqlSessionState._replay_mutations(
                self.states[sid], rows, rows[-1][0], sequence)

    async def archive_attachments(self, sid, attachments):
        assert not attachments

    async def _read_start_lookup(self, command, context):
        return None

    async def _locate_session(self, kind, identity):
        return next((sid for sid, state in self.states.items()
                     if any(row.get(kind) == identity for row in state["runs"])), None)

    async def _list_descendant_ids(self, session_id):
        return []

    async def delete_archived_sessions(self, session_ids):
        for sid in session_ids:
            self.states.pop(sid, None)

    async def close(self):
        pass


@pytest_asyncio.fixture(params=[("mysql", "fake"), ("postgres", "fake"), ("mysql", "live"), ("postgres", "live")])
async def stores(request):
    import os
    from uuid import uuid4
    backend, transport = request.param
    if transport == "live":
        redis_url = os.environ.get("SAGE_V2_TEST_REDIS_URL")
        dsn = os.environ.get("SAGE_V2_TEST_" + backend.upper() + "_DSN")
        if not redis_url or not dsn:
            pytest.skip("set Redis and SQL DSNs for live distributed contracts")
        from redis.asyncio import Redis
        prefix = "distributed_" + uuid4().hex[:12]
        key_prefix = "sage:test:{" + prefix + "}"
    else:
        redis_url = "redis://unused/0"
        dsn = "postgresql://unused/test" if backend == "postgres" else "mysql://unused/test"
        prefix = key_prefix = None
    server = fakeredis.FakeServer()
    archive = Archive()
    values = []
    for _ in range(2):
        if transport == "live":
            redis = Redis.from_url(redis_url, decode_responses=True)
        else:
            redis = fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)
            redis.info = AsyncMock(return_value={"maxmemory_policy": "noeviction", "aof_enabled": 1})
        if backend == "postgres":
            from sagents.v2.runtime.session.plugins.postgres.redis import RedisPostgresSessionStore
            factory = RedisPostgresSessionStore
        else:
            factory = RedisMysqlSessionStore
        value = factory(dsn, redis_url=redis_url, archive_interval_seconds=3600,
                        table_prefix=prefix, key_prefix=key_prefix)
        value._redis = redis
        if transport == "fake":
            value._archive = archive
        async def idle():
            await asyncio.Event().wait()
        value._archive_loop = idle
        values.append(value)
    try:
        yield tuple(values)
    finally:
        for value in values:
            await value.close()
        if transport == "live":
            monitor = Redis.from_url(redis_url, decode_responses=True)
            keys = [key async for key in monitor.scan_iter(match=key_prefix + ":*")]
            if keys:
                await monitor.delete(*keys)
            await monitor.aclose()
            cleanup = type(values[0]._archive)(dsn, table_prefix=prefix)
            try:
                async with cleanup._writer_connection() as connection:
                    async with connection.cursor() as cursor:
                        for name in ("attachments", "derived_state", "start_idempotency", "locations", "run_events", "session_mutations", "sessions"):
                            await cursor.execute(f"DROP TABLE IF EXISTS {cleanup._table(name)}")
                    await connection.commit()
            finally:
                await cleanup.close()


async def transition(store, run_id, state, key):
    run = await store.get_run(run_id)
    return await store.commit_run(
        run_id=run_id,
        expected_revision=run.revision,
        expected_states={run.state},
        new_state=state,
        drafts=(EventDraft(
            type={RunState.RUNNING: "run.started", RunState.CANCELLED: "run.cancelled"}[state],
            data=RunEventData(state=state.value),
        ),),
        context=CONTEXT,
        idempotency_key=key,
    )


@pytest.mark.asyncio
async def test_two_instances_start_and_write_the_same_namespace(stores):
    first, second = stores
    assert first.key_prefix == second.key_prefix
    await asyncio.wait_for(asyncio.gather(first.start(None, {}), second.start(None, {})), 2)
    created = await asyncio.gather(
        first.create_run(command("first"), CONTEXT),
        second.create_run(command("second"), CONTEXT),
    )
    assert created[0].handle.run_id != created[1].handle.run_id
    assert (await second.get_run(created[0].handle.run_id)).state == RunState.QUEUED
    assert (await first.get_run(created[1].handle.run_id)).state == RunState.QUEUED


@pytest.mark.asyncio
async def test_cached_run_and_session_refresh_after_another_instance_commits(stores):
    first, second = stores
    created = await first.create_run(command(), CONTEXT)
    sid, rid = created.handle.session_id, created.handle.run_id
    initial = await first.get_session(sid)
    assert (await second.get_run(rid)).state == RunState.QUEUED
    await transition(second, rid, RunState.RUNNING, "running")
    assert (await first.get_run(rid)).state == RunState.RUNNING
    assert (await first.get_session(sid)).revision > initial.revision
    await transition(first, rid, RunState.CANCELLED, "cancel")
    assert (await second.get_run(rid)).state == RunState.CANCELLED


@pytest.mark.asyncio
async def test_concurrent_start_deduplicates_before_generating_a_new_session(stores):
    first, second = stores
    created = await asyncio.gather(
        first.create_run(command(), CONTEXT), second.create_run(command(), CONTEXT))
    assert created[0].handle.run_id == created[1].handle.run_id
    assert created[0].handle.session_id == created[1].handle.session_id
    assert sorted(value.duplicate for value in created) == [False, True]
    runs = await second.list_session_runs(created[0].handle.session_id)
    assert [run.run_id for run in runs] == [created[0].handle.run_id]
    with pytest.raises(SageV2Error) as conflict:
        await second.create_run(command(text="different request"), CONTEXT)
    assert conflict.value.info.code == "idempotency.conflict"
    assert [run.run_id for run in await first.list_session_runs(created[0].handle.session_id)] == [created[0].handle.run_id]


@pytest.mark.asyncio
async def test_subscription_replays_durable_events_from_another_instance(stores):
    first, second = stores
    created = await first.create_run(command(), CONTEXT)
    rid = created.handle.run_id
    before = await second.get_run(rid)
    result = await transition(first, rid, RunState.RUNNING, "running")
    stream = second.subscribe_events(EventCursor(run_id=rid, run_sequence=before.last_run_sequence))
    try:
        event = await asyncio.wait_for(anext(stream), 2)
    finally:
        await stream.aclose()
    assert event == result.events[0]
    assert event.run_sequence > before.last_run_sequence
    assert event in await second.read_events(rid)


@pytest.mark.asyncio
async def test_waiting_subscription_delivers_another_instances_next_commit(stores):
    first, second = stores
    created = await first.create_run(command(), CONTEXT)
    rid = created.handle.run_id
    before = await second.get_run(rid)
    observed_empty_read = asyncio.Event()
    original = second.read_events

    async def observed_read(*args, **kwargs):
        events = await original(*args, **kwargs)
        if not events:
            observed_empty_read.set()
        return events

    second.read_events = observed_read
    stream = second.subscribe_events(EventCursor(run_id=rid, run_sequence=before.last_run_sequence))
    pending = asyncio.create_task(anext(stream))
    try:
        await asyncio.wait_for(observed_empty_read.wait(), 2)
        result = await transition(first, rid, RunState.RUNNING, "running-live")
        event = await asyncio.wait_for(pending, 2)
        assert event == result.events[0]
        assert event in await original(rid)
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        await stream.aclose()
        second.read_events = original


async def publish_preview(store, run_id, text):
    run = await store.get_run(run_id)
    return await store.publish_stream_preview(
        run_id=run_id, expected_revision=run.revision,
        drafts=(EventDraft(type="message.delta", item_id="assistant-message",
                           data=ItemEventData(operation="delta", delta=text)),),
        context=CONTEXT,
    )


@pytest.mark.asyncio
async def test_preview_sequences_are_shared_between_writers_without_advancing_canonical_cursor(stores):
    first, second = stores
    created = await first.create_run(command(), CONTEXT)
    rid = created.handle.run_id
    await transition(first, rid, RunState.RUNNING, "running")
    before = await second.get_run(rid)
    await publish_preview(first, rid, "first")
    assert [event.data.delta for event in await second.read_stream_previews(rid)] == ["first"]
    await publish_preview(second, rid, "second")
    for store in stores:
        previews = await store.read_stream_previews(rid)
        assert [event.data.delta for event in previews] == ["first", "second"]
        assert [event.preview_sequence for event in previews] == [1, 2]
        assert len({event.preview_epoch for event in previews}) == 1
        assert all(event.run_sequence == before.last_run_sequence for event in previews)
        assert (await store.get_run(rid)).last_run_sequence == before.last_run_sequence
    assert [event.preview_sequence for event in await first.read_stream_previews(
        rid, after_preview_sequence=1)] == [2]


@pytest.mark.asyncio
async def test_waiting_subscription_delivers_cross_instance_preview_after_its_preview_cursor(stores):
    first, second = stores
    created = await first.create_run(command(), CONTEXT)
    rid = created.handle.run_id
    await transition(first, rid, RunState.RUNNING, "running")
    await publish_preview(first, rid, "seen")
    before = await second.get_run(rid)
    seen, = await second.read_stream_previews(rid)
    observed_empty_read = asyncio.Event()
    original = second._read_preview_page

    async def observed_read(*args, **kwargs):
        page = await original(*args, **kwargs)
        if not page[1]:
            observed_empty_read.set()
        return page

    second._read_preview_page = observed_read
    stream = second.subscribe_events(EventCursor(
        run_id=rid, run_sequence=before.last_run_sequence,
        preview_sequence=seen.preview_sequence, preview_epoch=seen.preview_epoch))
    pending = asyncio.create_task(anext(stream))
    try:
        await asyncio.wait_for(observed_empty_read.wait(), 2)
        await publish_preview(first, rid, "new")
        event = await asyncio.wait_for(pending, 2)
        assert event.type == "message.delta"
        assert event.data.delta == "new"
        assert event.preview_sequence == seen.preview_sequence + 1
        assert event.preview_epoch == seen.preview_epoch
        assert event.run_sequence == before.last_run_sequence
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        await stream.aclose()
        second._read_preview_page = original


@pytest.mark.asyncio
async def test_old_preview_epoch_without_retained_preview_emits_an_explicit_gap(stores):
    first, second = stores
    created = await first.create_run(command(), CONTEXT)
    rid = created.handle.run_id
    before = await second.get_run(rid)
    stream = second.subscribe_events(EventCursor(
        run_id=rid, run_sequence=before.last_run_sequence,
        preview_sequence=10, preview_epoch="previous-process-epoch"))
    try:
        gap = await asyncio.wait_for(anext(stream), 2)
    finally:
        await stream.aclose()
    assert gap.type == "stream.gap"
    assert gap.data.state == "preview_epoch_changed"
    assert gap.data.from_sequence == 10
    assert gap.preview_epoch != "previous-process-epoch"
    assert gap.run_sequence == before.last_run_sequence


@pytest.mark.asyncio
@pytest.mark.parametrize("lose_fence", ["replace", "delete"])
async def test_worker_fence_loss_between_validation_and_exec_rejects_the_commit(stores, lose_fence):
    first, second = stores
    created = await first.create_run(command(), CONTEXT)
    rid, sid = created.handle.run_id, created.handle.session_id
    before = await first.get_run(rid)
    before_events = await first.read_events(rid)
    before_redis = await first._redis.hgetall(first._session_key(sid))
    fence = RedisMutationFence(first.redis_url, first._key("test-worker-fence"), "old-worker")
    await first._redis.set(fence.key, fence.token)
    original_pipeline = first._redis.pipeline
    injected = False

    def racing_pipeline(*args, **kwargs):
        pipe = original_pipeline(*args, **kwargs)
        original_execute = pipe.execute

        async def execute(*args, **kwargs):
            nonlocal injected
            writes_session = any(
                str(command[0]).upper() == "HSET" and command[1] == first._session_key(sid)
                for command, _ in pipe.command_stack
            )
            if writes_session and not injected:
                injected = True
                if lose_fence == "replace":
                    await second._redis.set(fence.key, "new-worker")
                else:
                    await second._redis.delete(fence.key)
            return await original_execute(*args, **kwargs)

        pipe.execute = execute
        return pipe

    first._redis.pipeline = racing_pipeline
    token = active_worker_fence.set(fence)
    try:
        with pytest.raises(SageV2Error) as rejected:
            await transition(first, rid, RunState.RUNNING, "stale-write")
        assert rejected.value.info.code == "scheduler.fence_rejected"
        assert injected, "the worker fence must be lost after WATCH and before EXEC"
    finally:
        active_worker_fence.reset(token)
        first._redis.pipeline = original_pipeline
    assert await second.get_run(rid) == before
    assert await second.read_events(rid) == before_events
    assert await second._redis.hgetall(second._session_key(sid)) == before_redis


@pytest.mark.asyncio
async def test_expired_scheduler_owner_cannot_dispatch_a_session_mutation(stores):
    from sagents.v2.contracts.common import utc_now
    from sagents.v2.runtime.execution.scheduler.contracts import WorkItem
    from sagents.v2.runtime.execution.scheduler.plugins.redis_distributed import RedisDistributedScheduler

    first, second = stores
    created = await first.create_run(command(), CONTEXT)
    rid = created.handle.run_id
    before = await first.get_run(rid)
    schedulers = []
    for store in (first, second):
        scheduler = RedisDistributedScheduler(redis_url=store.redis_url, key_prefix=store.key_prefix + ":scheduler-fence-test")
        scheduler._redis = store._redis
        schedulers.append(scheduler)
    try:
        await schedulers[0].submit(WorkItem(
            work_id="fenced-work", run_id=rid, tenant_id="tenant",
            available_at=utc_now(), idempotency_key="fenced-work"))
        old = await schedulers[0].claim(
            "old-worker", lease_duration=timedelta(seconds=0.08), wait_timeout=0)
        assert old is not None
        replacement = await asyncio.wait_for(schedulers[1].claim(
            "new-worker", lease_duration=timedelta(seconds=30), wait_timeout=1), 2)
        assert replacement is not None and replacement.fencing_token > old.fencing_token
        dispatched = False

        async def mutate():
            nonlocal dispatched
            dispatched = True
            return await transition(first, rid, RunState.RUNNING, "expired-owner-write")

        with pytest.raises(SageV2Error) as rejected:
            await schedulers[0].execute_fenced(old, mutate)
        assert rejected.value.info.code == "scheduler.fence_rejected"
        assert not dispatched
        assert await second.get_run(rid) == before
    finally:
        for scheduler in schedulers:
            await scheduler.close()


@pytest.mark.asyncio
async def test_deletion_on_another_instance_evicts_cached_state_and_cannot_be_rewritten(stores):
    first, second = stores
    created = await first.create_run(command(), CONTEXT)
    sid, rid = created.handle.session_id, created.handle.run_id
    await transition(first, rid, RunState.CANCELLED, "cancel")
    await first.archive_pending()
    await second.get_run(rid)
    await second.get_session(sid)
    await first.delete_session(sid)
    for read, identity, code in (
        (second.get_session, sid, "session.not_found"),
        (second.get_run, rid, "run.not_found"),
    ):
        with pytest.raises(SageV2Error) as missing:
            await read(identity)
        assert missing.value.info.code == code
    with pytest.raises(SageV2Error) as missing:
        await second.create_run(command("following", session_id=sid), CONTEXT)
    assert missing.value.info.code == "session.not_found"
    with pytest.raises(SageV2Error):
        await first.get_session(sid)


@pytest.mark.asyncio
async def test_cached_read_views_and_metadata_refresh_after_remote_commit_and_delete(stores):
    first, second = stores
    created = await first.create_run(command(), CONTEXT)
    sid, rid = created.handle.session_id, created.handle.run_id
    await second.get_run(rid)
    assert (await second.read_session_views([sid]))[sid].runs[0].run.state == RunState.QUEUED
    assert (await second.authorized_run_metadata_page([sid], CONTEXT))[0].state == RunState.QUEUED
    await transition(first, rid, RunState.RUNNING, "running")
    views = await second.read_session_views([sid], include_events=True)
    assert views[sid].runs[0].run.state == RunState.RUNNING
    assert views[sid].runs[0].events[-1].type == "run.started"
    assert (await second.authorized_run_metadata_page([sid], CONTEXT))[0].state == RunState.RUNNING
    await transition(first, rid, RunState.CANCELLED, "cancel")
    await first.archive_pending()
    assert (await second.read_session_views([sid]))[sid].runs[0].run.state == RunState.CANCELLED
    await first.delete_session(sid)
    assert await second.read_session_views([sid], include_events=True) == {}
    assert await second.authorized_run_metadata_page([sid], CONTEXT) == ()


@pytest.mark.asyncio
async def test_parent_delete_rechecks_child_created_after_its_descendant_snapshot(stores):
    first, second = stores
    parent = await first.create_run(command(), CONTEXT)
    sid, rid = parent.handle.session_id, parent.handle.run_id
    await transition(first, rid, RunState.CANCELLED, "cancel")
    snapshot_read, resume_delete = asyncio.Event(), asyncio.Event()
    original = first._archive._list_descendant_ids

    async def paused_snapshot(session_id):
        result = await original(session_id)
        snapshot_read.set()
        await resume_delete.wait()
        return result

    first._archive._list_descendant_ids = paused_snapshot
    deleting = asyncio.create_task(first.delete_session(sid))
    creating = None
    try:
        await asyncio.wait_for(snapshot_read.wait(), 2)
        creating = asyncio.create_task(second.create_run(
            command("child").model_copy(update={"parent_run_id": rid}), CONTEXT))
        # A correct provider may hold a topology guard before this snapshot.
        # Preserve the real wait: the competing admission can then remain
        # blocked until deletion resumes, rather than forcing one lock design.
        try:
            await asyncio.wait_for(asyncio.shield(creating), 0.05)
        except TimeoutError:
            pass
        resume_delete.set()
        deletion, child = await asyncio.wait_for(asyncio.gather(
            deleting, creating, return_exceptions=True), 2)
        if isinstance(child, SageV2Error):
            assert deletion is None
            assert child.info.code in {"session.not_found", "run.not_found", "run_id.not_found"}
            with pytest.raises(SageV2Error):
                await second.get_session(sid)
        else:
            assert not isinstance(child, BaseException)
            assert isinstance(deletion, SageV2Error), "parent deletion and new child admission cannot both succeed"
            assert deletion.info.code == "session.active_run"
            assert (await first.get_session(sid)).session_id == sid
            assert (await second.get_run(child.handle.run_id)).state == RunState.QUEUED
    finally:
        resume_delete.set()
        deleting.cancel()
        if creating is not None:
            creating.cancel()
            await asyncio.gather(creating, return_exceptions=True)
        await asyncio.gather(deleting, return_exceptions=True)
        first._archive._list_descendant_ids = original


@pytest.mark.asyncio
async def test_submitter_future_finishes_when_another_dispatcher_executes_the_run(stores):
    from sagents.v2.runtime import HarnessRuntime
    from sagents.v2.runtime.execution.dispatcher import LocalWorkerDispatcher
    from sagents.v2.runtime.execution.scheduler.plugins.redis_distributed import RedisDistributedScheduler

    first, second = stores
    created = await first.create_run(command(), CONTEXT)
    remotely_committed = asyncio.Event()
    executions = []

    class CompletingAgent:
        def __init__(self, store, node):
            self.runtime = HarnessRuntime(store)
            self.node = node

        def ensure_execution(self, run_id, context, *, resume):
            async def execute():
                executions.append(self.node)
                assert self.node == "worker-b", "only the remote worker may execute this Run"
                current = await self.runtime.get_run(run_id)
                running = await self.runtime.start_execution(
                    run_id=run_id, expected_revision=current.revision, context=context,
                    idempotency_key="remote-start")
                completed = await self.runtime.complete_run(
                    run_id=run_id, expected_revision=running.revision, context=context,
                    idempotency_key="remote-complete")
                remotely_committed.set()
                return completed

            return asyncio.create_task(execute())

    schedulers = []
    for store in stores:
        scheduler = RedisDistributedScheduler(
            redis_url=store.redis_url, key_prefix=store.key_prefix + ":remote-dispatch-test")
        scheduler._redis = store._redis
        schedulers.append(scheduler)
    original_claim = schedulers[0].claim

    async def claim_after_remote_completion(*args, **kwargs):
        # Control only timing: both providers retain real Redis admission,
        # claims, leases and cancellation. A cannot steal the submitted work
        # before B commits it, then resumes real empty claims and settlement.
        await remotely_committed.wait()
        return await original_claim(*args, **kwargs)

    schedulers[0].claim = claim_after_remote_completion
    dispatchers = [LocalWorkerDispatcher(
        scheduler, max_concurrent_runs=1, lease_seconds=30, distributed_claims=True)
        for scheduler in schedulers]
    agents = [CompletingAgent(first, "submitter-a"), CompletingAgent(second, "worker-b")]
    dispatchers[1].attach_recovery_agent(cast('RecoveryAgent', agents[1]))
    try:
        result = await dispatchers[0].submit(cast('RecoveryAgent', agents[0]), created.handle, CONTEXT)
        await dispatchers[1].start(recover=False)
        await asyncio.wait_for(remotely_committed.wait(), 2)
        assert (await first.get_run(created.handle.run_id)).state == RunState.COMPLETED
        completed = await asyncio.wait_for(asyncio.shield(result), 2)
        assert completed.run_id == created.handle.run_id
        assert completed.state == RunState.COMPLETED
        assert executions == ["worker-b"]
    finally:
        for dispatcher in dispatchers:
            await dispatcher.close()
        for scheduler in schedulers:
            await scheduler.close()


@pytest.mark.asyncio
async def test_deleted_start_key_is_reusable_even_when_submitter_has_the_old_session_cached(stores):
    first, second = stores
    original = await first.create_run(command(), CONTEXT)
    await transition(second, original.handle.run_id, RunState.CANCELLED, "cancel-original")
    await second.delete_session(original.handle.session_id)
    replacement = await first.create_run(command(), CONTEXT)
    duplicate = await second.create_run(command(), CONTEXT)
    assert not replacement.duplicate
    assert duplicate.duplicate
    assert replacement.handle.run_id != original.handle.run_id
    assert replacement.handle.session_id != original.handle.session_id
    assert duplicate.handle.run_id == replacement.handle.run_id
    assert duplicate.handle.session_id == replacement.handle.session_id
    for store in stores:
        assert (await store.get_run(replacement.handle.run_id)).state == RunState.QUEUED
        with pytest.raises(SageV2Error):
            await store.get_run(original.handle.run_id)


@pytest.mark.asyncio
async def test_concurrent_previews_for_different_runs_keep_each_runs_original_epoch(stores):
    first, _ = stores
    runs = [await first.create_run(command(key), CONTEXT) for key in ("first-run", "second-run")]
    expected = {}
    revisions = {}
    session_ids = set()
    for created in runs:
        rid = created.handle.run_id
        await transition(first, rid, RunState.RUNNING, "running-" + rid)
        await publish_preview(first, rid, "initial")
        preview, = await first.read_stream_previews(rid)
        expected[rid] = preview.preview_epoch
        revisions[rid] = (await first.get_run(rid)).revision
        session_ids.add(created.handle.session_id)
    assert len(set(expected.values())) == 2
    original_access = first._prepare_session_access
    reads = {sid: 0 for sid in session_ids}
    both_publications_ready = asyncio.Event()
    waiting = set()

    async def interleaved_access(session_id):
        await original_access(session_id)
        if session_id not in reads:
            return
        reads[session_id] += 1
        if reads[session_id] == 2:
            # The first read finds the Run; the second enters the coordinator
            # after the distributed publisher selected this Run's epoch. Hold
            # both there so a shared mutable epoch would contaminate a writer.
            waiting.add(session_id)
            if waiting == session_ids:
                both_publications_ready.set()
            await asyncio.wait_for(both_publications_ready.wait(), 2)

    first._prepare_session_access = interleaved_access
    try:
        await asyncio.wait_for(asyncio.gather(*(
            first.publish_stream_preview(
                run_id=rid, expected_revision=revisions[rid],
                drafts=(EventDraft(type="message.delta", item_id="assistant-message",
                                   data=ItemEventData(operation="delta", delta="concurrent")),),
                context=CONTEXT,
            ) for rid in expected
        )), 3)
        assert waiting == session_ids
    finally:
        first._prepare_session_access = original_access
    for rid, epoch in expected.items():
        previews = await first.read_stream_previews(rid)
        assert [event.preview_sequence for event in previews] == [1, 2]
        assert [event.data.delta for event in previews] == ["initial", "concurrent"]
        assert {event.preview_epoch for event in previews} == {epoch}


@pytest.mark.asyncio
async def test_preview_caught_up_reads_only_watermark_and_validates_new_suffix(stores, monkeypatch):
    from sagents.v2.contracts.events import RuntimeEvent

    first, second = stores
    rid = (await first.create_run(command(), CONTEXT)).handle.run_id
    await transition(first, rid, RunState.RUNNING, "running")
    run = await first.get_run(rid)
    await first.publish_stream_preview(
        run_id=rid, expected_revision=run.revision, context=CONTEXT,
        drafts=tuple(EventDraft(type="message.delta", item_id="assistant-message",
                                data=ItemEventData(operation="delta", delta=str(index)))
                     for index in range(2048)),
    )
    calls = []
    validate = RuntimeEvent.model_validate_json

    def observed(raw):
        calls.append(raw)
        return validate(raw)

    monkeypatch.setattr(RuntimeEvent, "model_validate_json", observed)
    for _ in range(10):
        assert await second.read_stream_previews(rid, after_preview_sequence=2048) == ()
    assert calls == []
    await publish_preview(first, rid, "new")
    event, = await second.read_stream_previews(rid, after_preview_sequence=2048)
    assert event.preview_sequence == 2049
    assert len(calls) == 1
    assert await first._redis.zcard(first._key("preview-events:" + rid)) == 2048


@pytest.mark.asyncio
async def test_preview_migrates_legacy_buffer_then_reports_overflow_and_hides_completed(stores):
    import json

    from sagents.v2.contracts.common import utc_now
    from sagents.v2.contracts.items import ItemSnapshot, ItemStatus, MessageItemData

    first, second = stores
    first.max_preview_events = second.max_preview_events = 3
    rid = (await first.create_run(command(), CONTEXT)).handle.run_id
    await transition(first, rid, RunState.RUNNING, "running")
    await publish_preview(first, rid, "old")
    old, = await second.read_stream_previews(rid)
    key = first._key("previews:" + rid)
    index = first._key("preview-events:" + rid)
    # Model an in-flight buffer left by the previous binary.
    await first._redis.hdel(key, "indexed_sequence")
    await first._redis.hset(key, "events", json.dumps([old.model_dump(mode="json")]))
    await first._redis.delete(index)
    assert (await second.read_stream_previews(rid)) == (old,)
    await publish_preview(first, rid, "migrated")
    assert [e.preview_sequence for e in await second.read_stream_previews(rid)] == [1, 2]
    for text in ("three", "four", "five", "six"):
        await publish_preview(first, rid, text)
    stream = second.subscribe_events(EventCursor(run_id=rid, run_sequence=old.run_sequence,
        preview_sequence=old.preview_sequence, preview_epoch=old.preview_epoch))
    try:
        gap = await asyncio.wait_for(anext(stream), 2)
        assert gap.type == "stream.gap" and gap.data.state == "preview_buffer_overflow"
        next_event = await asyncio.wait_for(anext(stream), 2)
        assert next_event.preview_sequence == 4 and next_event.preview_epoch == old.preview_epoch
    finally:
        await stream.aclose()

    run = await first.get_run(rid)
    now = utc_now()
    item = ItemSnapshot(item_id="assistant-message", run_id=rid, status=ItemStatus.COMPLETED,
        data=MessageItemData(role="assistant", content=(TextBlock(text="canonical"),)),
        created_at=now, updated_at=now)
    await first.commit_run(run_id=rid, expected_revision=run.revision, expected_states={RunState.RUNNING},
        new_state=RunState.RUNNING, context=CONTEXT, idempotency_key="complete-item",
        drafts=(EventDraft(type="message.completed", item_id=item.item_id,
            data=ItemEventData(operation="completed", item=item)),))
    assert await second.read_stream_previews(rid) == ()
    durable = await second.read_events(rid, after_sequence=old.run_sequence)
    assert [event.type for event in durable] == ["message.completed"]


@pytest.mark.asyncio
async def test_recovery_intent_survives_missing_resident_membership_without_loading_history(stores, monkeypatch):
    first, second = stores
    created = await first.create_run(command(), CONTEXT)
    rid, sid = created.handle.run_id, created.handle.session_id
    assert await first._redis.srem(first._key("resident"), sid)
    with monkeypatch.context() as patch:
        patch.setattr(second, "get_session", AsyncMock(side_effect=AssertionError("hydrated history")))
        intent, = await second.list_dispatchable_runs()
    assert intent.run.run_id == rid
    assert intent.run.state == RunState.QUEUED
    assert intent.context == CONTEXT

    # The legacy path still resolves canonical state when the derived fields
    # are absent. An old producer need only maintain its resident membership.
    await first._redis.sadd(first._key("resident"), sid)
    await first._redis.hdel(first._session_key(sid), "dispatch_revision", "dispatch_intents")
    legacy, = await second.list_dispatchable_runs()
    assert legacy == intent
    await transition(first, rid, RunState.CANCELLED, "cancel")
    assert await second.list_dispatchable_runs() == ()


@pytest.mark.asyncio
async def test_two_recovery_workers_requeue_original_runs_without_stealing_live_lease(stores):
    from collections import Counter

    from sagents.v2.runtime import HarnessRuntime
    from sagents.v2.runtime.execution.dispatcher import LocalWorkerDispatcher
    from sagents.v2.runtime.execution.scheduler import LeaseReleaseReason
    from sagents.v2.runtime.execution.scheduler.plugins.redis_distributed import RedisDistributedScheduler
    from sagents.v2.runtime.session.fencing import LeaseFencedSessionStore

    first, second = stores
    handles = [(await first.create_run(command(f"lost-handoff-{index}"), CONTEXT)).handle
               for index in range(8)]
    broken = (await first.create_run(command("unreadable-sibling"), CONTEXT)).handle
    broken_key = first._session_key(broken.session_id)
    broken_base = await first._redis.hget(broken_key, "base")
    original_intents = await first._redis.hget(broken_key, "dispatch_intents")

    executions = Counter()

    class CompletingAgent:
        def __init__(self, store):
            self.runtime = HarnessRuntime(store)

        def ensure_execution(self, run_id, context, *, resume):
            async def execute():
                assert not resume
                executions[run_id] += 1
                current = await self.runtime.get_run(run_id)
                running = await self.runtime.start_execution(
                    run_id=run_id, expected_revision=current.revision, context=context,
                    idempotency_key="recovered-start")
                await asyncio.sleep(.01)
                return await self.runtime.complete_run(
                    run_id=run_id, expected_revision=running.revision, context=context,
                    idempotency_key="recovered-complete")

            return asyncio.create_task(execute())

    schedulers, dispatchers = [], []
    for store in stores:
        scheduler = RedisDistributedScheduler(
            redis_url=store.redis_url, key_prefix=store.key_prefix + ":orphan-recovery",
            max_concurrent_runs=3, max_concurrent_runs_per_tenant=3)
        scheduler._redis = store._redis
        scheduler_store = LeaseFencedSessionStore(store, scheduler)
        dispatcher = LocalWorkerDispatcher(scheduler, max_concurrent_runs=1, lease_seconds=30,
            max_concurrent_runs_per_tenant=3, distributed_claims=True,
            lease_scope_factory=scheduler_store.lease_scope, recovery_interval_seconds=.05)
        dispatcher.attach_recovery_agent(cast("RecoveryAgent", CompletingAgent(store)))
        schedulers.append(scheduler)
        dispatchers.append(dispatcher)

    async def wait_completed(run_ids):
        async with asyncio.timeout(15):
            while True:
                snapshots = await asyncio.gather(*(second.get_run(run_id) for run_id in run_ids))
                if all(snapshot.state == RunState.COMPLETED for snapshot in snapshots):
                    return
                await asyncio.sleep(.03)

    try:
        await schedulers[0].submit(dispatchers[0]._work_item(handles[0], CONTEXT, resume=False))
        live = await schedulers[0].claim("original-worker", lease_duration=timedelta(seconds=45), wait_timeout=0)
        assert live is not None
        await first._redis.hset(broken_key, mapping={"dispatch_intents": "{", "base": "{"})
        first._recovery_required.add(broken.session_id)
        await asyncio.gather(*(dispatcher.start(recover=False) for dispatcher in dispatchers))
        await wait_completed([run.run_id for run in handles[1:]])
        assert executions[handles[0].run_id] == 0
        assert (await second.get_run(handles[0].run_id)).state == RunState.QUEUED
        await schedulers[0].assert_fence(live)
        await schedulers[0].release(live, LeaseReleaseReason.CANCELLED)
        await wait_completed([handles[0].run_id])
        assert executions == Counter({run.run_id: 1 for run in handles})
        await asyncio.gather(*(dispatcher.refresh_recovery() for dispatcher in dispatchers))
        assert await schedulers[0].pending_count() == 0
        assert broken.run_id not in executions
    finally:
        await asyncio.gather(*(dispatcher.close() for dispatcher in dispatchers))
        await first._redis.hset(broken_key, mapping={"dispatch_intents": original_intents, "base": broken_base})
        first._recovery_required.discard(broken.session_id)


@pytest.mark.asyncio
async def test_recovery_isolates_bad_session_and_rebuilds_only_derived_index(stores):
    first, second = stores
    good = (await first.create_run(command("good"), CONTEXT)).handle
    repairable = (await first.create_run(command("repairable"), CONTEXT)).handle
    unreadable = (await first.create_run(command("unreadable"), CONTEXT)).handle
    wrong_type = (await first.create_run(command("wrong-type"), CONTEXT)).handle
    repairable_key = first._session_key(repairable.session_id)
    unreadable_key = first._session_key(unreadable.session_id)
    wrong_type_key = first._session_key(wrong_type.session_id)
    original_base = await first._redis.hget(unreadable_key, "base")
    original_hash = await first._redis.hgetall(wrong_type_key)
    await first._redis.hset(repairable_key, "dispatch_intents", "{")
    await first._redis.hset(unreadable_key, mapping={"dispatch_intents": "{", "base": "{"})
    await first._redis.set(wrong_type_key, "not a hash")
    try:
        intents = await second.list_dispatchable_runs()
        assert {intent.run.run_id for intent in intents} == {good.run_id, repairable.run_id}
        assert all(intent.context == CONTEXT for intent in intents)
    finally:
        await first._redis.hset(unreadable_key, "base", original_base)
        await first._redis.delete(wrong_type_key)
        await first._redis.hset(wrong_type_key, mapping=original_hash)


@pytest.mark.asyncio
async def test_durable_event_tail_handles_revision_only_updates_and_reconnect(stores, monkeypatch):
    first, second = stores
    handle = (await first.create_run(command(), CONTEXT)).handle
    rid, sid = handle.run_id, handle.session_id
    await transition(first, rid, RunState.RUNNING, "running")
    before = await first.get_run(rid)
    canonical = second.read_events

    async def no_aggregate(*args, **kwargs):
        pytest.fail("recent durable event page loaded an aggregate")

    async def no_previews(*args, **kwargs):
        pytest.fail("durable subscription read live previews")

    with monkeypatch.context() as patch:
        patch.setattr(second, "read_events", no_aggregate)
        for revision in range(8):
            current = await first.get_run(rid)
            await first.commit_run(run_id=rid, expected_revision=current.revision,
                expected_states={RunState.RUNNING}, new_state=RunState.RUNNING, drafts=(),
                context=CONTEXT, idempotency_key=f"revision-only-{revision}")
            assert await second.read_indexed_run_events(
                rid, sid, after_sequence=before.last_run_sequence, limit=5) == ()

    await publish_preview(first, rid, "preview")
    current = await first.get_run(rid)
    added = await first.commit_run(run_id=rid, expected_revision=current.revision,
        expected_states={RunState.RUNNING}, new_state=RunState.RUNNING, context=CONTEXT,
        idempotency_key="event-burst", drafts=tuple(
            EventDraft(type="message.delta", item_id="durable-message",
                       data=ItemEventData(operation="delta", delta="x"*18000 if i == 100 else str(i)))
            for i in range(320)))
    # Both a cold gap and an individually oversized event use canonical replay.
    assert await second.read_indexed_run_events(
        rid, sid, after_sequence=before.last_run_sequence, limit=3) == added.events[:3]
    large = added.events[100]
    assert await second.read_indexed_run_events(rid, sid, after_sequence=large.run_sequence-1, limit=1) == (large,)
    assert await canonical(rid, after_sequence=before.last_run_sequence) == added.events

    # Disconnection after delivering 31 events must resume from the exact next event.
    with monkeypatch.context() as patch:
        patch.setattr(second, "read_events", no_aggregate)
        patch.setattr(second, "_read_preview_page", no_previews)
        async def reconnect():
            cursor = added.events[-64].run_sequence - 1
            stream = second.subscribe_durable_events(EventCursor(run_id=rid, run_sequence=cursor), sid)
            first_page = tuple([await asyncio.wait_for(anext(stream), 5) for _ in range(31)])
            await stream.aclose()
            stream = second.subscribe_durable_events(
                EventCursor(run_id=rid, run_sequence=first_page[-1].run_sequence), sid)
            remaining = tuple([await asyncio.wait_for(anext(stream), 5) for _ in range(33)])
            await stream.aclose()
            assert (*first_page, *remaining) == added.events[-64:]

        await asyncio.gather(*(reconnect() for _ in range(16)))
        streams = [second.subscribe_durable_events(
            EventCursor(run_id=rid, run_sequence=added.events[-1].run_sequence), sid) for _ in range(16)]
        waiting = [asyncio.create_task(anext(stream)) for stream in streams]
        try:
            await asyncio.sleep(.05)
            current = await first.get_run(rid)
            live = await first.commit_run(run_id=rid, expected_revision=current.revision,
                expected_states={RunState.RUNNING}, new_state=RunState.RUNNING, context=CONTEXT,
                idempotency_key="live-event", drafts=(EventDraft(type="message.delta", item_id="durable-message",
                    data=ItemEventData(operation="delta", delta="after-reconnect")),))
            assert await asyncio.wait_for(asyncio.gather(*waiting), 5) == [live.events[0]] * len(streams)
        finally:
            for task in waiting:
                task.cancel()
            await asyncio.gather(*waiting, return_exceptions=True)
            await asyncio.gather(*(stream.aclose() for stream in streams))

    # If an old writer advances past the index marker, never mistake a stale
    # indexed head for a caught-up cursor.
    session_key = first._session_key(sid)
    await first._redis.hset(session_key, "event_index_revision", "0")
    assert await second.read_indexed_run_events(
        rid, sid, after_sequence=added.events[-2].run_sequence, limit=1) == added.events[-1:]

from copy import deepcopy
import asyncio
import threading
import time
from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest

from sagents.v2.contracts.run_state import RunState
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.runtime.session.plugins.mysql.redis import RedisMysqlSessionStore
from tests.sagents.v2.test_mysql_session_store_matrix import command, CONTEXT


class Archive:
    def __init__(self):
        self.states = {}
        self.writes = 0
        self.fail = False
        self.attachments = {}

    async def _fetch_session(self, sid):
        return deepcopy(self.states.get(sid))

    async def _fetch_sessions(self, session_ids):
        return {sid: deepcopy(self.states[sid]) for sid in session_ids if sid in self.states}

    async def revision(self, sid):
        state = self.states.get(sid)
        return None if state is None else state["sessions"][0]["revision"]

    async def revisions(self, session_ids):
        return {sid: self.states[sid]["sessions"][0]["revision"]
                for sid in session_ids if sid in self.states}

    async def archive_batch(self, sid, mutations):
        from sagents.v2.runtime.session.plugins.mysql.state import _MysqlSessionState
        if self.fail:
            raise OSError("mysql unavailable")
        rows = [(revision, encoded) for revision, encoded in mutations
                if revision > self.states[sid]["sessions"][0]["revision"]]
        if rows:
            import json
            sequence = json.loads(rows[-1][1])["upserts"]["sessions"][0]["last_sequence"]
            self.states[sid] = _MysqlSessionState._replay_mutations(
                self.states[sid], rows, rows[-1][0], sequence)

    async def archive_attachments(self, sid, attachments):
        self.attachments.update({(sid, key): value for key, value in attachments.items()})

    async def archive_session(self, payload, attachments):
        if self.fail:
            raise OSError("mysql unavailable")
        sid = payload["sessions"][0]["session_id"]
        previous = self.states.get(sid)
        if previous is None or previous["sessions"][0]["revision"] < payload["sessions"][0]["revision"]:
            self.states[sid] = deepcopy(payload)
            self.attachments.update({(sid, key): value for key, value in attachments.items()})
            self.writes += 1

    async def _read_start_lookup(self, command, context):
        return None

    async def _locate_session(self, kind, identity):
        return next((sid for sid, state in self.states.items()
                     if any(row.get(kind) == identity for row in state["runs"])), None)

    async def _list_descendant_ids(self, sid):
        return []

    async def delete_archived_sessions(self, ids):
        for sid in ids:
            self.states.pop(sid, None)

    async def close(self):
        pass

    async def _read_attachment_bytes(self, sid, identity):
        return self.attachments[(sid, identity)]


def store(redis, archive, *, background=False):
    redis.info = AsyncMock(side_effect=lambda section: {"maxmemory_policy": "noeviction", "aof_enabled": 1})
    value = RedisMysqlSessionStore("mysql://unused/test", redis_url="redis://unused/0",
                                   archive_interval_seconds=3600)
    value._redis = redis
    value._archive = archive
    if not background:
        async def idle():
            await asyncio.Event().wait()
        value._archive_loop = idle
    return value


async def transition(value, created, target, key):
    current = await value.get_run(created.handle.run_id)
    return await value.commit_run(run_id=current.run_id, expected_revision=current.revision,
        expected_states={current.state}, new_state=target, drafts=(), context=CONTEXT,
        idempotency_key=key)


@pytest.mark.asyncio
async def test_running_writes_only_redis_and_terminal_run_archives_once():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    archive = Archive()
    value = store(redis, archive)
    created = await value.create_run(command(), CONTEXT)
    await transition(value, created, RunState.RUNNING, "running")
    assert archive.writes == 0
    await value.archive_pending()
    assert archive.writes == 0
    await transition(value, created, RunState.CANCELLED, "cancel")
    await value.archive_pending()
    assert archive.writes == 1
    assert archive.states[created.handle.session_id]["runs"][0]["state"] == "cancelled"
    await value.archive_pending()
    assert archive.writes == 1
    await value.close()


@pytest.mark.asyncio
async def test_pending_archive_prefetches_session_reads_and_revisions_in_one_batch():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    archive = Archive()
    value = store(redis, archive)
    expected = {}
    for i in range(3):
        created = await value.create_run(command(f"start-{i}"), CONTEXT)
        await transition(value, created, RunState.CANCELLED, f"cancel-{i}")
        expected[created.handle.session_id] = await value.export_session_state(created.handle.session_id)
    archive.revision = AsyncMock(wraps=archive.revision)
    archive.revisions = AsyncMock(wraps=archive.revisions)
    original = redis.execute_command
    individual_reads = []

    async def command_call(*args, **kwargs):
        if args[0] in {"HMGET", "HGETALL"}:
            individual_reads.append(args)
        return await original(*args, **kwargs)

    redis.execute_command = command_call
    try:
        await value.archive_pending()
        assert archive.states == expected
        archive.revision.assert_not_awaited()
        archive.revisions.assert_awaited_once()
        assert set(archive.revisions.await_args.args[0]) == set(expected)
        assert individual_reads == []
    finally:
        redis.execute_command = original
        await value.close()


@pytest.mark.asyncio
async def test_corrupt_pending_session_does_not_block_other_sessions_archiving():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    archive = Archive()
    value = store(redis, archive)
    broken = await value.create_run(command("broken"), CONTEXT)
    good = await value.create_run(command("good"), CONTEXT)
    for created in (broken, good):
        await transition(value, created, RunState.CANCELLED, "cancel")
    await redis.hdel(value._session_key(broken.handle.session_id), "base")
    try:
        await value.archive_pending()
        assert set(archive.states) == {good.handle.session_id}
        assert await redis.smembers(value._key("pending")) == {broken.handle.session_id}
    finally:
        await value.close()


@pytest.mark.asyncio
async def test_mysql_outage_keeps_terminal_events_and_retries_after_restart():
    server = fakeredis.FakeServer()
    archive = Archive()
    value = store(fakeredis.aioredis.FakeRedis(server=server, decode_responses=True), archive)
    created = await value.create_run(command(), CONTEXT)
    await transition(value, created, RunState.CANCELLED, "cancel")
    archive.fail = True
    await value.archive_pending()
    assert (await value.get_run(created.handle.run_id)).state == RunState.CANCELLED
    await value.close()

    reopened = store(fakeredis.aioredis.FakeRedis(server=server, decode_responses=True), archive)
    assert (await reopened.get_run(created.handle.run_id)).state == RunState.CANCELLED
    assert (await reopened.create_run(command(), CONTEXT)).duplicate
    archive.fail = False
    await reopened.archive_pending()
    assert archive.writes == 1
    await reopened.close()


@pytest.mark.asyncio
async def test_background_worker_archives_without_blocking_terminal_commit():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    archive = Archive()
    entered, release = asyncio.Event(), asyncio.Event()
    original = archive.archive_session
    async def blocked(payload, attachments):
        entered.set()
        await release.wait()
        await original(payload, attachments)
    archive.archive_session = blocked
    value = store(redis, archive, background=True)
    created = await value.create_run(command(), CONTEXT)
    await asyncio.wait_for(transition(value, created, RunState.CANCELLED, "cancel"), 1)
    await asyncio.wait_for(entered.wait(), 1)
    assert archive.writes == 0
    release.set()
    await value.archive_pending()
    assert archive.writes == 1
    await value.close()


@pytest.mark.asyncio
async def test_archive_of_old_revision_cannot_expire_new_running_state():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    archive = Archive()
    value = store(redis, archive)
    created = await value.create_run(command(), CONTEXT)
    await transition(value, created, RunState.CANCELLED, "cancel")
    entered, release = asyncio.Event(), asyncio.Event()
    original = archive.archive_session
    async def blocked(payload, attachments):
        entered.set()
        await release.wait()
        await original(payload, attachments)
    archive.archive_session = blocked
    task = asyncio.create_task(value.archive_pending())
    await asyncio.wait_for(entered.wait(), 1)
    sid = created.handle.session_id
    following = await value.create_run(command("next").model_copy(update={"session_id": sid}), CONTEXT)
    await transition(value, following, RunState.RUNNING, "next-running")
    release.set()
    await task
    assert await redis.sismember(value._key("pending"), sid)
    assert await redis.ttl(value._session_key(sid)) == -1
    await value.archive_pending()
    assert archive.states[sid]["runs"][-1]["state"] == "running"
    assert await redis.sismember(value._key("resident"), sid)
    assert await redis.ttl(value._session_key(sid)) == -1
    await value.close()


@pytest.mark.asyncio
async def test_expired_archived_cache_can_accept_following_run_and_preserve_history():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    archive = Archive()
    value = store(redis, archive)
    created = await value.create_run(command(), CONTEXT)
    await transition(value, created, RunState.CANCELLED, "cancel")
    await value.archive_pending()
    sid = created.handle.session_id
    assert await redis.ttl(value._session_key(sid)) > 0
    await redis.delete(value._session_key(sid))
    following = await value.create_run(command("next").model_copy(update={"session_id": sid}), CONTEXT)
    runs = await value.list_session_runs(sid)
    assert [run.state for run in runs] == [RunState.CANCELLED, RunState.QUEUED]
    assert (await value.get_start_command(created.handle.run_id)).idempotency_key == "start_1"
    assert (await value.get_run(following.handle.run_id)).state == RunState.QUEUED
    await value.close()


@pytest.mark.asyncio
async def test_missing_unarchived_redis_state_never_falls_back_to_old_mysql():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    archive = Archive()
    value = store(redis, archive)
    created = await value.create_run(command(), CONTEXT)
    sid = created.handle.session_id
    await redis.delete(value._session_key(sid))
    with pytest.raises(SageV2Error, match="Unarchived"):
        await value.export_session_state(sid)
    with pytest.raises(SageV2Error, match="Unarchived"):
        await value._fetch_sessions([sid])
    await value.close()


@pytest.mark.asyncio
async def test_batch_session_fetch_keeps_hot_authority_and_seeds_cold_before_next_commit():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    archive = Archive()
    value = store(redis, archive)
    try:
        hot = await value.create_run(command('hot'), CONTEXT)
        cold = await value.create_run(command('cold'), CONTEXT)
        deleted = await value.create_run(command('deleted'), CONTEXT)
        await transition(value, cold, RunState.CANCELLED, 'cold-cancel')
        await transition(value, deleted, RunState.CANCELLED, 'deleted-cancel')
        await value.archive_pending()
        expected = {created.handle.session_id: await value.export_session_state(created.handle.session_id)
                    for created in (hot, cold)}
        await redis.delete(value._session_key(cold.handle.session_id))
        await redis.hset(value._session_key(deleted.handle.session_id), mapping={'deleted': '1'})
        for created in (hot, cold, deleted):
            value._evict_session_locked(created.handle.session_id)
        original = value._fetch_session
        value._fetch_session = AsyncMock(side_effect=AssertionError('batch called single-session fetch'))
        archive._fetch_session = AsyncMock(side_effect=AssertionError('batch issued single-session SQL'))
        archive._fetch_sessions = AsyncMock(wraps=archive._fetch_sessions)
        assert await value._fetch_sessions([*expected, deleted.handle.session_id, 'missing']) == expected
        archive._fetch_sessions.assert_awaited_once()
        assert set(archive._fetch_sessions.await_args.args[0]) == {cold.handle.session_id, 'missing'}
        async with value._session_cache.operation():
            await value._ensure_sessions_loaded([*expected, deleted.handle.session_id])
            assert set(value._sessions) == set(expected)
            assert len(value._runs) == 2
        value._fetch_session = original
        following = await value.create_run(command('next').model_copy(update={'session_id': cold.handle.session_id}), CONTEXT)
        assert (await value.get_run(following.handle.run_id)).state == RunState.QUEUED
        assert len(await value.list_session_runs(cold.handle.session_id)) == 2
    finally:
        await value.close()


@pytest.mark.asyncio
async def test_attachment_bytes_survive_reopen_and_cold_mysql_read():
    server = fakeredis.FakeServer()
    archive = Archive()
    redis = fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)
    value = store(redis, archive)
    created = await value.create_run(command(), CONTEXT)
    sid = created.handle.session_id
    async def content():
        yield b"\x00binary\xff"
    await value.put_attachment(sid, artifact_id="image", media_type="image/jpeg", content=content(), context=CONTEXT)
    await transition(value, created, RunState.CANCELLED, "cancel")
    await value.archive_pending()
    await redis.delete(value._session_key(sid), value._key(f"attachments:{sid}"))
    await value.close()
    reopened = store(fakeredis.aioredis.FakeRedis(server=server, decode_responses=True), archive)
    _, chunks = await reopened.get_attachment(sid, "image", context=CONTEXT)
    assert b"".join([chunk async for chunk in chunks]) == b"\x00binary\xff"
    await reopened.close()


@pytest.mark.asyncio
async def test_delete_is_authoritative_during_mysql_outage_and_retried_on_reopen():
    server = fakeredis.FakeServer()
    archive = Archive()
    value = store(fakeredis.aioredis.FakeRedis(server=server, decode_responses=True), archive)
    created = await value.create_run(command(), CONTEXT)
    await transition(value, created, RunState.CANCELLED, "cancel")
    await value.archive_pending()
    original = archive.delete_archived_sessions
    async def fail(ids):
        raise OSError("offline")
    archive.delete_archived_sessions = fail
    await value.delete_session(created.handle.session_id)
    await value.archive_pending()
    assert created.handle.session_id in archive.states
    with pytest.raises(SageV2Error):
        await value.get_run(created.handle.run_id)
    await value.close()
    reopened = store(fakeredis.aioredis.FakeRedis(server=server, decode_responses=True), archive)
    with pytest.raises(SageV2Error):
        await reopened.get_session(created.handle.session_id)
    archive.delete_archived_sessions = original
    await reopened.archive_pending()
    assert created.handle.session_id not in archive.states
    await reopened.close()


@pytest.mark.asyncio
async def test_namespace_allows_only_one_live_writer():
    server = fakeredis.FakeServer()
    archive = Archive()
    first = store(fakeredis.aioredis.FakeRedis(server=server, decode_responses=True), archive)
    await first.create_run(command(), CONTEXT)
    second = store(fakeredis.aioredis.FakeRedis(server=server, decode_responses=True), archive)
    with pytest.raises(SageV2Error, match="already owned"):
        await second.create_run(command("other"), CONTEXT)
    await first.close()
    await second.close()


@pytest.mark.asyncio
async def test_start_waits_for_crashed_writer_lease_to_expire():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    value = store(redis, Archive())
    owner_key = value._key("owner")
    await redis.set(owner_key, "crashed-process", px=100)
    try:
        services = await asyncio.wait_for(value.start(None, ()), timeout=2)
        assert services["session.store"] is value
        assert await redis.get(owner_key) == value._owner
        created = await value.create_run(command(), CONTEXT)
        assert (await value.get_run(created.handle.run_id)).state == RunState.QUEUED
    finally:
        await value.close()


@pytest.mark.asyncio
async def test_start_times_out_without_stealing_live_writer_lease(monkeypatch):
    from sagents.v2.runtime.session.plugins.mysql import redis as redis_mysql

    monkeypatch.setattr(redis_mysql, "_OWNER_STARTUP_WAIT_SECONDS", 0.1)
    server = fakeredis.FakeServer()
    archive = Archive()
    first = store(fakeredis.aioredis.FakeRedis(server=server, decode_responses=True), archive)
    second = store(fakeredis.aioredis.FakeRedis(server=server, decode_responses=True), archive)
    await first.create_run(command(), CONTEXT)
    try:
        started = time.monotonic()
        with pytest.raises(SageV2Error, match="already owned"):
            await asyncio.wait_for(second.start(None, ()), timeout=1)
        assert time.monotonic() - started >= 0.1
        assert await first._redis.get(first._key("owner")) == first._owner
        assert not second._redis_ready
        assert second._worker is None
        assert second._lease_worker is None
        await first.create_run(command("still-owned"), CONTEXT)
    finally:
        await second.close()
        await first.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True], ids=["released", "cancelled"])
async def test_start_wait_can_finish_on_release_or_be_cancelled(cancel):
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    value = store(redis, Archive())
    owner_key = value._key("owner")
    await redis.set(owner_key, "previous-process", ex=30)
    attempted = asyncio.Event()
    original = redis.set

    async def observed_set(*args, **kwargs):
        result = await original(*args, **kwargs)
        attempted.set()
        return result

    redis.set = observed_set
    task = asyncio.create_task(value.start(None, ()))
    try:
        await asyncio.wait_for(attempted.wait(), timeout=1)
        assert not task.done()
        assert not value._redis_ready
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert await redis.get(owner_key) == "previous-process"
            assert value._worker is None
            assert value._lease_worker is None
        else:
            await redis.delete(owner_key)
            services = await asyncio.wait_for(task, timeout=2)
            assert services["session.store"] is value
            assert await redis.get(owner_key) == value._owner
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await value.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("after_exec", [True, False])
async def test_ambiguous_redis_response_resolves_commit_token(after_exec):
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    archive = Archive()
    value = store(redis, archive)
    created = await value.create_run(command(), CONTEXT)
    original = redis.pipeline
    failed = False
    def pipeline(*args, **kwargs):
        pipe = original(*args, **kwargs)
        execute = pipe.execute
        async def fail_once(*a, **kw):
            nonlocal failed
            if not failed:
                failed = True
                if after_exec:
                    await execute(*a, **kw)
                raise OSError("lost EXEC response")
            return await execute(*a, **kw)
        pipe.execute = fail_once
        return pipe
    redis.pipeline = pipeline
    if after_exec:
        await transition(value, created, RunState.RUNNING, "running")
    else:
        with pytest.raises(OSError):
            await transition(value, created, RunState.RUNNING, "running")
    assert (await value.get_run(created.handle.run_id)).state == (RunState.RUNNING if after_exec else RunState.QUEUED)
    await value.close()


@pytest.mark.asyncio
async def test_deleted_start_key_is_reusable_before_mysql_delete_succeeds():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    archive = Archive()
    value = store(redis, archive)
    created = await value.create_run(command(), CONTEXT)
    await transition(value, created, RunState.CANCELLED, "cancel")
    await value.delete_session(created.handle.session_id)
    following = await value.create_run(command(), CONTEXT)
    assert following.handle.session_id != created.handle.session_id
    await value.close()


@pytest.mark.asyncio
async def test_lost_delete_response_does_not_resurrect_deleted_memory():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    value = store(redis, Archive())
    created = await value.create_run(command(), CONTEXT)
    await transition(value, created, RunState.CANCELLED, "cancel")
    original = redis.pipeline
    failed = False
    def pipeline(*args, **kwargs):
        pipe = original(*args, **kwargs)
        execute = pipe.execute
        async def lost(*a, **kw):
            nonlocal failed
            result = await execute(*a, **kw)
            if not failed:
                failed = True
                raise TimeoutError("lost delete response")
            return result
        pipe.execute = lost
        return pipe
    redis.pipeline = pipeline
    await value.delete_session(created.handle.session_id)
    with pytest.raises(SageV2Error):
        await value.get_session(created.handle.session_id)
    await value.close()


@pytest.mark.asyncio
async def test_lost_delete_and_confirmation_response_force_resource_reload():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    value = store(redis, Archive())
    created = await value.create_run(command(), CONTEXT)
    await transition(value, created, RunState.CANCELLED, "cancel")
    original_pipeline, original_hget = redis.pipeline, redis.hget
    failed = False
    def pipeline(*args, **kwargs):
        pipe = original_pipeline(*args, **kwargs)
        execute = pipe.execute
        async def lost(*a, **kw):
            nonlocal failed
            result = await execute(*a, **kw)
            if not failed:
                failed = True
                raise TimeoutError("lost delete response")
            return result
        pipe.execute = lost
        return pipe
    async def hget(*args, **kwargs):
        if args[-1] == "delete_id":
            raise OSError("confirmation connection lost")
        return await original_hget(*args, **kwargs)
    redis.pipeline, redis.hget = pipeline, hget
    with pytest.raises(OSError):
        await value.delete_session(created.handle.session_id)
    redis.hget = original_hget
    with pytest.raises(SageV2Error):
        await value.get_run(created.handle.run_id)
    await value.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("memory,persistence", [
    ({"maxmemory_policy": "allkeys-lru"}, {"aof_enabled": 1}),
    ({"maxmemory_policy": "noeviction"}, {"aof_enabled": 0}),
])
async def test_cache_only_redis_configuration_is_rejected(memory, persistence):
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    value = store(redis, Archive())
    redis.info = AsyncMock(side_effect=lambda section: memory if section == "memory" else persistence)
    with pytest.raises(SageV2Error, match="noeviction and AOF"):
        await value.create_run(command(), CONTEXT)
    await value.close()


@pytest.mark.asyncio
async def test_stopped_redis_transaction_retries_watch_conflict():
    from redis.exceptions import WatchError
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    value = store(redis, Archive())
    created = await value.create_run(command(), CONTEXT)
    original = redis.pipeline
    failed = False
    def pipeline(*args, **kwargs):
        pipe = original(*args, **kwargs)
        execute = pipe.execute
        async def conflict(*a, **kw):
            nonlocal failed
            if not failed:
                failed = True
                raise WatchError("lease renewal changed the watched key")
            return await execute(*a, **kw)
        pipe.execute = conflict
        return pipe
    redis.pipeline = pipeline
    await transition(value, created, RunState.RUNNING, "running")
    assert (await value.get_run(created.handle.run_id)).state == RunState.RUNNING
    await value.close()


@pytest.mark.asyncio
async def test_multiple_commits_compact_and_replay_full_event_history():
    server = fakeredis.FakeServer()
    archive = Archive()
    redis = fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)
    value = store(redis, archive)
    value.snapshot_interval = 2
    created = await value.create_run(command(), CONTEXT)
    await transition(value, created, RunState.RUNNING, "running")
    await transition(value, created, RunState.CANCELLED, "cancel")
    before = await value.export_session_state(created.handle.session_id)
    await value.close()
    reopened = store(fakeredis.aioredis.FakeRedis(server=server, decode_responses=True), archive)
    after = await reopened.export_session_state(created.handle.session_id)
    assert before == after
    assert (await reopened.create_run(command(), CONTEXT)).duplicate
    await reopened.close()


@pytest.mark.asyncio
async def test_unfinished_run_is_recovered_from_redis_after_restart():
    server = fakeredis.FakeServer()
    archive = Archive()
    value = store(fakeredis.aioredis.FakeRedis(server=server, decode_responses=True), archive)
    created = await value.create_run(command(), CONTEXT)
    await transition(value, created, RunState.RUNNING, "running")
    await value.close()
    reopened = store(fakeredis.aioredis.FakeRedis(server=server, decode_responses=True), archive)
    runs = await reopened.list_dispatchable_runs()
    assert [row.run.run_id for row in runs] == [created.handle.run_id]
    assert archive.writes == 0
    await reopened.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["_fetch_session", "_archive_session"])
async def test_hot_session_replay_allows_writer_lease_renewal(operation):
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    value = store(redis, Archive())
    created = await value.create_run(command(), CONTEXT)
    await transition(value, created, RunState.CANCELLED, "cancel")
    value.snapshot_interval = 1
    entered, release, timed_out = threading.Event(), threading.Event(), threading.Event()
    original = value._decode_hot

    def slow_decode(fields):
        entered.set()
        if not release.wait(timeout=2):
            timed_out.set()
        return original(fields)

    async def renew_while_replaying():
        assert await asyncio.to_thread(entered.wait, 2)
        await value._renew()
        renewed_before_replay_finished = not release.is_set() and not timed_out.is_set()
        release.set()
        return renewed_before_replay_finished

    value._decode_hot = slow_decode
    heartbeat = asyncio.create_task(renew_while_replaying())
    replay = asyncio.create_task(getattr(value, operation)(created.handle.session_id))
    try:
        renewed, _ = await asyncio.wait_for(asyncio.gather(heartbeat, replay), 5)
        assert renewed, "Session replay blocked the event loop and prevented writer lease renewal"
    finally:
        release.set()
        await asyncio.gather(heartbeat, replay, return_exceptions=True)
        value._decode_hot = original
        await value.close()


@pytest.mark.asyncio
async def test_running_commits_append_deltas_without_rewriting_session_snapshot():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    value = store(redis, Archive())
    value.snapshot_interval = 2
    created = await value.create_run(command(), CONTEXT)
    sid = created.handle.session_id
    key = value._session_key(sid)
    base = await redis.hget(key, "base")
    try:
        await transition(value, created, RunState.RUNNING, "running")
        await transition(value, created, RunState.CANCELLED, "cancel")

        fields = await redis.hgetall(key)
        assert fields["base"] == base, "Hot commits must not rewrite the complete Session snapshot"
        assert {"d:2", "d:3"}.issubset(fields)
        expected = await value.export_session_state(sid)
        assert await value._fetch_session(sid) == expected
    finally:
        await value.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(("part_count", "delta_count", "max_round_trips"), [(64, 128, 4), (1024, 1024, 10)])
async def test_hot_snapshot_and_delta_reads_batch_round_trips_without_losing_fields(part_count, delta_count, max_round_trips):
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    value = store(redis, Archive())
    key = value._session_key("batched-read")
    parts = [f"part-{i};" for i in range(part_count)]
    fields = {"revision": str(delta_count + 1), "last_sequence": str(delta_count), "base_revision": "1",
              "base_snapshot": "batched", "base_parts": str(part_count)}
    deltas = {f"d:{i}": f"mutation-{i}" for i in range(2, delta_count + 2)}
    await redis.hset(key, mapping={**fields, **deltas})
    await redis.hset(value._key("snapshot:batched"), mapping=dict(enumerate(parts)))
    original_command, original_pipeline = redis.execute_command, redis.pipeline
    round_trips = 0

    async def command(*args, **kwargs):
        nonlocal round_trips
        round_trips += 1
        return await original_command(*args, **kwargs)

    def pipeline(*args, **kwargs):
        pipe = original_pipeline(*args, **kwargs)
        execute = pipe.execute

        async def counted_execute(*args, **kwargs):
            nonlocal round_trips
            round_trips += 1
            assert len(pipe.command_stack) <= 32
            return await execute(*args, **kwargs)

        pipe.execute = counted_execute
        return pipe

    redis.execute_command, redis.pipeline = command, pipeline
    try:
        assert await value._read_hot(key) == {**fields, **deltas, "base": "".join(parts)}
        assert round_trips <= max_round_trips
    finally:
        redis.execute_command, redis.pipeline = original_command, original_pipeline
        await value.close()


@pytest.mark.asyncio
async def test_background_snapshot_chunks_survive_resume_and_reader_compaction_race():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    value = store(redis, Archive())
    value.snapshot_interval = 2
    value.snapshot_chunk_chars = 1024
    created = await value.create_run(command(), CONTEXT)
    await transition(value, created, RunState.RUNNING, "running")
    await transition(value, created, RunState.CANCELLED, "cancel")
    sid = created.handle.session_id
    expected = await value.export_session_state(sid)
    old_fields = await value._read_hot(value._session_key(sid))
    original = redis.pipeline
    compacted = False

    def compact_during_read(*args, **kwargs):
        pipe = original(*args, **kwargs)
        execute = pipe.execute

        async def compact_before_execute(*args, **kwargs):
            nonlocal compacted
            if not compacted and any(command[0] == "HMGET" and command[1] == value._session_key(sid)
                    and any(str(name).startswith("d:") for name in command[2:])
                    for command, _ in pipe.command_stack):
                compacted = True
                await value._compact_hot(sid, old_fields)
            return await execute(*args, **kwargs)

        pipe.execute = compact_before_execute
        return pipe

    redis.pipeline = compact_during_read
    try:
        assert await value._fetch_session(sid) == expected
        assert compacted
        await value.archive_pending()
        token = await redis.hget(value._session_key(sid), "base_snapshot")
        snapshot_key = value._key(f"snapshot:{token}")
        parts = await redis.hgetall(snapshot_key)
        assert len(parts) > 1
        assert all(len(part.encode("utf-8")) <= 4096 for part in parts.values())
        assert await redis.ttl(snapshot_key) > 0
        await value.create_run(command("next").model_copy(update={"session_id": sid}), CONTEXT)
        assert await redis.ttl(snapshot_key) == -1
        assert len((await value._fetch_session(sid))["runs"]) == 2
    finally:
        redis.pipeline = original
        await value.close()


@pytest.mark.asyncio
async def test_large_initial_session_is_uploaded_as_bounded_chunks():
    from sagents.v2.contracts.commands import InputItem
    from sagents.v2.contracts.items import TextBlock
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    value = store(redis, Archive())
    text = "大输入" * 40000
    large = command().model_copy(update={"input": (InputItem(role="user", content=(TextBlock(text=text),)),)})
    try:
        created = await value.create_run(large, CONTEXT)
        key = value._session_key(created.handle.session_id)
        assert await redis.hget(key, "base") is None
        token = await redis.hget(key, "base_snapshot")
        parts = await redis.hgetall(value._key(f"snapshot:{token}"))
        assert all(len(part.encode("utf-8")) <= value.snapshot_chunk_chars * 4 for part in parts.values())
        loaded = await value._fetch_session(created.handle.session_id)
        assert loaded["runs"][0]["start_command"]["input"][0]["content"][0]["text"] == text
    finally:
        await value.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(("chunk_chars", "max_batches"), [(16 * 1024, 2), (128, 30)])
async def test_snapshot_upload_batches_small_chunks_with_bounded_pipeline_bytes(chunk_chars, max_batches):
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    value = store(redis, Archive())
    value.snapshot_chunk_chars = chunk_chars
    encoded = "大输入" * 40000
    original = redis.pipeline
    pipeline_sizes = []

    def pipeline(*args, **kwargs):
        pipe = original(*args, **kwargs)
        execute = pipe.execute

        async def counted_execute(*args, **kwargs):
            commands = [command for command, _ in pipe.command_stack if command[0] == "HSET"]
            assert len(commands) <= 32
            pipeline_sizes.append(sum(len(command[-1].encode("utf-8")) for command in commands))
            return await execute(*args, **kwargs)

        pipe.execute = counted_execute
        return pipe

    redis.pipeline = pipeline
    try:
        token, count = await value._stage_snapshot(encoded)
        parts = await redis.hmget(value._key(f"snapshot:{token}"), [str(i) for i in range(count)])
        assert "".join(parts) == encoded
        assert await redis.ttl(value._key(f"snapshot:{token}")) > 0
        assert all(size <= value.archive_batch_bytes for size in pipeline_sizes)
        assert len(pipeline_sizes) <= max_batches
    finally:
        redis.pipeline = original
        await value.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("bulk", [False, True], ids=["single", "batch"])
async def test_cold_read_racing_with_completed_deletion_preserves_tombstone(bulk):
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    archive = Archive()
    value = store(redis, archive)
    created = await value.create_run(command(), CONTEXT)
    sid = created.handle.session_id
    await transition(value, created, RunState.CANCELLED, "cancel")
    await value.archive_pending()
    key = value._session_key(sid)
    await redis.delete(key)
    method = "_fetch_sessions" if bulk else "_fetch_session"
    original = getattr(archive, method)

    async def deleted_after_sql_read(session_id):
        old_payload = await original(session_id)
        # Completed deletion retains a durable tombstone without a revision.
        await redis.hset(key, mapping={"deleted": "1"})
        return old_payload

    setattr(archive, method, deleted_after_sql_read)
    try:
        if bulk:
            assert await value._fetch_sessions([sid]) == {}
        else:
            assert await value._fetch_session(sid) is None
        assert await redis.hgetall(key) == {"deleted": "1"}
    finally:
        setattr(archive, method, original)
        await value.close()

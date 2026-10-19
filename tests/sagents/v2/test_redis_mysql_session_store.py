from copy import deepcopy
import asyncio
import threading
from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest

from sagents.v2.contracts.run_state import RunState
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.runtime.session.plugins.redis_mysql import RedisMysqlSessionStore
from tests.sagents.v2.test_mysql_session_store_matrix import command, CONTEXT


class Archive:
    def __init__(self):
        self.states = {}
        self.writes = 0
        self.fail = False
        self.attachments = {}

    async def _fetch_session(self, sid):
        return deepcopy(self.states.get(sid))

    async def revision(self, sid):
        state = self.states.get(sid)
        return None if state is None else state["sessions"][0]["revision"]

    async def archive_batch(self, sid, mutations):
        from sagents.v2.runtime.session.mysql_state import _MysqlSessionState
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
    original = redis.hmget
    compacted = False

    async def compact_during_read(key, keys, *args):
        nonlocal compacted
        if key == value._session_key(sid) and any(str(name).startswith("d:") for name in keys) and not compacted:
            compacted = True
            await value._compact_hot(sid, old_fields)
        return await original(key, keys, *args)

    redis.hmget = compact_during_read
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
        redis.hmget = original
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
async def test_cold_read_racing_with_completed_deletion_preserves_tombstone():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    archive = Archive()
    value = store(redis, archive)
    created = await value.create_run(command(), CONTEXT)
    sid = created.handle.session_id
    await transition(value, created, RunState.CANCELLED, "cancel")
    await value.archive_pending()
    key = value._session_key(sid)
    await redis.delete(key)
    original = archive._fetch_session

    async def deleted_after_sql_read(session_id):
        old_payload = await original(session_id)
        # Completed deletion retains a durable tombstone without a revision.
        await redis.hset(key, mapping={"deleted": "1"})
        return old_payload

    archive._fetch_session = deleted_after_sql_read
    try:
        assert await value._fetch_session(sid) is None
        assert await redis.hgetall(key) == {"deleted": "1"}
    finally:
        archive._fetch_session = original
        await value.close()

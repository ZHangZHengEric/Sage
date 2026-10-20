import asyncio
import json
import os
import uuid

import fakeredis.aioredis
import pytest

from sagents.v2.contracts.events import RunEventData
from sagents.v2.contracts.commands import InputItem
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.run_state import RunState
from sagents.v2.runtime.session.contracts import EventDraft
from sagents.v2.runtime.session.plugins.mysql.archive import MysqlSessionArchive
from sagents.v2.runtime.session.plugins.mysql.state import _SCHEMA_TABLES, parse_mysql_dsn
from sagents.v2.runtime.session.plugins.mysql.redis import RedisMysqlSessionStore
from tests.sagents.v2.test_mysql_session_store_matrix import CONTEXT, command, mysql_dsn as mysql_dsn
from tests.sagents.v2.test_redis_mysql_session_store import store, transition


@pytest.fixture
async def mysql_archive(mysql_dsn):
    prefix = f"sage_v2_{uuid.uuid4().hex[:12]}"
    archive = MysqlSessionArchive(mysql_dsn, table_prefix=prefix)
    try:
        yield archive
    finally:
        await archive.close()
        import aiomysql
        connection = await aiomysql.connect(**parse_mysql_dsn(mysql_dsn))
        try:
            async with connection.cursor() as cursor:
                for name in reversed(_SCHEMA_TABLES):
                    await cursor.execute(f"DROP TABLE IF EXISTS {archive._table(name)}")
            await connection.commit()
        finally:
            connection.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", ["rows", "bytes"])
async def test_incremental_archive_retries_after_a_committed_prefix_without_duplicate_events(mysql_archive, limit):
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    value = store(redis, mysql_archive)
    created = await value.create_run(command(), CONTEXT)
    sid, rid = created.handle.session_id, created.handle.run_id
    original = mysql_archive.archive_batch
    batches = []
    failed = False
    try:
        for number in range(5):
            current = await value.get_run(rid)
            await value.commit_run(run_id=rid, expected_revision=current.revision,
                expected_states={current.state}, new_state=RunState.RUNNING,
                drafts=(EventDraft(type="run.started", data=RunEventData(state="running")),),
                context=CONTEXT, idempotency_key=f"step:{number}")
        await transition(value, created, RunState.CANCELLED, "cancel")
        expected = await value.export_session_state(sid)
        fields = await redis.hgetall(value._session_key(sid))
        sizes = [len(encoded.encode("utf-8")) for key, encoded in fields.items() if key.startswith("d:")]
        value.archive_batch_rows = 2 if limit == "rows" else 32
        value.archive_batch_bytes = 1024 * 1024 if limit == "rows" else max(sizes) + 1

        async def fail_second_batch(session_id, mutations):
            nonlocal failed
            rows = list(mutations)
            batches.append(rows)
            if len(batches) == 2 and not failed:
                failed = True
                raise OSError("second archive batch unavailable")
            return await original(session_id, rows)

        mysql_archive.archive_batch = fail_second_batch
        await value.archive_pending()

        assert failed
        assert await mysql_archive.revision(sid) == batches[0][-1][0]
        assert await redis.sismember(value._key("pending"), sid)
        committed_prefix = await mysql_archive._fetch_session(sid)
        assert committed_prefix["sessions"][0]["revision"] < expected["sessions"][0]["revision"]

        await value.archive_pending()

        assert not await redis.sismember(value._key("pending"), sid)
        actual = await mysql_archive._fetch_session(sid)
        actual.pop("_mutation_count")
        assert actual == expected
        assert len(batches) >= 3
        for batch in batches:
            assert len(batch) <= value.archive_batch_rows
            byte_count = sum(len(encoded.encode("utf-8")) for _, encoded in batch)
            assert byte_count <= value.archive_batch_bytes or len(batch) == 1
        async with mysql_archive._reader_connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(f"SELECT COUNT(*), COUNT(DISTINCT run_sequence) "
                    f"FROM {mysql_archive._table('run_events')} WHERE session_id = %s AND run_id = %s", (sid, rid))
                total, distinct = await cursor.fetchone()
        assert total == distinct == len(expected["run_events"][rid])
    finally:
        mysql_archive.archive_batch = original
        await value.close()


@pytest.mark.asyncio
async def test_cold_suspended_filter_uses_latest_delta_without_installing_history(mysql_archive, mysql_dsn):
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    value = store(redis, mysql_archive)
    cold_archive = MysqlSessionArchive(mysql_dsn, table_prefix=mysql_archive.table_prefix)
    cold = store(fakeredis.aioredis.FakeRedis(decode_responses=True), cold_archive)
    try:
        created = await value.create_run(command(), CONTEXT)
        sid = created.handle.session_id
        await transition(value, created, RunState.SUSPENDED, "suspended")
        suspended_base = await value.export_session_state(sid)
        await mysql_archive.archive_session(suspended_base, {})
        assert await cold.filter_suspended_session_ids([sid]) == {sid}

        await transition(value, created, RunState.COMPLETED, "complete")
        await value.archive_pending()

        async with mysql_archive._reader_connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(f"SELECT compact_state FROM {mysql_archive._table('sessions')} WHERE session_id = %s", (sid,))
                compact, = await cursor.fetchone()
                await cursor.execute(f"SELECT COUNT(*) FROM {mysql_archive._table('session_mutations')} WHERE session_id = %s", (sid,))
                mutation_count, = await cursor.fetchone()
        assert json.loads(compact)["runs"][0]["state"] == "suspended"
        assert mutation_count == 1

        async def reject_history_load(*args, **kwargs):
            raise AssertionError("Candidate filtering must not load full Session history")

        cold_archive._fetch_session = reject_history_load
        cold._ensure_session_loaded = reject_history_load
        assert await cold.filter_suspended_session_ids([sid, "missing_session"]) == set()
        assert not cold._sessions
        assert not cold_archive._sessions
    finally:
        await cold.close()
        await value.close()


@pytest.fixture
def live_redis_url():
    url = os.environ.get("SAGE_V2_TEST_REDIS_URL", "").strip()
    if not url:
        pytest.skip("set SAGE_V2_TEST_REDIS_URL to run live Redis and MySQL tests")
    return url


@pytest.mark.asyncio
async def test_live_chunked_snapshot_survives_hot_and_cold_reopen_and_active_run_persists_chunks(
    live_redis_url, mysql_archive, mysql_dsn,
):
    from redis.asyncio import Redis

    key_prefix = f"sage:test:{{{mysql_archive.table_prefix}}}"
    monitor = Redis.from_url(live_redis_url, decode_responses=True)
    opened = []

    def reopen():
        value = RedisMysqlSessionStore(mysql_dsn, redis_url=live_redis_url,
            table_prefix=mysql_archive.table_prefix, key_prefix=key_prefix,
            archive_interval_seconds=0.05, retention_seconds=60)
        value.snapshot_interval = 2
        opened.append(value)
        return value

    try:
        first = reopen()
        start = command().model_copy(update={"input": (
            InputItem(role="user", content=(TextBlock(text="large snapshot " * 2000),)),
        )})
        created = await first.create_run(start, CONTEXT)
        sid = created.handle.session_id
        header_key = first._session_key(sid)
        assert await monitor.hget(header_key, "base_snapshot") is None
        await transition(first, created, RunState.RUNNING, "running")
        await transition(first, created, RunState.CANCELLED, "cancel")

        # Exercise the real background worker, including staging and publication.
        async with asyncio.timeout(10):
            while True:
                fields = await monitor.hgetall(header_key)
                if (fields.get("base_snapshot") and fields.get("archived_revision") == fields.get("revision")
                    and await monitor.ttl(header_key) > 0):
                    break
                await asyncio.sleep(0.02)
        assert int(fields["base_parts"]) > 1
        token = fields["base_snapshot"]
        snapshot_key = first._key(f"snapshot:{token}")
        assert await monitor.hlen(snapshot_key) == int(fields["base_parts"])
        assert await monitor.ttl(snapshot_key) > 0
        expected = await first.export_session_state(sid)
        await first.close()

        hot = reopen()
        assert await hot.export_session_state(sid) == expected
        assert await monitor.ttl(snapshot_key) > 0
        await hot.close()

        # Evict this session's archived cache to exercise MySQL restoration.
        await monitor.delete(header_key, snapshot_key)
        cold = reopen()
        assert await cold.export_session_state(sid) == expected
        restored = await monitor.hgetall(header_key)
        restored_key = cold._key(f"snapshot:{restored['base_snapshot']}")
        assert await monitor.ttl(restored_key) > 0

        following = await cold.create_run(command("following").model_copy(update={"session_id": sid}), CONTEXT)
        await transition(cold, following, RunState.RUNNING, "following-running")
        assert await monitor.ttl(header_key) == -1
        assert await monitor.ttl(restored_key) == -1
        assert (await cold.get_run(following.handle.run_id)).state == RunState.RUNNING
    finally:
        for value in opened:
            await value.close()
        keys = [key async for key in monitor.scan_iter(match=f"{key_prefix}:*")]
        if keys:
            await monitor.delete(*keys)
        await monitor.aclose()

"""Shared Redis storage must settle guard cleanup before cancellation escapes."""

import asyncio

import fakeredis.aioredis
import pytest

from sagents.v2.runtime.distributed.redis_coordination import RedisGuard


async def test_repeated_cancellation_does_not_leave_a_live_session_guard():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original = redis.pipeline

    def pipeline(*args, **kwargs):
        pipe = original(*args, **kwargs)
        original_execute = pipe.execute

        async def execute(*args, **kwargs):
            cleaning.set()
            await release.wait()
            return await original_execute(*args, **kwargs)

        pipe.execute = execute
        return pipe

    redis.pipeline = pipeline

    async def operation():
        async with RedisGuard(redis, "guard", ttl_seconds=30):
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(operation())
    await entered.wait()
    task.cancel()
    await cleaning.wait()
    task.cancel()
    await asyncio.sleep(0)
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not await redis.exists("guard")
    await redis.aclose()


async def test_guard_release_retries_watch_race_and_never_deletes_a_successor():
    from redis.exceptions import WatchError

    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    original = redis.pipeline
    raced = False

    def pipeline(*args, **kwargs):
        pipe = original(*args, **kwargs)
        original_execute = pipe.execute

        async def execute(*args, **kwargs):
            nonlocal raced
            if not raced:
                raced = True
                raise WatchError("TTL renewal raced with release")
            return await original_execute(*args, **kwargs)

        pipe.execute = execute
        return pipe

    async with RedisGuard(redis, "guard", ttl_seconds=30):
        redis.pipeline = pipeline
    assert raced
    assert not await redis.exists("guard")
    async with RedisGuard(redis, "guard", ttl_seconds=30):
        await redis.set("guard", "successor")
    assert await redis.get("guard") == "successor"
    await redis.aclose()

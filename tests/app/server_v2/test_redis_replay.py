from __future__ import annotations

import json

import pytest

from app.server_v2.agui.redis_store import RedisAguiReplayStore
from app.server_v2.core.errors import ServerV2Error
from tests.app.server_v2.conftest import make_test_service


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}
        self.streams: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self.expirations: dict[str, int] = {}
        self.eval_calls = 0

    def key(self, *parts: str) -> str:
        return ":".join(("sage-server", *parts))

    async def get_json(self, key: str, *, default=None):
        return self.values.get(key, default)

    async def set_json(
        self,
        key: str,
        value,
        *,
        expires_seconds: int | None = None,
        only_if_absent: bool = False,
    ) -> bool:
        if only_if_absent and key in self.values:
            return False
        self.values[key] = value
        if expires_seconds is not None:
            self.expirations[key] = expires_seconds
        return True

    async def expire(self, key: str, seconds: int) -> bool:
        self.expirations[key] = seconds
        return True

    async def stream_add(
        self, key: str, fields: dict[str, str], *, max_length: int | None = None
    ) -> str:
        stream = self.streams.setdefault(key, [])
        event_id = f"{len(stream) + 1}-0"
        stream.append((event_id, fields))
        if max_length is not None and len(stream) > max_length:
            del stream[:-max_length]
        return event_id

    async def eval(self, script: str, numkeys: int, *args):
        self.eval_calls += 1
        assert numkeys == 2
        run_key, stream_key, payload, max_length, ttl_seconds = args
        event_id = await self.stream_add(
            stream_key,
            {"payload": payload},
            max_length=int(max_length),
        )
        await self.expire(run_key, int(ttl_seconds))
        await self.expire(stream_key, int(ttl_seconds))
        return event_id

    async def stream_read(self, streams: dict[str, str], *, count=None, block_milliseconds=None):
        key, cursor = next(iter(streams.items()))
        entries = [
            entry
            for entry in self.streams.get(key, [])
            if _stream_id_after(entry[0], cursor)
        ]
        if count is not None:
            entries = entries[:count]
        return [(key, entries)] if entries else []


def _stream_id_after(value: str, cursor: str) -> bool:
    return tuple(map(int, value.split("-"))) > tuple(map(int, cursor.split("-")))


def _parse_sse(chunks: list[str]) -> list[dict]:
    events: list[dict] = []
    for chunk in chunks:
        if not chunk.startswith("id: "):
            continue
        events.append(json.loads(chunk.split("data: ", 1)[1]))
    return events


async def test_claim_is_idempotent_per_user_and_conflicts_on_thread() -> None:
    store = RedisAguiReplayStore(FakeRedis())
    first = await store.claim(user_id="user-1", thread_id="thread-1", run_id="run-1")
    repeated = await store.claim(user_id="user-1", thread_id="thread-1", run_id="run-1")
    other_user = await store.claim(user_id="user-2", thread_id="thread-1", run_id="run-1")

    assert first.created is True
    assert repeated.created is False
    assert repeated.run.run_id == first.run.run_id == "run-1"
    assert other_user.created is True
    with pytest.raises(ServerV2Error) as exc_info:
        await store.claim(user_id="user-1", thread_id="thread-2", run_id="run-1")
    assert exc_info.value.status_code == 409


async def test_subscribe_replays_after_cursor_and_stops_at_terminal() -> None:
    store = RedisAguiReplayStore(FakeRedis(), heartbeat_seconds=0.01)
    claim = await store.claim(user_id="user-1", thread_id="thread-1", run_id="run-1")
    first_id = await store.publish(
        claim.run, {"type": "RUN_STARTED", "threadId": "thread-1", "runId": "run-1"}
    )
    await store.publish(
        claim.run, {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m1", "delta": "hello"}
    )
    await store.publish(
        claim.run, {"type": "RUN_FINISHED", "threadId": "thread-1", "runId": "run-1"}
    )
    await store.finish(claim.run, "completed")

    chunks = [chunk async for chunk in store.subscribe(claim.run, last_event_id=first_id)]
    events = _parse_sse(chunks)
    assert [event["type"] for event in events] == [
        "TEXT_MESSAGE_CONTENT",
        "RUN_FINISHED",
    ]
    assert chunks[0].startswith("id: 2-0\ndata:")


async def test_publish_appends_event_and_refreshes_ttls_in_one_redis_call() -> None:
    redis = FakeRedis()
    store = RedisAguiReplayStore(redis, ttl_seconds=60)
    claim = await store.claim(user_id="user-1", thread_id="thread-1", run_id="run-1")

    event_id = await store.publish(
        claim.run, {"type": "TEXT_MESSAGE_CONTENT", "delta": "hello"}
    )

    assert event_id == "1-0"
    assert redis.eval_calls == 1
    assert set(redis.expirations.values()) == {60}


def test_service_uses_redis_replay_when_client_injected(tmp_path) -> None:
    redis = FakeRedis()
    service = make_test_service(
        tmp_path, redis=redis, redis_url="redis://127.0.0.1:6379/0"
    )
    assert isinstance(service.replay, RedisAguiReplayStore)

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from typing import Any

from app.server_v2.agui.replay import AguiRun, AguiRunClaim, RunStatus
from app.server_v2.agui.sse import format_sse
from app.server_v2.core.errors import ServerV2Error

_PUBLISH_EVENT_SCRIPT = """
local event_id = redis.call(
    'XADD', KEYS[2], 'MAXLEN', '~', ARGV[2], '*', 'payload', ARGV[1]
)
redis.call('EXPIRE', KEYS[1], ARGV[3])
redis.call('EXPIRE', KEYS[2], ARGV[3])
return event_id
"""
_TERMINAL_EVENT_TYPES = frozenset({"RUN_FINISHED", "RUN_ERROR"})
_TERMINAL_STATUSES = frozenset({"completed", "failed", "stopped"})


class RedisAguiReplayStore:
    """Redis-backed AG-UI idempotency and SSE replay, same contract as AguiReplayStore."""

    def __init__(
        self,
        redis,
        *,
        ttl_seconds: int = 24 * 60 * 60,
        stream_max_length: int = 2_000,
        heartbeat_seconds: float = 20.0,
    ) -> None:
        self._redis = redis
        self._ttl_seconds = int(ttl_seconds)
        self._stream_max_length = stream_max_length
        self._heartbeat_seconds = heartbeat_seconds

    async def claim(
        self, *, user_id: str, thread_id: str, run_id: str
    ) -> AguiRunClaim:
        run_key = self._run_key(user_id, run_id)
        stored = await self._redis.get_json(run_key)
        if stored is not None:
            run = self._decode_run(stored)
            if run.thread_id != thread_id:
                raise ServerV2Error(
                    "conflict",
                    "runId conflicts with an existing AG-UI thread",
                    detail="run idempotency conflict",
                )
            await self._touch(run)
            return AguiRunClaim(run=run, created=False)

        candidate = AguiRun(run_id=run_id, user_id=user_id, thread_id=thread_id)
        created = await self._redis.set_json(
            run_key,
            _run_payload(candidate),
            expires_seconds=self._ttl_seconds,
            only_if_absent=True,
        )
        if created:
            return AguiRunClaim(run=candidate, created=True)
        return await self.claim(user_id=user_id, thread_id=thread_id, run_id=run_id)

    async def publish(self, run: AguiRun, payload: dict[str, Any]) -> str:
        event_id = await self._redis.eval(
            _PUBLISH_EVENT_SCRIPT,
            2,
            self._run_key(run.user_id, run.run_id),
            self._stream_key(run.user_id, run.run_id),
            json.dumps(payload, ensure_ascii=False),
            self._stream_max_length,
            self._ttl_seconds,
        )
        return event_id.decode() if isinstance(event_id, bytes) else str(event_id)

    async def finish(self, run: AguiRun, status: RunStatus) -> None:
        if status not in _TERMINAL_STATUSES:
            raise ValueError(f"unsupported status {status}")
        await self._save_run(
            AguiRun(
                run_id=run.run_id,
                user_id=run.user_id,
                thread_id=run.thread_id,
                status=status,
            )
        )
        await self._touch(run)

    async def subscribe(
        self, run: AguiRun, *, last_event_id: str | None
    ) -> AsyncIterator[str]:
        cursor = _stream_cursor(last_event_id)
        stream_key = self._stream_key(run.user_id, run.run_id)
        while True:
            response = await self._redis.stream_read(
                {stream_key: cursor},
                count=100,
                block_milliseconds=int(self._heartbeat_seconds * 1000),
            )
            entries = _entries(response)
            if entries:
                for event_id, fields in entries:
                    cursor = str(event_id)
                    payload = _decode_payload(fields)
                    yield format_sse(cursor, payload)
                    if payload.get("type") in _TERMINAL_EVENT_TYPES:
                        return
                continue
            current = await self._load_run(run.user_id, run.run_id)
            if current is None or current.thread_id != run.thread_id:
                raise ServerV2Error("not_found", "run not found")
            if current.status in _TERMINAL_STATUSES:
                return
            yield ": heartbeat\n\n"

    async def _save_run(self, run: AguiRun) -> None:
        await self._redis.set_json(
            self._run_key(run.user_id, run.run_id),
            _run_payload(run),
            expires_seconds=self._ttl_seconds,
        )

    async def _touch(self, run: AguiRun) -> None:
        await self._redis.expire(
            self._run_key(run.user_id, run.run_id), self._ttl_seconds
        )
        await self._redis.expire(
            self._stream_key(run.user_id, run.run_id), self._ttl_seconds
        )

    async def _load_run(self, user_id: str, run_id: str) -> AguiRun | None:
        stored = await self._redis.get_json(self._run_key(user_id, run_id))
        return None if stored is None else self._decode_run(stored)

    def _run_key(self, user_id: str, run_id: str) -> str:
        return self._redis.key("chat", "run", _digest(user_id, run_id))

    def _stream_key(self, user_id: str, run_id: str) -> str:
        return self._redis.key("chat", "events", _digest(user_id, run_id))

    @staticmethod
    def _decode_run(value: Any) -> AguiRun:
        if not isinstance(value, dict):
            raise ServerV2Error("not_found", "run not found")
        try:
            return AguiRun(
                run_id=str(value["run_id"]),
                user_id=str(value["user_id"]),
                thread_id=str(value["thread_id"]),
                status=str(value.get("status") or "running"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ServerV2Error("not_found", "run not found") from exc


def _run_payload(run: AguiRun) -> dict[str, str]:
    return {
        "run_id": run.run_id,
        "user_id": run.user_id,
        "thread_id": run.thread_id,
        "status": run.status,
    }


def _digest(user_id: str, run_id: str) -> str:
    return hashlib.sha256(f"{user_id}\0{run_id}".encode()).hexdigest()


def _stream_cursor(value: str | None) -> str:
    cursor = (value or "0-0").strip() or "0-0"
    if cursor == "0":
        return "0-0"
    return cursor


def _entries(response: Any) -> list[tuple[str, dict[str, str]]]:
    result: list[tuple[str, dict[str, str]]] = []
    for _, entries in response or []:
        result.extend((str(event_id), fields) for event_id, fields in entries)
    return result


def _decode_payload(fields: dict[str, Any]) -> dict[str, Any]:
    raw = fields.get("payload")
    if isinstance(raw, bytes):
        raw = raw.decode()
    if not isinstance(raw, str):
        raise ValueError("chat event payload is missing")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("chat event payload must be an object")
    return payload

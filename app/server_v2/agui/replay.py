from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from app.server_v2.agui.sse import format_sse
from app.server_v2.core.errors import ServerV2Error

RunStatus = Literal["running", "completed", "failed", "stopped"]
_TERMINAL_EVENT_TYPES = frozenset({"RUN_FINISHED", "RUN_ERROR"})
_TERMINAL_STATUSES = frozenset({"completed", "failed", "stopped"})


@dataclass(frozen=True, slots=True)
class StoredEvent:
    sequence: int
    payload: dict[str, Any]

    @property
    def event_id(self) -> str:
        return f"{self.sequence}-0"


@dataclass(slots=True)
class AguiRun:
    run_id: str
    user_id: str
    thread_id: str
    status: RunStatus = "running"
    updated_at: float = field(default_factory=time.monotonic)
    next_sequence: int = 1
    events: list[StoredEvent] = field(default_factory=list)
    subscribers: set[asyncio.Queue[StoredEvent | None]] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class AguiRunClaim:
    run: AguiRun
    created: bool


class ReplayStore(Protocol):
    async def claim(
        self, *, user_id: str, thread_id: str, run_id: str
    ) -> AguiRunClaim: ...

    async def publish(self, run: AguiRun, payload: dict[str, Any]) -> Any: ...

    async def finish(self, run: AguiRun, status: RunStatus) -> None: ...

    def subscribe(
        self, run: AguiRun, *, last_event_id: str | None
    ) -> AsyncIterator[str]: ...


class AguiReplayStore:
    def __init__(
        self,
        *,
        ttl_seconds: float = 24 * 60 * 60,
        heartbeat_seconds: float = 20.0,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._heartbeat_seconds = heartbeat_seconds
        self._runs: dict[tuple[str, str], AguiRun] = {}
        self._lock = asyncio.Lock()

    async def claim(
        self, *, user_id: str, thread_id: str, run_id: str
    ) -> AguiRunClaim:
        async with self._lock:
            self._gc_locked()
            existing = self._runs.get((user_id, run_id))
            if existing is None:
                run = AguiRun(run_id=run_id, user_id=user_id, thread_id=thread_id)
                self._runs[(user_id, run_id)] = run
                return AguiRunClaim(run=run, created=True)
            if existing.thread_id != thread_id:
                raise ServerV2Error(
                    "conflict",
                    "runId conflicts with an existing AG-UI thread",
                    detail="run idempotency conflict",
                )
            existing.updated_at = time.monotonic()
            return AguiRunClaim(run=existing, created=False)

    async def publish(self, run: AguiRun, payload: dict[str, Any]) -> StoredEvent:
        async with self._lock:
            self._require(run)
            event = StoredEvent(sequence=run.next_sequence, payload=payload)
            run.next_sequence += 1
            run.events.append(event)
            run.updated_at = time.monotonic()
            subscribers = tuple(run.subscribers)
        for queue in subscribers:
            queue.put_nowait(event)
        return event

    async def finish(self, run: AguiRun, status: RunStatus) -> None:
        if status not in _TERMINAL_STATUSES:
            raise ValueError(f"unsupported status {status}")
        async with self._lock:
            self._require(run)
            run.status = status
            run.updated_at = time.monotonic()
            subscribers = tuple(run.subscribers)
        for queue in subscribers:
            queue.put_nowait(None)

    async def subscribe(
        self, run: AguiRun, *, last_event_id: str | None
    ) -> AsyncIterator[str]:
        cursor = _parse_event_id(last_event_id)
        queue: asyncio.Queue[StoredEvent | None] = asyncio.Queue()
        async with self._lock:
            self._require(run)
            replay = [event for event in run.events if event.sequence > cursor]
            terminal = run.status in _TERMINAL_STATUSES
            if not terminal:
                run.subscribers.add(queue)
            run.updated_at = time.monotonic()
        try:
            for event in replay:
                yield format_sse(event.event_id, event.payload)
                if event.payload.get("type") in _TERMINAL_EVENT_TYPES:
                    return
            if terminal:
                return
            while True:
                try:
                    event = await asyncio.wait_for(
                        queue.get(), timeout=self._heartbeat_seconds
                    )
                except TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                if event is None:
                    return
                yield format_sse(event.event_id, event.payload)
                if event.payload.get("type") in _TERMINAL_EVENT_TYPES:
                    return
        finally:
            async with self._lock:
                run.subscribers.discard(queue)

    def _require(self, run: AguiRun) -> None:
        if self._runs.get((run.user_id, run.run_id)) is not run:
            raise ServerV2Error("not_found", "run not found")

    def _gc_locked(self) -> None:
        cutoff = time.monotonic() - self._ttl_seconds
        expired = [
            key
            for key, run in self._runs.items()
            if run.updated_at < cutoff and not run.subscribers
        ]
        for key in expired:
            del self._runs[key]


def _parse_event_id(value: str | None) -> int:
    candidate = (value or "0").strip()
    if not candidate:
        return 0
    head = candidate.split("-", 1)[0]
    try:
        return max(int(head), 0)
    except ValueError:
        return 0

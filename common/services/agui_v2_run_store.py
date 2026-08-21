"""Process-local delivery buffer for the Sage AG-UI V2 endpoint.

This is deliberately not business storage. Conversation messages remain owned by
Sage's existing session and conversation persistence. The buffer only supports
same-process SSE replay for a bounded time.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Literal, Mapping


RunStatus = Literal["running", "completed", "failed", "stopped"]
_TERMINAL_EVENT_TYPES = frozenset({"RUN_FINISHED", "RUN_ERROR"})
_TERMINAL_STATUSES = frozenset({"completed", "failed", "stopped"})
_MAX_ID_LENGTH = 256


class AguiRunConflict(RuntimeError):
    pass


class AguiRunNotFound(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class AguiStoredEvent:
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
    events: list[AguiStoredEvent] = field(default_factory=list)
    subscribers: set[asyncio.Queue[AguiStoredEvent | None]] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class AguiRunClaim:
    run: AguiRun
    created: bool


class AguiV2RunStore:
    """Bounded same-process idempotency and replay buffer."""

    def __init__(
        self,
        *,
        ttl_seconds: float = 24 * 60 * 60,
        max_events: int = 2_000,
        heartbeat_seconds: float = 20.0,
    ) -> None:
        self._ttl_seconds = max(float(ttl_seconds), 1.0)
        self._max_events = max(int(max_events), 1)
        self._heartbeat_seconds = max(float(heartbeat_seconds), 0.01)
        self._runs: dict[tuple[str, str], AguiRun] = {}
        self._lock = asyncio.Lock()

    async def claim_run(
        self,
        *,
        user_id: str,
        thread_id: str,
        run_id: str,
    ) -> AguiRunClaim:
        normalized_user_id = user_id.strip()
        normalized_thread_id = thread_id.strip()
        normalized_run_id = run_id.strip()
        if (
            not normalized_user_id
            or not normalized_thread_id
            or not normalized_run_id
            or len(normalized_thread_id) > _MAX_ID_LENGTH
            or len(normalized_run_id) > _MAX_ID_LENGTH
        ):
            raise ValueError("user_id, thread_id and run_id are required")

        async with self._lock:
            self._gc_locked()
            key = (normalized_user_id, normalized_run_id)
            run = self._runs.get(key)
            if run is not None:
                if run.thread_id != normalized_thread_id:
                    raise AguiRunConflict(
                        "runId is already bound to another AG-UI thread"
                    )
                run.updated_at = time.monotonic()
                return AguiRunClaim(run=run, created=False)

            run = AguiRun(
                run_id=normalized_run_id,
                user_id=normalized_user_id,
                thread_id=normalized_thread_id,
            )
            self._runs[key] = run
            return AguiRunClaim(run=run, created=True)

    async def require_run(
        self,
        *,
        user_id: str,
        thread_id: str,
        run_id: str,
    ) -> AguiRun:
        async with self._lock:
            self._gc_locked()
            run = self._runs.get((user_id.strip(), run_id.strip()))
            if run is None or run.thread_id != thread_id.strip():
                raise AguiRunNotFound(run_id)
            run.updated_at = time.monotonic()
            return run

    async def publish(
        self,
        run: AguiRun,
        event: Mapping[str, Any],
    ) -> str:
        payload = dict(event)
        async with self._lock:
            self._require_identity_locked(run)
            stored = AguiStoredEvent(sequence=run.next_sequence, payload=payload)
            run.next_sequence += 1
            run.events.append(stored)
            if len(run.events) > self._max_events:
                del run.events[: len(run.events) - self._max_events]
            run.updated_at = time.monotonic()
            subscribers = tuple(run.subscribers)

        for queue in subscribers:
            queue.put_nowait(stored)
        return stored.event_id

    async def finish(self, run: AguiRun, *, status: RunStatus) -> None:
        if status not in _TERMINAL_STATUSES:
            raise ValueError(f"Unsupported terminal AG-UI run status: {status}")
        async with self._lock:
            self._require_identity_locked(run)
            run.status = status
            run.updated_at = time.monotonic()
            subscribers = tuple(run.subscribers)
        for queue in subscribers:
            queue.put_nowait(None)

    async def list_events(self, run: AguiRun) -> list[AguiStoredEvent]:
        async with self._lock:
            self._require_identity_locked(run)
            return list(run.events)

    async def subscribe(
        self,
        run: AguiRun,
        *,
        last_event_id: str | None,
    ) -> AsyncIterator[str]:
        cursor = _parse_event_id(last_event_id)
        queue: asyncio.Queue[AguiStoredEvent | None] = asyncio.Queue()
        async with self._lock:
            self._require_identity_locked(run)
            replay = [event for event in run.events if event.sequence > cursor]
            terminal = run.status in _TERMINAL_STATUSES
            if not terminal:
                run.subscribers.add(queue)
            run.updated_at = time.monotonic()

        try:
            for event in replay:
                yield _format_sse(event)
                if _is_terminal_event(event):
                    return
            if terminal:
                return

            while True:
                try:
                    event = await asyncio.wait_for(
                        queue.get(),
                        timeout=self._heartbeat_seconds,
                    )
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                if event is None:
                    return
                yield _format_sse(event)
                if _is_terminal_event(event):
                    return
        finally:
            async with self._lock:
                run.subscribers.discard(queue)

    def _require_identity_locked(self, run: AguiRun) -> None:
        if self._runs.get((run.user_id, run.run_id)) is not run:
            raise AguiRunNotFound(run.run_id)

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


def _format_sse(event: AguiStoredEvent) -> str:
    payload = json.dumps(event.payload, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event.event_id}\ndata: {payload}\n\n"


def _is_terminal_event(event: AguiStoredEvent) -> bool:
    return str(event.payload.get("type") or "") in _TERMINAL_EVENT_TYPES


_RUN_STORE: AguiV2RunStore | None = None


def get_agui_v2_run_store() -> AguiV2RunStore:
    global _RUN_STORE
    if _RUN_STORE is None:
        _RUN_STORE = AguiV2RunStore()
    return _RUN_STORE


__all__ = [
    "AguiRun",
    "AguiRunClaim",
    "AguiRunConflict",
    "AguiRunNotFound",
    "AguiStoredEvent",
    "AguiV2RunStore",
    "get_agui_v2_run_store",
]

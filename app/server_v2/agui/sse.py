from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from sagents.v2.contracts.events import RuntimeEvent
from sagents.v2.interfaces.protocols.ag_ui import AgUiProtocolAdapter
from sagents.v2.interfaces.protocols.contracts import ProtocolFrame

_RUN_ID_EVENTS = {"RUN_STARTED", "RUN_FINISHED"}
_TEXT_MESSAGE_EVENTS = {
    "TEXT_MESSAGE_START",
    "TEXT_MESSAGE_CONTENT",
    "TEXT_MESSAGE_END",
}


def frame_to_agui_event(
    frame: ProtocolFrame,
    *,
    thread_id: str,
    run_id: str,
) -> dict[str, Any]:
    payload = dict(frame.payload)
    if frame.name in _RUN_ID_EVENTS:
        payload["threadId"] = thread_id
        payload["runId"] = run_id
    return {"type": frame.name, **payload}


def format_sse(event_id: str, payload: dict[str, Any]) -> str:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event_id}\ndata: {body}\n\n"


def run_error_event(message: str, *, code: str | None = None) -> dict[str, Any]:
    event: dict[str, Any] = {"type": "RUN_ERROR", "message": message}
    if code:
        event["code"] = code
    return event


@dataclass(frozen=True, order=True, slots=True)
class CanonicalSseCursor:
    """Position of one AG-UI frame inside one canonical RuntimeEvent."""

    run_sequence: int = 0
    frame_index: int = -1

    def encode(self) -> str:
        return f"v1:{self.run_sequence}:{self.frame_index}"

    @classmethod
    def parse(cls, value: str | None) -> "CanonicalSseCursor":
        parts = (value or "").strip().split(":")
        if len(parts) != 3 or parts[0] != "v1":
            return cls()
        try:
            run_sequence = int(parts[1])
            frame_index = int(parts[2])
        except ValueError:
            return cls()
        if run_sequence < 1 or frame_index < 0:
            return cls()
        return cls(run_sequence=run_sequence, frame_index=frame_index)


async def canonical_agui_sse(
    events: AsyncIterator[RuntimeEvent],
    *,
    thread_id: str,
    run_id: str,
    last_event_id: str | None,
    heartbeat_seconds: float = 20.0,
) -> AsyncIterator[str]:
    """Project one canonical Run log into a resumable AG-UI SSE stream.

    Replaying from the beginning is intentional: the AG-UI adapter has small
    item-lifecycle state, so rebuilding it makes a cursor inside a multi-frame
    RuntimeEvent exact without introducing a second persisted projection log.
    """

    cursor = CanonicalSseCursor.parse(last_event_id)
    adapter = AgUiProtocolAdapter(enable_sage_extensions=True)
    owned_user_text = ClientOwnedUserTextFilter()
    opened = False
    async for event in _events_with_heartbeats(
        events, heartbeat_seconds=heartbeat_seconds
    ):
        if event is None:
            yield ": heartbeat\n\n"
            continue
        result = adapter.translate(event)
        for frame_index, frame in enumerate(result.frames):
            payload = frame_to_agui_event(
                frame,
                thread_id=thread_id,
                run_id=run_id,
            )
            if not owned_user_text.allow(payload):
                continue
            kind = payload.get("type")
            if not opened:
                if kind == "RUN_STARTED":
                    opened = True
                elif kind == "RUN_ERROR":
                    opened = True
                else:
                    # AG-UI requires its run lifecycle frame first. Native
                    # accepted/queued/input facts remain in the canonical log.
                    continue
            position = CanonicalSseCursor(event.run_sequence, frame_index)
            if position <= cursor:
                continue
            yield format_sse(position.encode(), payload)
        if event.type in {
            "run.suspended",
            "run.completed",
            "run.failed",
            "run.cancelled",
        }:
            return


async def _events_with_heartbeats(
    events: AsyncIterator[RuntimeEvent], *, heartbeat_seconds: float
) -> AsyncIterator[RuntimeEvent | None]:
    iterator = events.__aiter__()
    pending = asyncio.create_task(anext(iterator))
    try:
        while True:
            done, _ = await asyncio.wait((pending,), timeout=heartbeat_seconds)
            if not done:
                yield None
                continue
            try:
                event = pending.result()
            except StopAsyncIteration:
                return
            yield event
            pending = asyncio.create_task(anext(iterator))
    finally:
        if not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        closer = getattr(iterator, "aclose", None)
        if closer is not None:
            await closer()


async def single_error_sse(message: str, *, code: str) -> AsyncIterator[str]:
    """Return a pre-acceptance error; it has no canonical Run cursor."""

    body = json.dumps(
        run_error_event(message, code=code),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    yield f"data: {body}\n\n"


class ClientOwnedUserTextFilter:
    """Drop inbound user TEXT_MESSAGE frames; the AG-UI client already has them."""

    def __init__(self) -> None:
        self._skip_ids: set[str] = set()

    def allow(self, event: dict[str, Any]) -> bool:
        kind = event.get("type")
        message_id = str(event.get("messageId") or "")
        if kind == "TEXT_MESSAGE_START" and event.get("role") == "user":
            if message_id:
                self._skip_ids.add(message_id)
            return False
        if kind in _TEXT_MESSAGE_EVENTS and message_id in self._skip_ids:
            return False
        return True

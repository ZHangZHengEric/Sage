from __future__ import annotations

import json
from typing import Any

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


class RunStartedGate:
    """Hold events until RUN_STARTED so @ag-ui/client can open the run."""

    def __init__(self) -> None:
        self._open = False
        self._held: list[dict[str, Any]] = []

    def release(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        kind = event.get("type")
        if kind == "RUN_STARTED":
            held, self._held = self._held, []
            self._open = True
            return [event, *held]
        if kind == "RUN_ERROR" and not self._open:
            self._held.clear()
            self._open = True
            return [event]
        if not self._open:
            self._held.append(event)
            return []
        return [event]

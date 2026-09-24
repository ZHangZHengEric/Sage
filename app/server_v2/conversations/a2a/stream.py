from __future__ import annotations

from collections.abc import AsyncIterator

from a2a.server.events.event_queue import Event
from a2a.types.a2a_pb2 import (
    TaskArtifactUpdateEvent,
    TaskStatusUpdateEvent,
)
from google.protobuf.json_format import ParseDict
from sagents.v2.contracts.events import RuntimeEvent
from sagents.v2.interfaces.protocols.a2a import A2AProtocolAdapter
from sagents.v2.interfaces.protocols.contracts import ProtocolFrame

from app.server_v2.conversations.a2a.task import TaskReducer, message_from

_TERMINAL = frozenset(
    {"run.completed", "run.failed", "run.cancelled", "run.suspended"}
)


async def task_stream(
    events: AsyncIterator[RuntimeEvent],
    *,
    task_id: str,
    context_id: str,
    resume_after: int = 0,
    resumed: bool = False,
    history_length: int = 0,
) -> AsyncIterator[Event]:
    """Project one canonical Run log into the A2A streaming event sequence.

    A2A opens a stream with a whole Task and continues with increments, so a
    client that joins late still starts from a complete picture. ``resume_after``
    is where "late" is decided: events at or below it are folded into the
    opening snapshot instead of being emitted, which is how ``SubscribeToTask``
    hands a reconnecting client the Task as it stands now rather than replaying
    a conversation it has already seen.

    The subscription is always read from sequence 0 even when resuming. Asking
    the store to skip ahead would be cheaper but would leave the opening Task
    empty, and A2A has no cursor of its own for the client to correct it with.

    ``resumed`` says this request is what put the Run back in flight. It matters
    because a Run that is waiting for input has already recorded the suspension
    that stopped it, and the replayed prefix therefore ends in an event that
    normally means "nothing more is coming". For a subscriber that is true and
    ends the stream; for the answer that just restarted the Run it is the pause
    this stream exists to continue past.
    """

    adapter = A2AProtocolAdapter()
    reducer = TaskReducer(task_id, context_id)
    opened = False
    async for event in events:
        frames = adapter.translate(event).frames
        replayed = event.preview_sequence is None and event.run_sequence <= resume_after
        if replayed:
            for frame in frames:
                reducer.push(frame)
        else:
            if not opened:
                opened = True
                yield reducer.build(history_length=history_length)
            for frame in frames:
                reducer.push(frame)
                increment = to_event(frame, task_id=task_id, context_id=context_id)
                if increment is not None:
                    yield increment
        if event.type in _TERMINAL and not (replayed and resumed):
            break
    if not opened:
        # Nothing new ever arrived: the Run was already over when the client
        # joined. The snapshot is still owed — it is the answer.
        yield reducer.build(history_length=history_length)


def to_event(
    frame: ProtocolFrame, *, task_id: str, context_id: str
) -> Event | None:
    """Turn one adapter frame into the proto event A2A streams it as."""

    payload = frame.payload
    if frame.name == "task/status-update":
        update = TaskStatusUpdateEvent(task_id=task_id, context_id=context_id)
        ParseDict(
            {"status": payload.get("status") or {}},
            update,
            ignore_unknown_fields=True,
        )
        _metadata(update, payload.get("metadata"))
        return update
    if frame.name == "task/artifact-update":
        update = TaskArtifactUpdateEvent(task_id=task_id, context_id=context_id)
        ParseDict(
            {
                "artifact": payload.get("artifact") or {},
                "append": bool(payload.get("append")),
                "lastChunk": bool(payload.get("lastChunk")),
            },
            update,
            ignore_unknown_fields=True,
        )
        return update
    if frame.name == "task/message":
        raw = payload.get("message")
        if not isinstance(raw, dict):
            return None
        if raw.get("role") == "ROLE_USER":
            # The caller wrote this message; echoing it back as progress would
            # tell it nothing. It still belongs in the Task's history, which the
            # reducer keeps regardless of what is streamed.
            return None
        return message_from(raw)
    return None


def _metadata(update: TaskStatusUpdateEvent, metadata: object) -> None:
    if not isinstance(metadata, dict):
        return
    for key, value in metadata.items():
        update.metadata[key] = value

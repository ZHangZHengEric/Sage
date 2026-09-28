from __future__ import annotations

from datetime import datetime

from a2a.types.a2a_pb2 import (
    Artifact,
    Message,
    Part,
    Role,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
)
from google.protobuf.json_format import ParseDict
from sagents.v2.interfaces.protocols.contracts import ProtocolFrame

_ROLE = {"ROLE_USER": Role.ROLE_USER, "ROLE_AGENT": Role.ROLE_AGENT}


class TaskReducer:
    """Fold A2A frames into the one Task snapshot a caller asked for.

    A2A is snapshot-oriented and the Sage event log is increment-oriented, so
    every read path — ``GetTask``, the terminal result of ``SendMessage``, the
    first frame of a subscription — funnels through this fold. Keeping it in
    one place is what stops the two surfaces from disagreeing about the same
    Run.

    Chunked working statuses (``sage.chunk``) advance the state but are not
    retained: the fold keeps the last non-chunk status so a completed Task does
    not report the text of its final token as its status message.
    """

    def __init__(self, task_id: str, context_id: str) -> None:
        self._task = Task(id=task_id, context_id=context_id)
        self._task.status.state = TaskState.TASK_STATE_SUBMITTED
        self._artifacts: dict[str, Artifact] = {}
        self._history: list[Message] = []

    def push(self, frame: ProtocolFrame) -> None:
        payload = frame.payload
        if frame.name == "task/status-update":
            self._status(payload)
        elif frame.name == "task/message":
            self._message(payload)
        elif frame.name == "task/artifact-update":
            self._artifact(payload)

    def build(self, *, history_length: int = 0) -> Task:
        task = Task()
        task.CopyFrom(self._task)
        del task.artifacts[:]
        task.artifacts.extend(self._artifacts.values())
        del task.history[:]
        history = self._history
        if history_length > 0:
            history = history[-history_length:]
        task.history.extend(history)
        return task

    def _status(self, payload: dict) -> None:
        raw = payload.get("status") or {}
        state = _state(raw.get("state"))
        chunk = bool((payload.get("metadata") or {}).get("sage.chunk"))
        status = TaskStatus(state=state)
        if not chunk and isinstance(raw.get("message"), dict):
            status.message.CopyFrom(message_from(raw["message"]))
        elif chunk:
            # Preserve whatever status message the last real transition set.
            if self._task.status.HasField("message"):
                status.message.CopyFrom(self._task.status.message)
        timestamp = raw.get("timestamp")
        if isinstance(timestamp, str) and timestamp:
            status.timestamp.FromDatetime(datetime.fromisoformat(timestamp))
        self._task.status.CopyFrom(status)
        for key, value in (payload.get("metadata") or {}).items():
            if key != "sage.chunk":
                self._task.metadata[key] = value

    def _message(self, payload: dict) -> None:
        raw = payload.get("message")
        if not isinstance(raw, dict):
            return
        self._history.append(message_from(raw))

    def _artifact(self, payload: dict) -> None:
        event = ParseDict(payload, TaskArtifactUpdateEvent(), ignore_unknown_fields=True)
        existing = self._artifacts.get(event.artifact.artifact_id)
        if existing is not None and event.append:
            existing.parts.extend(event.artifact.parts)
            return
        artifact = Artifact()
        artifact.CopyFrom(event.artifact)
        self._artifacts[artifact.artifact_id] = artifact


def _state(value: object) -> int:
    name = str(value or "")
    if name in TaskState.keys():
        return TaskState.Value(name)
    return TaskState.TASK_STATE_UNSPECIFIED


def message_from(raw: dict) -> Message:
    """Build a proto Message from the adapter's JSON shape.

    Parts are read field by field rather than with ``ParseDict`` because ``Part``
    is a oneof: a payload carrying both a text and a url would otherwise have
    one silently overwrite the other.
    """

    message = Message(
        message_id=str(raw.get("messageId") or ""),
        context_id=str(raw.get("contextId") or ""),
        task_id=str(raw.get("taskId") or ""),
        role=_ROLE.get(str(raw.get("role") or ""), Role.ROLE_UNSPECIFIED),
    )
    for part in raw.get("parts") or []:
        if not isinstance(part, dict):
            continue
        if part.get("text") is not None:
            message.parts.append(Part(text=str(part["text"])))
        elif part.get("url"):
            message.parts.append(
                Part(url=str(part["url"]), media_type=str(part.get("mediaType") or ""))
            )
    return message

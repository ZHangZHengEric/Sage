"""Project Native RuntimeEvents into the A2A Task/Message/Artifact model."""

from __future__ import annotations

from sagents.v2.contracts.events import (
    ArtifactEventData,
    InteractionEventData,
    ItemEventData,
    RunEventData,
    RuntimeEvent,
)
from sagents.v2.contracts.items import MessageItemData, TextBlock
from sagents.v2.interfaces.protocols.contracts import (
    AdapterCapabilities,
    AdapterResult,
    MappingFidelity,
    frame,
    loss,
)

# A2A 1.0 is a proto wire format, so its JSON uses the protobuf enum names.
# Emitting those names here means the transport layer maps frames onto proto
# messages field for field instead of maintaining a second vocabulary.
_RUN_STATE = {
    "run.queued": "TASK_STATE_SUBMITTED",
    "run.accepted": "TASK_STATE_SUBMITTED",
    "run.started": "TASK_STATE_WORKING",
    "run.resumed": "TASK_STATE_WORKING",
    "run.completed": "TASK_STATE_COMPLETED",
    "run.failed": "TASK_STATE_FAILED",
    "run.cancelled": "TASK_STATE_CANCELED",
    "run.suspended": "TASK_STATE_INPUT_REQUIRED",
}

_ROLE = {"user": "ROLE_USER", "assistant": "ROLE_AGENT"}


class A2AProtocolAdapter:
    """Task-oriented projection that explicitly loses Step/Tool/Flow detail."""

    plugin_id = "sage.protocol.a2a"
    name = "A2A protocol adapter"
    description = "Projects Sage events into A2A frames."
    protocol = "a2a"
    version = "1.0"

    async def capabilities(self):
        return AdapterCapabilities(
            protocol=self.protocol,
            protocol_version=self.version,
            adapter_version="sage-v2/1",
            supports_run_lifecycle=True,
            supports_item_lifecycle=False,
            supports_reasoning=False,
            supports_tool_lifecycle=False,
            supports_interactions=True,
            supports_pause_resume=False,
            supports_exact_cursor_replay=False,
            supports_flow=False,
            supports_artifacts=True,
        )

    def translate(self, event: RuntimeEvent) -> AdapterResult:
        """Translate one Native fact into an A2A frame or LossReport."""

        data = event.data
        if isinstance(data, RunEventData):
            return self._run(event, data)
        if (
            isinstance(data, InteractionEventData)
            and event.type == "interaction.requested"
        ):
            return self._interaction(event, data)
        if isinstance(data, ArtifactEventData):
            return self._artifact(event, data)
        if isinstance(data, ItemEventData):
            return self._item(event, data)
        return self._unsupported(event)

    def _run(self, event: RuntimeEvent, data: RunEventData) -> AdapterResult:
        state = _RUN_STATE.get(event.type)
        if state is None:
            return self._unsupported(event)
        failed = event.type == "run.failed" and data.error is not None
        text = data.error.message if failed else data.reason
        metadata: dict[str, object] = {}
        if failed and data.error is not None:
            # A2A has no error code on TaskStatus: the code survives as status
            # metadata rather than being dropped on the way out.
            metadata["sage.errorCode"] = data.error.code
        return AdapterResult(
            frames=(
                self._status(
                    event,
                    state=state,
                    text=text,
                    metadata=metadata,
                ),
            )
        )

    def _interaction(
        self, event: RuntimeEvent, data: InteractionEventData
    ) -> AdapterResult:
        """Surface an approval or question as the input-required state.

        The decision vocabulary has no A2A equivalent, so it travels as status
        metadata: a client that understands Sage can answer precisely, and one
        that does not still sees a Task waiting on input.
        """

        return AdapterResult(
            frames=(
                self._status(
                    event,
                    state="TASK_STATE_INPUT_REQUIRED",
                    text=str(data.payload.get("prompt") or "") or None,
                    metadata={
                        "sage.interactionId": data.interaction_id,
                        "sage.interactionType": data.interaction_type,
                        "sage.allowedDecisions": list(data.allowed_decisions),
                        "sage.interactionRevision": data.revision,
                        "sage.payload": data.payload,
                    },
                ),
            )
        )

    def _artifact(self, event: RuntimeEvent, data: ArtifactEventData) -> AdapterResult:
        if event.type == "artifact.deleted":
            return AdapterResult(
                losses=(
                    loss(
                        event,
                        fidelity=MappingFidelity.UNSUPPORTED,
                        code="a2a.artifact_delete",
                        detail="A2A artifacts are append-only and cannot be retracted",
                    ),
                )
            )
        return AdapterResult(
            frames=(
                frame(
                    event,
                    protocol=self.protocol,
                    version=self.version,
                    frame_kind="notification",
                    name="task/artifact-update",
                    payload={
                        "taskId": event.run_id,
                        "contextId": event.session_id,
                        "artifact": {
                            "artifactId": data.artifact.artifact_id,
                            "name": data.artifact.name,
                            "parts": [
                                {
                                    "url": data.artifact.uri,
                                    "mediaType": data.artifact.mime_type or "",
                                }
                            ],
                        },
                        # Each Sage artifact event carries the whole reference,
                        # so an update replaces rather than appends.
                        "append": False,
                        "lastChunk": event.type == "artifact.finalized",
                    },
                ),
            )
        )

    def _item(self, event: RuntimeEvent, data: ItemEventData) -> AdapterResult:
        if event.type == "message.delta":
            # A2A carries whole Messages, so streamed text rides on the working
            # status the way the protocol's own progress updates do. The final
            # Message still arrives on completion; only that one is history.
            return AdapterResult(
                frames=(
                    self._status(
                        event,
                        state="TASK_STATE_WORKING",
                        text=_delta_text(data.delta),
                        metadata={"sage.chunk": True, "sage.itemId": event.item_id},
                    ),
                )
            )
        if data.item is None or not isinstance(data.item.data, MessageItemData):
            return self._unsupported(event)
        if data.operation not in {"completed", "snapshot"}:
            return self._unsupported(event)
        message = data.item.data
        role = _ROLE.get(message.role)
        if role is None:
            return AdapterResult(
                losses=(
                    loss(
                        event,
                        fidelity=MappingFidelity.LOSSY,
                        code="a2a.internal_message",
                        detail=(
                            f"{message.role} messages are internal to Sage and "
                            "have no A2A role"
                        ),
                    ),
                )
            )
        text = "\n".join(
            block.text for block in message.content if isinstance(block, TextBlock)
        )
        return AdapterResult(
            frames=(
                frame(
                    event,
                    protocol=self.protocol,
                    version=self.version,
                    frame_kind="notification",
                    name="task/message",
                    payload={
                        "taskId": event.run_id,
                        "contextId": event.session_id,
                        "message": {
                            "messageId": data.item.item_id,
                            "taskId": event.run_id,
                            "contextId": event.session_id,
                            "role": role,
                            "parts": [{"text": text}],
                        },
                    },
                ),
            )
        )

    def _status(
        self,
        event: RuntimeEvent,
        *,
        state: str,
        text: str | None,
        metadata: dict[str, object],
    ):
        status: dict[str, object] = {
            "state": state,
            "timestamp": event.occurred_at.isoformat(),
        }
        if text:
            status["message"] = {
                "messageId": event.event_id,
                "taskId": event.run_id,
                "contextId": event.session_id,
                "role": "ROLE_AGENT",
                "parts": [{"text": text}],
            }
        payload: dict[str, object] = {
            "taskId": event.run_id,
            "contextId": event.session_id,
            "status": status,
        }
        if metadata:
            payload["metadata"] = metadata
        return frame(
            event,
            protocol=self.protocol,
            version=self.version,
            frame_kind="notification",
            name="task/status-update",
            payload=payload,
        )

    def _unsupported(self, event: RuntimeEvent) -> AdapterResult:
        return AdapterResult(
            losses=(
                loss(
                    event,
                    fidelity=MappingFidelity.UNSUPPORTED,
                    code="a2a.unsupported",
                    detail="A2A task model cannot represent this Sage runtime fact",
                ),
            )
        )


def _delta_text(delta: object) -> str:
    if isinstance(delta, str):
        return delta
    if isinstance(delta, dict):
        return str(delta.get("text") or "")
    if isinstance(delta, tuple):
        return "".join(_delta_text(item) for item in delta)
    return ""

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


class A2AProtocolAdapter:
    """Task-oriented projection that explicitly loses Step/Tool/Flow detail."""

    protocol = "a2a"
    # Latest published stable line; the development specification is newer and
    # must not be advertised as a supported wire version until conformance lands.
    version = "0.3"

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
            status = {
                "run.queued": "submitted",
                "run.started": "working",
                "run.completed": "completed",
                "run.failed": "failed",
                "run.cancelled": "canceled",
                "run.suspended": "input-required",
            }.get(event.type)
            if status:
                return AdapterResult(
                    frames=(
                        frame(
                            event,
                            protocol=self.protocol,
                            version=self.version,
                            frame_kind="notification",
                            name="task/status-update",
                            payload={
                                "taskId": event.run_id,
                                "contextId": event.session_id,
                                "status": {
                                    "state": status,
                                    "message": (
                                        data.error.message
                                        if event.type == "run.failed" and data.error
                                        else data.reason
                                    ),
                                    "errorCode": (
                                        data.error.code
                                        if event.type == "run.failed" and data.error
                                        else None
                                    ),
                                },
                            },
                        ),
                    )
                )
        if (
            isinstance(data, InteractionEventData)
            and event.type == "interaction.requested"
        ):
            return AdapterResult(
                frames=(
                    frame(
                        event,
                        protocol=self.protocol,
                        version=self.version,
                        frame_kind="notification",
                        name="task/status-update",
                        payload={
                            "taskId": event.run_id,
                            "contextId": event.session_id,
                            "status": {
                                "state": "input-required",
                                "interactionId": data.interaction_id,
                                "type": data.interaction_type,
                                "allowedDecisions": list(data.allowed_decisions),
                                "payload": data.payload,
                            },
                        },
                    ),
                )
            )
        if isinstance(data, ArtifactEventData):
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
                            "artifact": {
                                "artifactId": data.artifact.artifact_id,
                                "name": data.artifact.name,
                                "parts": [{"kind": "file", "uri": data.artifact.uri}],
                            },
                        },
                    ),
                )
            )
        if (
            isinstance(data, ItemEventData)
            and data.item is not None
            and isinstance(data.item.data, MessageItemData)
        ):
            text = "\n".join(
                block.text
                for block in data.item.data.content
                if isinstance(block, TextBlock)
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
                            "message": {
                                "role": data.item.data.role,
                                "parts": [{"kind": "text", "text": text}],
                            },
                        },
                    ),
                )
            )
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

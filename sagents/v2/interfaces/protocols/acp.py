"""Project Native RuntimeEvents into ACP v1 session updates and requests."""

from __future__ import annotations

from sagents.v2.contracts.events import (
    ArtifactEventData,
    InteractionEventData,
    ItemEventData,
    RunEventData,
    RuntimeEvent,
    ToolEventData,
)
from sagents.v2.contracts.items import (
    MessageItemData,
    ReasoningItemData,
    TextBlock,
    ToolCallItemData,
    ToolResultItemData,
)
from sagents.v2.interfaces.protocols.contracts import (
    AdapterCapabilities,
    AdapterResult,
    MappingFidelity,
    frame,
    loss,
)


class AcpProtocolAdapter:
    """ACP projection with LossReports for unsupported Run/Flow semantics."""

    protocol = "acp"
    version = "1"

    async def capabilities(self):
        return AdapterCapabilities(
            protocol=self.protocol,
            protocol_version=self.version,
            adapter_version="sage-v2/1",
            supports_run_lifecycle=True,
            supports_item_lifecycle=True,
            supports_reasoning=True,
            supports_tool_lifecycle=True,
            supports_interactions=True,
            supports_pause_resume=False,
            supports_exact_cursor_replay=False,
            supports_flow=False,
            supports_artifacts=True,
            extensions=("sage-session-update",),
        )

    def translate(self, event: RuntimeEvent) -> AdapterResult:
        """Translate exactly one Native fact; never infer missing lifecycle state."""

        data = event.data
        if (
            isinstance(data, InteractionEventData)
            and event.type == "interaction.requested"
        ):
            method = (
                "session/request_permission"
                if data.interaction_type in {"approval", "permission"}
                else "session/request_input"
            )
            return AdapterResult(
                frames=(
                    frame(
                        event,
                        protocol=self.protocol,
                        version=self.version,
                        frame_kind="request",
                        frame_id=data.interaction_id,
                        name=method,
                        payload={
                            "sessionId": event.session_id,
                            "runId": event.run_id,
                            "interactionId": data.interaction_id,
                            "type": data.interaction_type,
                            "revision": data.revision,
                        },
                    ),
                )
            )
        if isinstance(data, ItemEventData):
            return self._item(event, data)
        if isinstance(data, ToolEventData):
            return AdapterResult(
                frames=(
                    frame(
                        event,
                        protocol=self.protocol,
                        version=self.version,
                        frame_kind="notification",
                        name="session/update",
                        payload={
                            "sessionId": event.session_id,
                            "update": {
                                "sessionUpdate": "tool_call_update",
                                "toolCallId": data.tool_call_id,
                                "status": data.state,
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
                        name="session/update",
                        payload={
                            "sessionId": event.session_id,
                            "update": {
                                "sessionUpdate": "resource",
                                "uri": data.artifact.uri,
                                "name": data.artifact.name,
                            },
                        },
                    ),
                )
            )
        if isinstance(data, RunEventData):
            status = {
                "run.started": "in_progress",
                "run.completed": "completed",
                "run.failed": "failed",
                "run.cancelled": "cancelled",
            }.get(event.type)
            if status:
                return AdapterResult(
                    frames=(
                        frame(
                            event,
                            protocol=self.protocol,
                            version=self.version,
                            frame_kind="notification",
                            name="session/update",
                            payload={
                                "sessionId": event.session_id,
                                "update": {"sessionUpdate": "status", "status": status},
                            },
                        ),
                    )
                )
        return AdapterResult(
            losses=(
                loss(
                    event,
                    fidelity=MappingFidelity.UNSUPPORTED,
                    code="acp.unsupported",
                    detail="ACP has no lossless mapping for this Sage runtime fact",
                ),
            )
        )

    def _item(self, event, data):
        """Flatten the richer v2 Item lifecycle into ACP session updates."""

        if data.operation == "delta":
            kind = (
                "agent_thought_chunk"
                if event.type == "reasoning.delta"
                else "agent_message_chunk"
            )
            return AdapterResult(
                frames=(
                    frame(
                        event,
                        protocol=self.protocol,
                        version=self.version,
                        frame_kind="notification",
                        name="session/update",
                        payload={
                            "sessionId": event.session_id,
                            "update": {
                                "sessionUpdate": kind,
                                "content": {"type": "text", "text": data.delta},
                            },
                        },
                    ),
                )
            )
        if data.item is None:
            return AdapterResult(
                losses=(
                    loss(
                        event,
                        fidelity=MappingFidelity.UNSUPPORTED,
                        code="acp.item_incomplete",
                        detail="item lifecycle fact has no ACP content mapping",
                    ),
                )
            )
        item = data.item.data
        if isinstance(item, (MessageItemData, ReasoningItemData)):
            kind = (
                "agent_thought_chunk"
                if isinstance(item, ReasoningItemData)
                else "agent_message_chunk"
            )
            text = "\n".join(
                block.text for block in item.content if isinstance(block, TextBlock)
            )
            return AdapterResult(
                frames=(
                    frame(
                        event,
                        protocol=self.protocol,
                        version=self.version,
                        frame_kind="notification",
                        name="session/update",
                        payload={
                            "sessionId": event.session_id,
                            "update": {
                                "sessionUpdate": kind,
                                "content": {"type": "text", "text": text},
                            },
                        },
                    ),
                )
            )
        if isinstance(item, ToolCallItemData):
            return AdapterResult(
                frames=(
                    frame(
                        event,
                        protocol=self.protocol,
                        version=self.version,
                        frame_kind="notification",
                        name="session/update",
                        payload={
                            "sessionId": event.session_id,
                            "update": {
                                "sessionUpdate": "tool_call",
                                "toolCallId": item.tool_call_id,
                                "title": item.tool_name,
                                "rawInput": item.arguments,
                            },
                        },
                    ),
                )
            )
        if isinstance(item, ToolResultItemData):
            text = "\n".join(
                block.text for block in item.content if isinstance(block, TextBlock)
            )
            return AdapterResult(
                frames=(
                    frame(
                        event,
                        protocol=self.protocol,
                        version=self.version,
                        frame_kind="notification",
                        name="session/update",
                        payload={
                            "sessionId": event.session_id,
                            "update": {
                                "sessionUpdate": "tool_call_update",
                                "toolCallId": item.tool_call_id,
                                "status": "failed" if item.error else "completed",
                                "content": [
                                    {
                                        "type": "content",
                                        "content": {"type": "text", "text": text},
                                    }
                                ],
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
                    code="acp.item_unsupported",
                    detail=f"ACP mapping unavailable for item kind {item.kind}",
                ),
            )
        )

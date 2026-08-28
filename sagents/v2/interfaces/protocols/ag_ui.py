"""Project Native RuntimeEvents into AG-UI plus optional Sage extensions."""

from __future__ import annotations

import json

from sagents.v2.contracts.events import (
    ArtifactEventData,
    FlowEventData,
    InteractionEventData,
    ItemEventData,
    JobEventData,
    PolicyEventData,
    ProtocolEventData,
    RunEventData,
    RuntimeEvent,
    SandboxEventData,
    SessionCommitEventData,
    SteeringEventData,
    ToolEventData,
    UsageEventData,
)
from sagents.v2.contracts.items import (
    ActivityItemData,
    ErrorItemData,
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


class AgUiProtocolAdapter:
    """AG-UI event adapter with explicit Sage extensions for kernel-only facts."""

    protocol = "ag-ui"
    version = "0.1"

    def __init__(self, *, enable_sage_extensions: bool = True) -> None:
        self.enable_sage_extensions = enable_sage_extensions
        self._started_text: set[str] = set()
        self._started_reasoning: set[str] = set()

    async def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            protocol=self.protocol,
            protocol_version=self.version,
            adapter_version="sage-v2/1",
            supports_run_lifecycle=True,
            supports_item_lifecycle=True,
            supports_reasoning=True,
            supports_tool_lifecycle=True,
            supports_interactions=self.enable_sage_extensions,
            supports_pause_resume=self.enable_sage_extensions,
            supports_exact_cursor_replay=False,
            supports_flow=self.enable_sage_extensions,
            supports_artifacts=True,
            extensions=("sage-native-events",) if self.enable_sage_extensions else (),
        )

    def translate(self, event: RuntimeEvent) -> AdapterResult:
        data = event.data
        if isinstance(data, RunEventData):
            return self._run(event, data)
        if isinstance(data, ItemEventData):
            return self._item(event, data)
        if isinstance(data, ToolEventData):
            return AdapterResult(
                frames=(
                    self._frame(
                        event,
                        "CUSTOM",
                        {"name": event.type, "value": data.model_dump(mode="json")},
                    ),
                ),
                losses=(
                    loss(
                        event,
                        fidelity=MappingFidelity.EXTENSION,
                        code="ag_ui.tool_state_extension",
                        detail="AG-UI tool item events do not cover Sage dispatch/reconcile states",
                        preserved_by_extension=True,
                    ),
                ),
            )
        if isinstance(data, ArtifactEventData):
            return AdapterResult(
                frames=(
                    self._frame(
                        event,
                        "ACTIVITY_SNAPSHOT",
                        {
                            "messageId": data.artifact.artifact_id,
                            "activityType": "artifact",
                            "content": data.model_dump(mode="json"),
                            "replace": True,
                        },
                    ),
                )
            )
        if isinstance(data, UsageEventData):
            return self._extension(event, "sage.usage", data.model_dump(mode="json"))
        if (
            isinstance(
                data,
                (
                    InteractionEventData,
                    FlowEventData,
                    SandboxEventData,
                    PolicyEventData,
                    SteeringEventData,
                    JobEventData,
                    ProtocolEventData,
                    SessionCommitEventData,
                ),
            )
            or event.type == "checkpoint.committed"
        ):
            return self._extension(
                event, f"sage.{event.type}", data.model_dump(mode="json")
            )
        return self._unsupported(event, "AG-UI has no mapping for this event family")

    def _run(self, event, data):
        if event.type == "run.started":
            return AdapterResult(
                frames=(
                    self._frame(
                        event,
                        "RUN_STARTED",
                        {"threadId": event.session_id, "runId": event.run_id},
                    ),
                )
            )
        if event.type == "run.completed":
            return AdapterResult(
                frames=(
                    self._frame(
                        event,
                        "RUN_FINISHED",
                        {"threadId": event.session_id, "runId": event.run_id},
                    ),
                )
            )
        if event.type == "run.failed":
            return AdapterResult(
                frames=(
                    self._frame(
                        event,
                        "RUN_ERROR",
                        {
                            "message": data.error.message
                            if data.error
                            else "run failed",
                            "code": data.error.code if data.error else None,
                        },
                    ),
                )
            )
        if event.type == "run.cancelled":
            return self._extension(
                event, "sage.run.cancelled", data.model_dump(mode="json")
            )
        if event.type in {
            "run.suspended",
            "run.resume_requested",
            "run.resumed",
            "run.pause_requested",
        }:
            return self._extension(
                event, f"sage.{event.type}", data.model_dump(mode="json")
            )
        return self._extension(
            event, f"sage.{event.type}", data.model_dump(mode="json")
        )

    def _item(self, event, data):
        """Maintain AG-UI start/content/end framing for one canonical Item."""

        item_id = event.item_id or (data.item.item_id if data.item else event.event_id)
        if event.type == "message.delta":
            frames = []
            if item_id not in self._started_text:
                self._started_text.add(item_id)
                frames.append(
                    self._frame(
                        event,
                        "TEXT_MESSAGE_START",
                        {"messageId": item_id, "role": "assistant"},
                    )
                )
            frames.append(
                self._frame(
                    event,
                    "TEXT_MESSAGE_CONTENT",
                    {"messageId": item_id, "delta": data.delta},
                )
            )
            return AdapterResult(frames=tuple(frames))
        if event.type == "reasoning.delta":
            frames = []
            if item_id not in self._started_reasoning:
                self._started_reasoning.add(item_id)
                frames.extend(
                    (
                        self._frame(event, "REASONING_START", {"messageId": item_id}),
                        self._frame(
                            event,
                            "REASONING_MESSAGE_START",
                            {"messageId": item_id, "role": "reasoning"},
                        ),
                    )
                )
            frames.append(
                self._frame(
                    event,
                    "REASONING_MESSAGE_CONTENT",
                    {"messageId": item_id, "delta": data.delta},
                )
            )
            return AdapterResult(frames=tuple(frames))
        if data.item is None:
            return self._extension(
                event, f"sage.{event.type}", data.model_dump(mode="json")
            )
        item = data.item.data
        if isinstance(item, MessageItemData):
            text = self._text(item.content)
            frames = []
            if item_id not in self._started_text:
                frames.extend(
                    (
                        self._frame(
                            event,
                            "TEXT_MESSAGE_START",
                            {"messageId": item_id, "role": item.role},
                        ),
                        self._frame(
                            event,
                            "TEXT_MESSAGE_CONTENT",
                            {"messageId": item_id, "delta": text},
                        ),
                    )
                )
            frames.append(
                self._frame(event, "TEXT_MESSAGE_END", {"messageId": item_id})
            )
            self._started_text.discard(item_id)
            return AdapterResult(frames=tuple(frames))
        if isinstance(item, ReasoningItemData):
            text = self._text(item.content)
            frames = []
            if item_id not in self._started_reasoning:
                frames.extend(
                    (
                        self._frame(event, "REASONING_START", {"messageId": item_id}),
                        self._frame(
                            event,
                            "REASONING_MESSAGE_START",
                            {"messageId": item_id, "role": "reasoning"},
                        ),
                        self._frame(
                            event,
                            "REASONING_MESSAGE_CONTENT",
                            {"messageId": item_id, "delta": text},
                        ),
                    )
                )
            frames.extend(
                (
                    self._frame(event, "REASONING_MESSAGE_END", {"messageId": item_id}),
                    self._frame(event, "REASONING_END", {"messageId": item_id}),
                )
            )
            self._started_reasoning.discard(item_id)
            return AdapterResult(frames=tuple(frames))
        if isinstance(item, ToolCallItemData):
            arguments = item.arguments_json or json.dumps(
                item.arguments or {}, separators=(",", ":")
            )
            return AdapterResult(
                frames=(
                    self._frame(
                        event,
                        "TOOL_CALL_START",
                        {
                            "toolCallId": item.tool_call_id,
                            "toolCallName": item.tool_name,
                            "parentMessageId": item_id,
                        },
                    ),
                    self._frame(
                        event,
                        "TOOL_CALL_ARGS",
                        {"toolCallId": item.tool_call_id, "delta": arguments},
                    ),
                    self._frame(
                        event, "TOOL_CALL_END", {"toolCallId": item.tool_call_id}
                    ),
                )
            )
        if isinstance(item, ToolResultItemData):
            return AdapterResult(
                frames=(
                    self._frame(
                        event,
                        "TOOL_CALL_RESULT",
                        {
                            "messageId": item_id,
                            "toolCallId": item.tool_call_id,
                            "content": self._text(item.content),
                            "role": "tool",
                        },
                    ),
                )
            )
        if isinstance(item, ActivityItemData):
            return AdapterResult(
                frames=(
                    self._frame(
                        event,
                        "ACTIVITY_SNAPSHOT",
                        {
                            "messageId": item_id,
                            "activityType": item.activity_type,
                            "content": item.state,
                            "replace": True,
                        },
                    ),
                )
            )
        if isinstance(item, ErrorItemData):
            return AdapterResult(
                frames=(
                    self._frame(
                        event,
                        "RUN_ERROR",
                        {"message": item.error.message, "code": item.error.code},
                    ),
                )
            )
        return self._extension(
            event, f"sage.item.{item.kind}", data.model_dump(mode="json")
        )

    def _extension(self, event, name, value):
        if not self.enable_sage_extensions:
            return self._unsupported(
                event, f"{event.type} requires Sage AG-UI extension"
            )
        return AdapterResult(
            frames=(self._frame(event, "CUSTOM", {"name": name, "value": value}),),
            losses=(
                loss(
                    event,
                    fidelity=MappingFidelity.EXTENSION,
                    code="ag_ui.sage_extension",
                    detail="fact is preserved in a namespaced Sage custom event",
                    preserved_by_extension=True,
                ),
            ),
        )

    def _unsupported(self, event, detail):
        return AdapterResult(
            losses=(
                loss(
                    event,
                    fidelity=MappingFidelity.UNSUPPORTED,
                    code="ag_ui.unsupported",
                    detail=detail,
                ),
            )
        )

    def _frame(self, event, name, payload):
        return frame(
            event,
            protocol=self.protocol,
            version=self.version,
            name=name,
            payload=payload,
        )

    @staticmethod
    def _text(blocks):
        return "\n".join(block.text for block in blocks if isinstance(block, TextBlock))

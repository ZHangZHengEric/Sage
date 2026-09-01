"""SAgents V2 module for interfaces/protocols/mcp.py."""

from __future__ import annotations

from sagents.v2.contracts.events import (
    InteractionEventData,
    JobEventData,
    RuntimeEvent,
    ToolEventData,
)
from sagents.v2.interfaces.protocols.contracts import (
    AdapterCapabilities,
    AdapterResult,
    MappingFidelity,
    frame,
    loss,
)


class McpProtocolAdapter:
    """Maps only MCP-correlated progress/elicitation; MCP is not a Run protocol."""

    plugin_id = "sage.protocol.mcp"
    protocol = "mcp"
    version = "2026-07-28"

    async def capabilities(self):
        return AdapterCapabilities(
            protocol=self.protocol,
            protocol_version=self.version,
            adapter_version="sage-v2/1",
            supports_run_lifecycle=False,
            supports_item_lifecycle=False,
            supports_reasoning=False,
            supports_tool_lifecycle=True,
            supports_interactions=True,
            supports_pause_resume=False,
            supports_exact_cursor_replay=False,
            supports_flow=False,
            supports_artifacts=False,
        )

    def translate(self, event: RuntimeEvent) -> AdapterResult:
        data = event.data
        if (
            isinstance(data, InteractionEventData)
            and event.type == "interaction.requested"
        ):
            questions = tuple(
                question
                for question in (data.payload.get("questions") or ())
                if isinstance(question, dict)
            )
            properties = {
                str(question.get("id") or f"q{index + 1}"): {
                    "type": (
                        "array" if question.get("type") == "multiple" else "string"
                    ),
                    "title": question.get("title") or question.get("question"),
                    **(
                        {
                            "items": {
                                "type": "string",
                                "enum": [
                                    option.get("value")
                                    if isinstance(option, dict)
                                    else option
                                    for option in question.get("options", [])
                                ],
                            }
                        }
                        if question.get("type") == "multiple"
                        else {
                            "enum": [
                                option.get("value")
                                if isinstance(option, dict)
                                else option
                                for option in question.get("options", [])
                            ]
                        }
                        if question.get("type") == "single"
                        else {}
                    ),
                }
                for index, question in enumerate(questions)
            }
            if not properties:
                properties["response"] = {
                    "type": "string",
                    "title": data.payload.get("prompt")
                    or data.payload.get("title")
                    or data.interaction_type,
                }
            if data.allowed_decisions:
                properties["decision"] = {
                    "type": "string",
                    "title": data.payload.get("guidance") or "Decision",
                    "enum": list(data.allowed_decisions),
                }
            return AdapterResult(
                frames=(
                    frame(
                        event,
                        protocol=self.protocol,
                        version=self.version,
                        frame_kind="request",
                        frame_id=data.interaction_id,
                        name="elicitation/create",
                        payload={
                            "interactionId": data.interaction_id,
                            "runId": event.run_id,
                            "message": data.payload.get("prompt")
                            or data.payload.get("title")
                            or data.interaction_type,
                            "requestedSchema": {
                                "type": "object",
                                "properties": properties,
                            },
                            "sageInteraction": {
                                "type": data.interaction_type,
                                "allowedDecisions": list(data.allowed_decisions),
                                "payload": data.payload,
                            },
                        },
                    ),
                )
            )
        if isinstance(data, (ToolEventData, JobEventData)):
            progress = data.progress if isinstance(data, JobEventData) else None
            return AdapterResult(
                frames=(
                    frame(
                        event,
                        protocol=self.protocol,
                        version=self.version,
                        frame_kind="notification",
                        name="notifications/progress",
                        payload={
                            "progressToken": event.job_id
                            or getattr(data, "tool_call_id", event.event_id),
                            "progress": progress,
                            "message": event.type,
                        },
                    ),
                ),
                losses=(
                    loss(
                        event,
                        fidelity=MappingFidelity.LOSSY,
                        code="mcp.progress_only",
                        detail="MCP progress does not preserve Sage Run sequencing or lifecycle",
                    ),
                ),
            )
        return AdapterResult(
            losses=(
                loss(
                    event,
                    fidelity=MappingFidelity.UNSUPPORTED,
                    code="mcp.not_run_protocol",
                    detail="MCP request lifecycle cannot represent this Sage Run event",
                ),
            )
        )

"""SAgents V2 module for model/contracts.py."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from sagents.v2.contracts.common import Identifier, StrictModel, ToolName, VerbatimText
from sagents.v2.contracts.items import ContentBlock, UsageSummary
from sagents.v2.contracts.provider_state import validate_provider_state


class ModelEventKind(str, Enum):
    TEXT_DELTA = "text_delta"
    REASONING_DELTA = "reasoning_delta"
    COMPLETED = "completed"


class ModelCapabilities(StrictModel):
    api_version: Literal["2"] = "2"
    supports_streaming: bool
    supports_tools: bool
    supports_parallel_tool_calls: bool
    supports_reasoning: bool
    supports_multimodal_input: bool
    supports_structured_output: bool
    supports_continuation: bool = False
    max_input_tokens: int | None = Field(default=None, gt=0)
    max_output_tokens: int | None = Field(default=None, gt=0)


class ModelMessage(StrictModel):
    role: Literal["system", "developer", "user", "assistant", "tool"]
    content: tuple[ContentBlock, ...] = ()
    tool_call_id: Identifier | None = None
    tool_calls: tuple["ModelToolCall", ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)
    # Opaque, JSON-serializable continuation material partitioned by wire
    # protocol. It is not rendered to users and a provider may only consume its
    # own namespace.
    provider_state: dict[str, Any] = Field(default_factory=dict)

    _validate_provider_state = field_validator("provider_state")(
        validate_provider_state
    )

    @model_validator(mode="after")
    def validate_tool_message(self) -> "ModelMessage":
        if self.role == "tool" and self.tool_call_id is None:
            raise ValueError("tool messages require tool_call_id")
        return self


class ModelToolDefinition(StrictModel):
    name: ToolName
    description: str
    input_schema: dict[str, Any]
    strict: bool | None = None
    output_schema: dict[str, Any] | None = None


class ModelToolCall(StrictModel):
    tool_call_id: Identifier
    name: ToolName
    arguments: dict[str, Any]


class ModelRequest(StrictModel):
    request_id: Identifier
    run_id: Identifier
    model_binding: Identifier
    messages: tuple[ModelMessage, ...]
    tools: tuple[ModelToolDefinition, ...] = ()
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_output_tokens: int | None = Field(default=None, gt=0)
    response_format: Literal["json_object"] | None = None
    response_schema: dict[str, Any] | None = None
    tool_choice: Literal["auto", "required", "none"] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("tools")
    @classmethod
    def stabilize_tool_order(
        cls, tools: tuple[ModelToolDefinition, ...]
    ) -> tuple[ModelToolDefinition, ...]:
        """Keep provider payloads stable when selection ranking changes.

        Tool-selection policies may rank the same selected set differently as
        recent calls change. Provider prompt caches include the serialized
        ``tools`` field, so ranking order must not leak across this request
        boundary. Selection membership is preserved; only its wire order is
        canonicalized.
        """

        return tuple(sorted(tools, key=lambda tool: tool.name))

    @model_validator(mode="after")
    def validate_output_and_tool_controls(self) -> "ModelRequest":
        if self.response_format is not None and self.response_schema is not None:
            raise ValueError(
                "response_format and response_schema are mutually exclusive"
            )
        if self.tool_choice == "required" and not self.tools:
            raise ValueError("required tool_choice requires at least one Tool")
        return self


class ModelResponse(StrictModel):
    response_id: Identifier
    text: str = ""
    reasoning: str = ""
    tool_calls: tuple[ModelToolCall, ...] = ()
    finish_reason: str
    usage: UsageSummary = Field(default_factory=UsageSummary)
    provider_metadata: dict[str, Any] = Field(default_factory=dict)
    provider_state: dict[str, Any] = Field(default_factory=dict)

    _validate_provider_state = field_validator("provider_state")(
        validate_provider_state
    )


class ModelStreamEvent(StrictModel):
    kind: ModelEventKind
    delta: VerbatimText | None = None
    response: ModelResponse | None = None

    @model_validator(mode="after")
    def validate_payload(self) -> "ModelStreamEvent":
        if self.kind in {ModelEventKind.TEXT_DELTA, ModelEventKind.REASONING_DELTA}:
            if self.delta is None or self.response is not None:
                raise ValueError("delta events require only delta")
        elif self.kind == ModelEventKind.COMPLETED:
            if self.response is None or self.delta is not None:
                raise ValueError("completed event requires only response")
        return self

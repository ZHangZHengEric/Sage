"""SAgents V2 module for model/contracts.py."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import Field, model_validator

from sagents.v2.contracts.common import Identifier, StrictModel, ToolName
from sagents.v2.contracts.items import ContentBlock, UsageSummary


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
    response_schema: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelResponse(StrictModel):
    response_id: Identifier
    text: str = ""
    reasoning: str = ""
    tool_calls: tuple[ModelToolCall, ...] = ()
    finish_reason: str
    usage: UsageSummary = Field(default_factory=UsageSummary)
    provider_metadata: dict[str, Any] = Field(default_factory=dict)


class ModelStreamEvent(StrictModel):
    kind: ModelEventKind
    delta: str | None = None
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

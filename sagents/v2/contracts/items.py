"""SAgents V2 module for contracts/items.py."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal, Union

from pydantic import Field, field_validator

from sagents.v2.contracts.common import Identifier, StrictModel, ToolName
from sagents.v2.contracts.errors import RuntimeErrorInfo
from sagents.v2.contracts.provider_state import validate_provider_state


class Visibility(str, Enum):
    PUBLIC = "public"
    MODEL_VISIBLE = "model_visible"
    AUDIT = "audit"
    DIAGNOSTIC = "diagnostic"


class ItemStatus(str, Enum):
    STARTED = "started"
    RUNNING = "running"
    SUSPENDED = "suspended"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DECLINED = "declined"


class TextBlock(StrictModel):
    kind: Literal["text"] = "text"
    text: str
    mime_type: str = "text/plain"


class ImageBlock(StrictModel):
    kind: Literal["image"] = "image"
    uri: str
    mime_type: str
    alt: str | None = None
    detail: Literal["auto", "low", "high", "original"] = "auto"


class AudioBlock(StrictModel):
    kind: Literal["audio"] = "audio"
    uri: str
    mime_type: str


class FileBlock(StrictModel):
    kind: Literal["file"] = "file"
    uri: str
    name: str
    mime_type: str | None = None
    size: int | None = Field(default=None, ge=0)


class JsonBlock(StrictModel):
    kind: Literal["json"] = "json"
    value: Any
    schema_ref: str | None = None


class ResourceRefBlock(StrictModel):
    kind: Literal["resource_ref"] = "resource_ref"
    uri: str
    name: str | None = None
    mime_type: str | None = None


ContentBlock = Annotated[
    Union[TextBlock, ImageBlock, AudioBlock, FileBlock, JsonBlock, ResourceRefBlock],
    Field(discriminator="kind"),
]


class MessageItemData(StrictModel):
    kind: Literal["message"] = "message"
    role: Literal["user", "assistant", "system", "developer", "tool"]
    content: tuple[ContentBlock, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)
    provider_state: dict[str, Any] = Field(default_factory=dict)

    _validate_provider_state = field_validator("provider_state")(
        validate_provider_state
    )


class ReasoningItemData(StrictModel):
    kind: Literal["reasoning"] = "reasoning"
    content: tuple[ContentBlock, ...] = ()
    encrypted_content: str | None = None


class ToolCallItemData(StrictModel):
    kind: Literal["tool_call"] = "tool_call"
    tool_call_id: Identifier
    tool_name: ToolName
    arguments: dict[str, Any] | None = None
    arguments_json: str | None = None


class ToolResultItemData(StrictModel):
    kind: Literal["tool_result"] = "tool_result"
    tool_call_id: Identifier
    content: tuple[ContentBlock, ...] = ()
    error: RuntimeErrorInfo | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActivityItemData(StrictModel):
    kind: Literal["activity"] = "activity"
    activity_type: Identifier
    state: dict[str, Any]


class PlanItemData(StrictModel):
    kind: Literal["plan"] = "plan"
    title: str | None = None
    steps: tuple[dict[str, Any], ...]


class ArtifactItemData(StrictModel):
    kind: Literal["artifact"] = "artifact"
    artifact_id: Identifier
    name: str
    uri: str
    mime_type: str | None = None


class InteractionItemData(StrictModel):
    kind: Literal["interaction"] = "interaction"
    interaction_id: Identifier
    interaction_type: Identifier


class ErrorItemData(StrictModel):
    kind: Literal["error"] = "error"
    error: RuntimeErrorInfo


ItemData = Annotated[
    Union[
        MessageItemData,
        ReasoningItemData,
        ToolCallItemData,
        ToolResultItemData,
        ActivityItemData,
        PlanItemData,
        ArtifactItemData,
        InteractionItemData,
        ErrorItemData,
    ],
    Field(discriminator="kind"),
]


class ItemSnapshot(StrictModel):
    item_id: Identifier
    run_id: Identifier
    turn_id: Identifier | None = None
    step_id: Identifier | None = None
    owner_agent_id: Identifier | None = None
    status: ItemStatus
    visibility: Visibility = Visibility.PUBLIC
    presentation_key: str | None = None
    data: ItemData
    content_hash: str | None = None
    created_at: datetime
    updated_at: datetime


class ArtifactRef(StrictModel):
    artifact_id: Identifier
    uri: str
    name: str
    mime_type: str | None = None
    content_hash: str | None = None
    size: int | None = Field(default=None, ge=0)


class UsageSummary(StrictModel):
    # ``reported`` distinguishes a provider-reported zero from the legacy
    # default used when an endpoint omits usage altogether.  Runtime consumers
    # use the canonical counters below; diagnostics can inspect the original
    # provider payload without learning every compatible gateway dialect.
    # ``input_tokens`` is canonical total prompt input, including cache reads;
    # ``cached_input_tokens`` is the cached subset of that total.
    reported: bool = False
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    reasoning_tokens: int = Field(default=0, ge=0)
    cost: float | None = Field(default=None, ge=0)
    models: tuple[str, ...] = ()
    provider_usage: dict[str, Any] = Field(default_factory=dict)

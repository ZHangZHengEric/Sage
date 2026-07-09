from typing import Any, Dict, List, Literal, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


ReasoningLevel = Literal["minimal", "low", "medium", "high"]
ModelType = Literal["standard", "fast"]
ATTRIBUTION_METADATA_KEYS = (
    "task",
    "request_source",
    "source",
    "billing_key",
    "purpose",
)


class DirectModelInvokeRequest(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    agent_id: Optional[str] = None
    provider_id: Optional[str] = None
    user_id: Optional[str] = None
    model_type: ModelType = "standard"
    task: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    messages: List[Dict[str, Any]] = Field(min_length=1)
    response_format: Optional[Dict[str, Any]] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    stream: bool = False
    deep_thinking: Optional[bool] = None
    thinking_level: Optional[ReasoningLevel] = Field(
        default=None,
        validation_alias=AliasChoices("thinking_level", "deep_thinking_level"),
    )

    @model_validator(mode="after")
    def validate_audit_context(self) -> "DirectModelInvokeRequest":
        task = str(self.task or "").strip()
        has_metadata_attribution = any(
            str(self.metadata.get(key) or "").strip()
            for key in ATTRIBUTION_METADATA_KEYS
        )
        if not task and not has_metadata_attribution:
            raise ValueError(
                "task or metadata attribution "
                "(task/request_source/source/billing_key/purpose) is required"
            )
        self.task = task or None
        return self

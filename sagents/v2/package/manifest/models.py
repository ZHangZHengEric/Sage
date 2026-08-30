"""Model route declarations."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from pydantic import Field, field_validator

from sagents.v2.contracts.common import Identifier, StrictModel


class ModelRequestDefaults(StrictModel):
    max_output_tokens: int | None = Field(default=None, gt=0)
    temperature: float | None = None
    top_p: float | None = None
    reasoning_effort: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class ModelLimits(StrictModel):
    context_window: int | None = Field(default=None, gt=0)
    max_output_tokens: int | None = Field(default=None, gt=0)


class ModelCapabilityDeclaration(StrictModel):
    multimodal: bool = False
    structured_output: bool = False
    tool_calling: bool = True
    reasoning: bool = False
    parallel_tool_calls: bool = False


class ModelRoute(StrictModel):
    provider: Identifier
    plugin: Identifier | None = None
    base_url: str | None = None
    credential: Identifier | None = None
    model: str
    request: ModelRequestDefaults = Field(default_factory=ModelRequestDefaults)
    limits: ModelLimits = Field(default_factory=ModelLimits)
    capabilities: ModelCapabilityDeclaration = Field(
        default_factory=ModelCapabilityDeclaration
    )

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "base_url must be an absolute http(s) URL without credentials"
            )
        return value

"""Stable contracts for plugin-owned model capability negotiation."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import Field, model_validator

from sagents.v2.contracts.common import StrictModel


ProbeName = Literal[
    "connection",
    "multimodal",
    "structured_output",
    "json_object",
    "tool_calling",
    "reasoning_control",
]


class ModelCapabilityProbeStatus(str, Enum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    ERROR = "error"
    SKIPPED = "skipped"


class ModelCapabilityProbeOutcome(StrictModel):
    name: ProbeName
    status: ModelCapabilityProbeStatus
    response: str | None = None
    error: str | None = None
    error_code: str | None = None
    error_category: str | None = None
    provider_code: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def supported(self) -> bool:
        return self.status == ModelCapabilityProbeStatus.SUPPORTED


class ModelCapabilityProbeReport(StrictModel):
    valid: bool
    outcomes: tuple[ModelCapabilityProbeOutcome, ...]
    successful_probes: tuple[ProbeName, ...] = ()
    failed_probes: tuple[ProbeName, ...] = ()
    skipped_probes: tuple[ProbeName, ...] = ()
    supports_text: bool = False
    supports_multimodal: bool = False
    supports_structured_output: bool = False
    supports_json_object: bool = False
    supports_tools: bool = False

    def outcome(self, name: ProbeName) -> ModelCapabilityProbeOutcome:
        return next(value for value in self.outcomes if value.name == name)


class ModelCapabilityProbeRequest(StrictModel):
    """Host-neutral request passed to a model plugin's probe interface."""

    model_binding: str
    route_fingerprint: str
    max_output_tokens: int = Field(default=128, gt=0)
    timeout_seconds: float = Field(default=30, gt=0)
    output_token_fallbacks: tuple[int, ...] = (
        65_536,
        32_768,
        16_384,
        8_192,
        4_096,
        2_048,
        1_024,
        512,
        256,
        128,
    )
    reasoning_efforts: tuple[str, ...] = (
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    )


class ModelCapabilityProfile(StrictModel):
    """Versioned probe facts and opaque invocation strategy owned by a plugin."""

    schema_version: Literal[1] = 1
    plugin_id: str
    plugin_version: str
    protocol: str
    route_fingerprint: str
    verified_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    effective_max_output_tokens: int = Field(gt=0)
    outcomes: tuple[ModelCapabilityProbeOutcome, ...]
    invocation_strategy: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def outcome(self, name: ProbeName) -> ModelCapabilityProbeOutcome:
        return next(value for value in self.outcomes if value.name == name)

    def supports(self, name: ProbeName) -> bool:
        return self.outcome(name).supported

    @model_validator(mode="after")
    def validate_standard_outcomes(self):
        expected = {
            "connection",
            "multimodal",
            "structured_output",
            "json_object",
            "tool_calling",
            "reasoning_control",
        }
        names = [value.name for value in self.outcomes]
        if len(names) != len(set(names)):
            raise ValueError("model capability profile outcomes must be unique")
        if set(names) != expected:
            raise ValueError(
                "model capability profile must include every standard outcome"
            )
        return self

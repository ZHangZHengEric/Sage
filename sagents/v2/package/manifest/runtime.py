"""Explicit runtime capability selections and policy ceilings."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import Field, field_validator, model_serializer, model_validator

from sagents.v2.contracts.common import Identifier, StrictModel
from sagents.v2.runtime.extensions.contracts import ExtensionScope


class CapabilitySelection(StrictModel):
    """Select one named provider implementation for a runtime capability."""

    plugin: Identifier
    name: Identifier = "default"
    scope: ExtensionScope | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    grant_tools: bool = False

    @model_serializer(mode="wrap")
    def serialize_selection(self, handler):
        data = handler(self)
        # Preserve immutable package hashes from before this field existed.
        if not self.grant_tools:
            data.pop("grant_tools", None)
        return data

    @field_validator("config")
    @classmethod
    def serializable_parameters(cls, value):
        try:
            json.dumps(value, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "plugin parameters must be finite JSON values; provide process objects "
                "through registered factories and declared dependencies"
            ) from exc
        return value

    @model_validator(mode="before")
    @classmethod
    def retire_skill_estimate_limit(cls, value):
        if isinstance(value, dict) and value.get("plugin") == "sage.skill.loading.lazy":
            config = value.get("config")
            if isinstance(config, dict) and "max_active_tokens" in config:
                return {
                    **value,
                    "config": {
                        k: v for k, v in config.items() if k != "max_active_tokens"
                    },
                }
        return value


CapabilityBinding = CapabilitySelection | tuple[CapabilitySelection, ...]


class RuntimeConfig(StrictModel):
    preset: Identifier = "standard"
    deployment_profile: Literal["controlled_host", "distributed"] = "controlled_host"
    plugin_trust_policy: Literal["trusted_declared", "built_in_only"] = (
        "trusted_declared"
    )
    start_workers: bool = True
    check_readiness: bool = False
    state_root: str | None = None
    capabilities: dict[Identifier, CapabilityBinding] = Field(default_factory=dict)
    # Operational guarantees are requirements, not documentation.  The
    # builder fails closed when the selected provider cannot prove each value.
    required_guarantees: dict[Identifier, dict[Identifier, Any]] = Field(
        default_factory=dict
    )

    @model_serializer(mode="wrap")
    def serialize_runtime(self, handler):
        data = handler(self)
        # Newly introduced defaults must not invalidate stored package refs.
        for name, default in (("start_workers", True), ("check_readiness", False), ("state_root", None)):
            if getattr(self, name) == default:
                data.pop(name, None)
        return data

    @field_validator("capabilities", mode="before")
    @classmethod
    def retire_input_estimator(cls, value):
        if isinstance(value, dict):
            return {
                key: item
                for key, item in value.items()
                if key != "context.token-estimator"
            }
        return value

    def selections(self, capability: str) -> tuple[CapabilitySelection, ...]:
        value = self.capabilities.get(capability)
        if value is None:
            return ()
        return value if isinstance(value, tuple) else (value,)


class BudgetConfig(StrictModel):
    max_steps: int | None = Field(default=None, gt=0)
    input_tokens: int | None = Field(default=None, gt=0)
    system_tokens: int | None = Field(default=None, gt=0)
    protected_recent_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, gt=0)
    total_tokens: int | None = Field(default=None, gt=0)
    wall_time_seconds: float | None = Field(default=None, gt=0)


class PolicyConfig(StrictModel):
    budgets: BudgetConfig = Field(default_factory=BudgetConfig)


def merge_capability_selections(defaults, overrides):
    """Merge one declared configuration; a changed implementation replaces params."""
    merged = dict(defaults)
    for capability, selection in overrides.items():
        previous = merged.get(capability)
        if (
            isinstance(previous, CapabilitySelection)
            and isinstance(selection, CapabilitySelection)
            and previous.plugin == selection.plugin
            and previous.name == selection.name
        ):
            selection = selection.model_copy(
                update={
                    "config": {**previous.config, **selection.config},
                }
            )
        merged[capability] = selection
    return merged

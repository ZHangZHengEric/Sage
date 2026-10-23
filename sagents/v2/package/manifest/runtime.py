"""Explicit runtime capability selections and policy ceilings."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import Field, field_validator, model_serializer, model_validator

from sagents.v2.contracts.common import Identifier, StrictModel
from sagents.v2.runtime.extensions.contracts import ExtensionScope
from sagents.v2.contracts.runtime_skills import RuntimeSkillAuthorization


REMOVED_CAPABILITIES = frozenset(
    {
        "tool.catalog",
        "tool.executor",
        "skill.catalog",
        "skill.source",
        "context.unit-compactor",
        "observability.log-sink",
        "observability.diagnostic-sink",
        "observability.trace-sink",
    }
)


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


class SkillUsageConfig(StrictModel):
    """Workspace and activation policy, grouped separately from the repository."""

    workspace: CapabilitySelection = Field(
        default_factory=lambda: CapabilitySelection(
            plugin="sage.skill.workspace.auto-sync",
            scope=ExtensionScope.RUN,
        )
    )
    loading: CapabilitySelection = Field(
        default_factory=lambda: CapabilitySelection(
            plugin="sage.skill.loading.lazy",
        )
    )


class SkillModulesConfig(StrictModel):
    """Convenient input syntax; normalized to ordinary capability selections."""

    management: CapabilitySelection | None = None
    usage: SkillUsageConfig = Field(default_factory=SkillUsageConfig)


class RuntimeConfig(StrictModel):
    # Host authority, independent of package Skills; empty denies attachments.
    runtime_skill_authorizations: tuple[RuntimeSkillAuthorization, ...] = ()
    preset: Identifier = "standard"
    deployment_profile: Literal["controlled_host", "distributed"] = "controlled_host"
    plugin_trust_policy: Literal["trusted_declared", "built_in_only"] = (
        "trusted_declared"
    )
    start_workers: bool = True
    check_readiness: bool = False
    state_root: str | None = None
    capabilities: dict[Identifier, CapabilityBinding] = Field(default_factory=dict)
    skills: SkillModulesConfig | None = None
    # Operational guarantees are requirements, not documentation.  The
    # builder fails closed when the selected provider cannot prove each value.
    required_guarantees: dict[Identifier, dict[Identifier, Any]] = Field(
        default_factory=dict
    )

    @model_validator(mode="before")
    @classmethod
    def expand_skill_modules(cls, value):
        if not isinstance(value, dict) or value.get("skills") is None:
            return value
        modules = SkillModulesConfig.model_validate(value["skills"])
        choices = dict(value.get("capabilities") or {})
        grouped = {
            "skill.workspace": modules.usage.workspace,
            "skill.loading": modules.usage.loading,
        }
        if modules.management is not None:
            grouped["skill.provider"] = modules.management
            grouped["skill.management"] = modules.management
        for key, selection in grouped.items():
            if (
                key in choices
                and choices[key] != selection
                and choices[key] != selection.model_dump(mode="python")
            ):
                raise ValueError(f"skills and capabilities both configure {key!r}")
            choices[key] = selection
        return {**value, "skills": None, "capabilities": choices}

    @model_serializer(mode="wrap")
    def serialize_runtime(self, handler):
        data = handler(self)
        if self.skills is None:
            data.pop("skills", None)
        # Newly introduced defaults must not invalidate stored package refs.
        for name, default in (
            ("runtime_skill_authorizations", ()),
            ("start_workers", True),
            ("check_readiness", False),
            ("state_root", None),
        ):
            if getattr(self, name) == default:
                data.pop(name, None)
        return data

    @model_validator(mode="after")
    def reject_removed_capabilities(self):
        invalid = REMOVED_CAPABILITIES.intersection(
            self.capabilities
        ) | REMOVED_CAPABILITIES.intersection(self.required_guarantees)
        if invalid:
            raise ValueError(
                f"removed capability configuration: {', '.join(sorted(invalid))}"
            )
        return self

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

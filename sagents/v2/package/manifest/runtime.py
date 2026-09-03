"""Explicit runtime capability selections and policy ceilings."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from sagents.v2.contracts.common import Identifier, StrictModel
from sagents.v2.runtime.extensions.contracts import ExtensionScope


class CapabilitySelection(StrictModel):
    """Select one named provider implementation for a runtime capability."""

    plugin: Identifier
    name: Identifier = "default"
    scope: ExtensionScope | None = None
    config: dict[str, Any] = Field(default_factory=dict)


CapabilityBinding = CapabilitySelection | tuple[CapabilitySelection, ...]


class RuntimeConfig(StrictModel):
    preset: Identifier = "standard"
    deployment_profile: Literal["controlled_host", "distributed"] = "controlled_host"
    plugin_trust_policy: Literal["trusted_declared", "built_in_only"] = (
        "trusted_declared"
    )
    capabilities: dict[Identifier, CapabilityBinding] = Field(default_factory=dict)
    # Operational guarantees are requirements, not documentation.  The
    # builder fails closed when the selected provider cannot prove each value.
    required_guarantees: dict[Identifier, dict[Identifier, Any]] = Field(
        default_factory=dict
    )

    def selections(self, capability: str) -> tuple[CapabilitySelection, ...]:
        value = self.capabilities.get(capability)
        if value is None:
            return ()
        return value if isinstance(value, tuple) else (value,)


class BudgetConfig(StrictModel):
    max_steps: int | None = Field(default=None, gt=0)
    input_tokens: int | None = Field(default=None, gt=0)
    output_tokens: int | None = Field(default=None, gt=0)
    total_tokens: int | None = Field(default=None, gt=0)
    wall_time_seconds: float | None = Field(default=None, gt=0)


class PolicyConfig(StrictModel):
    budgets: BudgetConfig = Field(default_factory=BudgetConfig)

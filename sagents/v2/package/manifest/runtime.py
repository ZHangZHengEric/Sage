"""Runtime selections and policy ceilings."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from sagents.v2.contracts.common import Identifier, StrictModel


class ProviderSelection(StrictModel):
    plugin: Identifier
    config: dict[str, Any] = Field(default_factory=dict)


class SchedulerConfig(StrictModel):
    max_concurrent_runs: int | None = Field(default=None, gt=0)
    max_concurrent_runs_per_tenant: int | None = Field(default=None, gt=0)


class RuntimeConfig(StrictModel):
    preset: str = "standard"
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    session_store: ProviderSelection | None = None
    memory_provider: ProviderSelection | None = None
    session_memory_provider: ProviderSelection | None = None
    tool_provider: ProviderSelection | None = None
    tool_selection: ProviderSelection | None = None


class BudgetConfig(StrictModel):
    max_steps: int | None = Field(default=None, gt=0)
    input_tokens: int | None = Field(default=None, gt=0)
    output_tokens: int | None = Field(default=None, gt=0)
    total_tokens: int | None = Field(default=None, gt=0)
    wall_time_seconds: float | None = Field(default=None, gt=0)


class PolicyConfig(StrictModel):
    budgets: BudgetConfig = Field(default_factory=BudgetConfig)

"""Agent declarations and package entrypoints."""

from __future__ import annotations

from typing import Any, Literal

from sagents.v2.agent.policy.approval_config import ToolApprovalConfig
from pydantic import Field, model_validator

from sagents.v2.contracts.common import (
    Identifier,
    SkillName,
    StrictModel,
    ToolName,
    VerbatimText,
)


class Instructions(StrictModel):
    inline: VerbatimText | None = None
    path: str | None = None

    @model_validator(mode="after")
    def exactly_one_source(self) -> "Instructions":
        if (self.inline is None) == (self.path is None):
            raise ValueError("instructions require exactly one of inline or path")
        return self


class AgentBudgets(StrictModel):
    max_steps: int | None = Field(default=None, gt=0)
    input_tokens: int | None = Field(default=None, gt=0)
    output_tokens: int | None = Field(default=None, gt=0)
    total_tokens: int | None = Field(default=None, gt=0)
    wall_time_seconds: float | None = Field(default=None, gt=0)

    @model_validator(mode="before")
    @classmethod
    def retire_estimated_budgets(cls, value):
        from sagents.v2.package.manifest.runtime import retire_budget_fields

        return retire_budget_fields(value)


class AgentMemoryBehavior(StrictModel):
    recall: bool = False
    auto_write: bool = False
    scope: str = "agent"


class AgentEntrypoint(StrictModel):
    type: Literal["loop", "flow"] = "loop"
    loop: Identifier | None = "react"
    flow: Identifier | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class AgentSandboxConfig(StrictModel):
    # A request to the host, never an authorization to exceed host policy.
    network: Literal["none", "unrestricted"] = "none"


class AgentDefinition(StrictModel):
    name: str
    description: str | None = None
    instructions: Instructions
    # Flow remains an entrypoint kind.  This mode controls only the standard
    # Agent body and is deliberately explicit so a non-empty ``subagents`` list
    # never grants delegation by inference.
    mode: Literal["simple", "fibre", "team"] = "simple"
    models: dict[Identifier, Identifier] = Field(default_factory=dict)
    # Defaults in models do not override a parent's per-Run selection. Use this
    # explicit map when this Agent must select a different route as a child.
    delegation_model_bindings: dict[Identifier, Identifier] = Field(
        default_factory=dict
    )
    entrypoint: AgentEntrypoint = Field(default_factory=AgentEntrypoint)
    tools: tuple[ToolName, ...] = ()
    tool_approval: ToolApprovalConfig | None = None
    skills: tuple[SkillName, ...] = ()
    preload_skills: tuple[SkillName, ...] = ()
    subagents: tuple[Identifier, ...] = ()
    budgets: AgentBudgets = Field(default_factory=AgentBudgets)
    memory: AgentMemoryBehavior = Field(default_factory=AgentMemoryBehavior)
    sandbox: AgentSandboxConfig = Field(default_factory=AgentSandboxConfig)

    @model_validator(mode="after")
    def validate_preload_skills(self) -> "AgentDefinition":
        outside = set(self.preload_skills) - set(self.skills)
        if outside:
            raise ValueError(f"preload_skills must be a subset of skills: {sorted(outside)}")
        return self


class ApplicationEntrypoint(StrictModel):
    agent: Identifier | None = None
    flow: Identifier | None = None

    @model_validator(mode="after")
    def exactly_one_target(self) -> "ApplicationEntrypoint":
        if (self.agent is None) == (self.flow is None):
            raise ValueError("entrypoint requires exactly one of agent or flow")
        return self

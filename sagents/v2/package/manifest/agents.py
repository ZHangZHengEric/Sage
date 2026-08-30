"""Agent declarations and package entrypoints."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from sagents.v2.contracts.common import Identifier, SkillName, StrictModel, ToolName


class Instructions(StrictModel):
    inline: str | None = None
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


class AgentMemoryBehavior(StrictModel):
    recall: bool = False
    auto_write: bool = False
    scope: str = "agent"


class AgentEntrypoint(StrictModel):
    type: Literal["loop", "flow"] = "loop"
    loop: Identifier | None = "react"
    flow: Identifier | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class AgentDefinition(StrictModel):
    name: str
    description: str | None = None
    instructions: Instructions
    # Flow remains an entrypoint kind.  This mode controls only the standard
    # Agent body and is deliberately explicit so a non-empty ``subagents`` list
    # never grants delegation by inference.
    mode: Literal["simple", "fibre", "team"] = "simple"
    models: dict[Identifier, Identifier] = Field(default_factory=dict)
    entrypoint: AgentEntrypoint = Field(default_factory=AgentEntrypoint)
    tools: tuple[ToolName, ...] = ()
    skills: tuple[SkillName, ...] = ()
    subagents: tuple[Identifier, ...] = ()
    budgets: AgentBudgets = Field(default_factory=AgentBudgets)
    memory: AgentMemoryBehavior = Field(default_factory=AgentMemoryBehavior)


class ApplicationEntrypoint(StrictModel):
    agent: Identifier | None = None
    flow: Identifier | None = None

    @model_validator(mode="after")
    def exactly_one_target(self) -> "ApplicationEntrypoint":
        if (self.agent is None) == (self.flow is None):
            raise ValueError("entrypoint requires exactly one of agent or flow")
        return self

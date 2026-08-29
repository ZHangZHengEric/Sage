"""SAgents V2 module for testing/contracts.py."""

from __future__ import annotations

from pydantic import Field

from sagents.v2.contracts.commands import InputItem, RunConfig
from sagents.v2.contracts.common import Identifier, StrictModel, ToolName
from sagents.v2.contracts.events import RuntimeEvent
from sagents.v2.contracts.run_state import RunResult, RunState


class ScenarioInteractionReply(StrictModel):
    decision: str
    payload: dict = Field(default_factory=dict)


class ScenarioExpectation(StrictModel):
    outcome: RunState = RunState.COMPLETED
    required_event_types: tuple[str, ...] = ()
    forbidden_event_types: tuple[str, ...] = ()
    final_text_contains: tuple[str, ...] = ()
    required_tool_names: tuple[ToolName, ...] = ()
    max_tool_calls: int | None = Field(default=None, ge=0)
    max_steps: int | None = Field(default=None, ge=0)


class ScenarioDefinition(StrictModel):
    scenario_id: Identifier
    agent_id: Identifier
    input: tuple[InputItem, ...]
    resolved_spec_hash: str
    config: RunConfig = Field(default_factory=RunConfig)
    interactions: tuple[ScenarioInteractionReply, ...] = ()
    expectation: ScenarioExpectation = Field(default_factory=ScenarioExpectation)
    timeout_seconds: float = Field(default=30, gt=0)


class ScenarioResult(StrictModel):
    scenario_id: Identifier
    passed: bool
    failures: tuple[str, ...] = ()
    run_result: RunResult | None = None
    events: tuple[RuntimeEvent, ...] = ()
    duration_seconds: float = Field(ge=0)


class ScenarioSuiteReport(StrictModel):
    passed: bool
    passed_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    results: tuple[ScenarioResult, ...]

"""Serializable definition-independent execution state for FlowRuntime."""

from __future__ import annotations

from enum import Enum
from typing import Any, Protocol

from pydantic import Field

from sagents.v2.contracts.common import Identifier, StrictModel
from sagents.v2.contracts.errors import RuntimeErrorInfo
from sagents.v2.contracts.principals import RequestContext


class FlowNodeOutcome(str, Enum):
    COMPLETED = "completed"
    SUSPENDED = "suspended"
    FAILED = "failed"


class FlowNodeContext(StrictModel):
    session_id: Identifier
    run_id: Identifier
    flow_id: Identifier
    flow_execution_id: Identifier
    node_id: Identifier
    node_execution_id: Identifier
    node_type: Identifier
    config: dict[str, Any] = Field(default_factory=dict)
    prior_results: dict[str, Any] = Field(default_factory=dict)
    request_context: RequestContext


class FlowNodeResult(StrictModel):
    outcome: FlowNodeOutcome = FlowNodeOutcome.COMPLETED
    output: dict[str, Any] = Field(default_factory=dict)
    error: RuntimeErrorInfo | None = None


class FlowFrameState(StrictModel):
    """Suspended parent frame while a nested subflow is active."""

    flow_id: Identifier
    flow_execution_id: Identifier
    current_node_id: Identifier
    parent_node_id: Identifier
    parent_node_execution_id: Identifier
    completed_node_ids: tuple[Identifier, ...] = ()
    results: dict[Identifier, dict[str, Any]] = Field(default_factory=dict)
    visit_counts: dict[Identifier, int] = Field(default_factory=dict)
    pending_interaction_id: Identifier | None = None
    pending_child_run_id: Identifier | None = None
    pending_node_execution_id: Identifier | None = None


class FlowExecutionState(StrictModel):
    """Checkpoint payload for one Flow execution, including nested frames."""

    state_version: str = "1"
    flow_id: Identifier
    flow_execution_id: Identifier
    current_node_id: Identifier
    completed_node_ids: tuple[Identifier, ...] = ()
    results: dict[Identifier, dict[str, Any]] = Field(default_factory=dict)
    visit_counts: dict[Identifier, int] = Field(default_factory=dict)
    pending_interaction_id: Identifier | None = None
    pending_child_run_id: Identifier | None = None
    pending_node_execution_id: Identifier | None = None
    subflow_stack: tuple[FlowFrameState, ...] = ()


class RunnableNode(Protocol):
    """Host-injected body for Agent or Tool Flow nodes."""

    async def run(self, context: FlowNodeContext) -> FlowNodeResult: ...

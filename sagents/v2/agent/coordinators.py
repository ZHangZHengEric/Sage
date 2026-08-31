# pyright: strict
"""Focused orchestration objects extracted from the Agent loop facade."""

from __future__ import annotations

from typing import Protocol

from sagents.v2.agent.state import AgentLoopCheckpointState
from sagents.v2.contracts.principals import RequestContext
from sagents.v2.contracts.run_state import RunSnapshot
from sagents.v2.model.contracts import ModelRequest, ModelResponse
from sagents.v2.tool.contracts import ToolCall, ToolExecutionResult


class _AgentCoordinatorEngine(Protocol):
    """Narrow engine surface consumed by the extracted coordinators."""

    async def execute_coordinated(
        self, run_id: str, context: RequestContext
    ) -> RunSnapshot: ...

    async def resume_coordinated(
        self, run_id: str, context: RequestContext
    ) -> RunSnapshot: ...

    async def stream_model_step(
        self,
        run: RunSnapshot,
        request: ModelRequest,
        context: RequestContext,
        state: AgentLoopCheckpointState,
        step_id: str,
    ) -> tuple[RunSnapshot, ModelResponse | None, RunSnapshot | None]: ...

    async def dispatch_tool_call(
        self,
        run: RunSnapshot,
        call: ToolCall,
        context: RequestContext,
        turn_id: str,
        step_id: str | None = None,
        state: AgentLoopCheckpointState | None = None,
    ) -> tuple[RunSnapshot, ToolExecutionResult | None]: ...

    async def commit_safe_point_suspension(
        self,
        run: RunSnapshot,
        state: AgentLoopCheckpointState,
        context: RequestContext,
    ) -> RunSnapshot: ...


class AgentRunCoordinator:
    """Own the ordered start/resume entrypoints for one logical Agent run."""

    def __init__(self, engine: _AgentCoordinatorEngine) -> None:
        self.engine = engine

    async def execute(self, run_id: str, context: RequestContext) -> RunSnapshot:
        return await self.engine.execute_coordinated(run_id, context)

    async def resume(self, run_id: str, context: RequestContext) -> RunSnapshot:
        return await self.engine.resume_coordinated(run_id, context)


class ModelStepExecutor:
    """Own model request streaming and response accounting for one step."""

    def __init__(self, engine: _AgentCoordinatorEngine) -> None:
        self.engine = engine

    async def execute(
        self,
        run: RunSnapshot,
        request: ModelRequest,
        context: RequestContext,
        state: AgentLoopCheckpointState,
        step_id: str,
    ) -> tuple[RunSnapshot, ModelResponse | None, RunSnapshot | None]:
        return await self.engine.stream_model_step(
            run, request, context, state, step_id
        )


class ToolCallCoordinator:
    """Own proposal, approval, execution, reconciliation, and delegation."""

    def __init__(self, engine: _AgentCoordinatorEngine) -> None:
        self.engine = engine

    async def dispatch(
        self,
        run: RunSnapshot,
        call: ToolCall,
        context: RequestContext,
        turn_id: str,
        step_id: str | None = None,
        state: AgentLoopCheckpointState | None = None,
    ) -> tuple[RunSnapshot, ToolExecutionResult | None]:
        return await self.engine.dispatch_tool_call(
            run, call, context, turn_id, step_id=step_id, state=state
        )


class RunControlCoordinator:
    """Own steer/pause/resume/interaction checkpoint boundaries."""

    def __init__(self, engine: _AgentCoordinatorEngine) -> None:
        self.engine = engine

    async def suspend_at_safe_point(
        self,
        run: RunSnapshot,
        state: AgentLoopCheckpointState,
        context: RequestContext,
    ) -> RunSnapshot:
        return await self.engine.commit_safe_point_suspension(run, state, context)

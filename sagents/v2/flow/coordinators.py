# pyright: strict
"""Focused Flow node, parallel branch, and subflow coordinators."""

from __future__ import annotations

from typing import Protocol, TypeAlias

from sagents.v2.contracts.principals import RequestContext
from sagents.v2.contracts.run_state import RunSnapshot
from sagents.v2.flow.contracts import (
    FlowExecutionState,
    FlowFrameState,
    FlowNodeResult,
)
from sagents.v2.package.manifest.flows import FlowDefinition, FlowNode


ActiveFlowState: TypeAlias = FlowExecutionState | FlowFrameState


class _FlowCoordinatorRuntime(Protocol):
    """Narrow runtime surface consumed by Flow coordination objects."""

    async def invoke_node(
        self,
        run: RunSnapshot,
        state: ActiveFlowState,
        node: FlowNode,
        context: RequestContext,
        *,
        node_execution_id: str | None = None,
        resumed: bool = False,
    ) -> tuple[FlowNodeResult, str]: ...

    async def run_parallel_branches(
        self,
        run: RunSnapshot,
        flow: FlowDefinition,
        root_state: FlowExecutionState,
        state: ActiveFlowState,
        node: FlowNode,
        context: RequestContext,
    ) -> tuple[RunSnapshot, FlowExecutionState]: ...

    async def enter_subflow(
        self,
        run: RunSnapshot,
        state: FlowExecutionState,
        active: ActiveFlowState,
        node: FlowNode,
        context: RequestContext,
    ) -> tuple[RunSnapshot, FlowExecutionState]: ...

    async def exit_subflow(
        self,
        run: RunSnapshot,
        state: FlowExecutionState,
        child: FlowFrameState,
        context: RequestContext,
    ) -> tuple[RunSnapshot, FlowExecutionState]: ...


class FlowNodeExecutor:
    def __init__(self, runtime: _FlowCoordinatorRuntime) -> None:
        self.runtime = runtime

    async def invoke(
        self,
        run: RunSnapshot,
        state: ActiveFlowState,
        node: FlowNode,
        context: RequestContext,
        *,
        node_execution_id: str | None = None,
        resumed: bool = False,
    ) -> tuple[FlowNodeResult, str]:
        return await self.runtime.invoke_node(
            run,
            state,
            node,
            context,
            node_execution_id=node_execution_id,
            resumed=resumed,
        )


class ParallelBranchCoordinator:
    def __init__(self, runtime: _FlowCoordinatorRuntime) -> None:
        self.runtime = runtime

    async def run(
        self,
        run: RunSnapshot,
        flow: FlowDefinition,
        root_state: FlowExecutionState,
        state: ActiveFlowState,
        node: FlowNode,
        context: RequestContext,
    ) -> tuple[RunSnapshot, FlowExecutionState]:
        return await self.runtime.run_parallel_branches(
            run, flow, root_state, state, node, context
        )


class SubflowCoordinator:
    def __init__(self, runtime: _FlowCoordinatorRuntime) -> None:
        self.runtime = runtime

    async def enter(
        self,
        run: RunSnapshot,
        state: FlowExecutionState,
        active: ActiveFlowState,
        node: FlowNode,
        context: RequestContext,
    ) -> tuple[RunSnapshot, FlowExecutionState]:
        return await self.runtime.enter_subflow(
            run, state, active, node, context
        )

    async def exit(
        self,
        run: RunSnapshot,
        state: FlowExecutionState,
        child: FlowFrameState,
        context: RequestContext,
    ) -> tuple[RunSnapshot, FlowExecutionState]:
        return await self.runtime.exit_subflow(run, state, child, context)

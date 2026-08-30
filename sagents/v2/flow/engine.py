"""Checkpointable deterministic graph driver sharing the Native Run kernel."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping

from sagents.v2.contracts.checkpoint import (
    Checkpoint,
    Suspension,
    SuspensionReason,
)
from sagents.v2.contracts.commands import CancelRun, ReplyInteraction
from sagents.v2.contracts.common import new_id, utc_now
from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)
from sagents.v2.contracts.events import FlowEventData, RunEventData
from sagents.v2.contracts.interactions import (
    BlockingScope,
    InteractionRequest,
    InteractionType,
)
from sagents.v2.contracts.principals import RequestContext
from sagents.v2.contracts.run_state import (
    RunSnapshot,
    RunState,
    TERMINAL_RUN_STATES,
)
from sagents.v2.flow.contracts import (
    FlowExecutionState,
    FlowFrameState,
    FlowNodeContext,
    FlowNodeOutcome,
    FlowNodeResult,
    ParallelBranchState,
    PendingParallelState,
    RunnableNode,
)
from sagents.v2.runtime.contracts import RuntimePort
from sagents.v2.package.manifest.flows import FlowDefinition
from sagents.v2.runtime.session.contracts import EventDraft
from sagents.v2.i18n import (
    error_recovery_payload,
    localize_error,
    normalize_language,
    tr,
)


ConditionEvaluator = Callable[[str, FlowExecutionState, str], bool]


class FlowRuntime:
    """Checkpointable graph runtime sharing the native Run/Event/Interaction kernel."""

    def __init__(
        self,
        *,
        runtime: RuntimePort,
        flows: Mapping[str, FlowDefinition],
        agent_nodes: Mapping[str, RunnableNode],
        tool_nodes: Mapping[str, RunnableNode] | None = None,
        condition_evaluator: ConditionEvaluator | None = None,
        clock: Callable = utc_now,
        max_node_visits: int = 100,
    ) -> None:
        if max_node_visits < 1:
            raise ValueError("max_node_visits must be positive")
        self.runtime = runtime
        self.flows = dict(flows)
        self.agent_nodes = dict(agent_nodes)
        self.tool_nodes = dict(tool_nodes or {})
        self.condition_evaluator = condition_evaluator or self._default_condition
        self.clock = clock
        self.max_node_visits = max_node_visits

    async def execute(
        self, run_id: str, flow_id: str, context: RequestContext
    ) -> RunSnapshot:
        """Start a versioned Flow definition inside an accepted Run."""

        flow = self._flow(flow_id)
        run = await self.runtime.get_run(run_id)
        if run.state == RunState.QUEUED:
            run = await self.runtime.start_execution(
                run_id=run_id,
                expected_revision=run.revision,
                context=context,
                idempotency_key=f"flow-start-run:{run_id}",
            )
        if run.state != RunState.RUNNING:
            raise self._error(
                "flow.run_not_runnable",
                ErrorCategory.CONFLICT,
                f"run is {run.state.value}, not running",
            )
        execution_id = new_id("flow_execution")
        state = FlowExecutionState(
            flow_id=flow_id,
            flow_execution_id=execution_id,
            current_node_id=flow.start,
        )
        run = await self._commit(
            run,
            context,
            (
                EventDraft(
                    type="flow.started",
                    flow_execution_id=execution_id,
                    data=FlowEventData(state="started", flow_id=flow_id),
                ),
            ),
        )
        return await self._drive(run, flow, state, context)

    async def resume(self, run_id: str, context: RequestContext) -> RunSnapshot:
        """Restore the active frame and settle its pending dependency."""

        run = await self.runtime.get_run(run_id)
        if run.state != RunState.RESUMING or run.suspension_id is None:
            raise self._error(
                "flow.run_not_resuming",
                ErrorCategory.CONFLICT,
                "flow run must be resuming",
            )
        suspension = await self.runtime.session_store.get_suspension(run.suspension_id)
        checkpoint = await self.runtime.session_store.get_checkpoint(
            suspension.checkpoint_id
        )
        if checkpoint.checkpoint_codec_version not in {"flow/1", "flow/2"}:
            raise self._error(
                "flow.checkpoint_incompatible",
                ErrorCategory.UNSUPPORTED_SCHEMA,
                "checkpoint is not a FlowRuntime checkpoint",
            )
        state = FlowExecutionState.model_validate(checkpoint.state)
        flow = self._flow(state.flow_id)
        run = await self.runtime.mark_resumed(
            run_id=run_id,
            expected_revision=run.revision,
            context=context,
            idempotency_key=f"flow-resumed:{suspension.suspension_id}:{suspension.expected_revision}",
        )
        active = self._active_view(state)
        if active.pending_interaction_id is None:
            return await self._drive(run, flow, state, context)
        resolution = await self.runtime.session_store.get_interaction_resolution(
            active.pending_interaction_id
        )
        if active.pending_error is not None:
            if resolution.decision == "cancel":
                await self.runtime.cancel_run(
                    CancelRun(
                        run_id=run.run_id,
                        expected_revision=run.revision,
                        idempotency_key=(
                            f"flow-error-cancel:{active.pending_interaction_id}"
                        ),
                        reason="interaction_cancelled",
                    ),
                    context,
                )
                return await self.runtime.get_run(run.run_id)
            results = dict(active.results)
            if resolution.payload:
                results[f"{active.current_node_id}__recovery"] = {
                    "decision": resolution.decision,
                    "payload": resolution.payload,
                }
            active = active.model_copy(
                update={
                    "results": results,
                    "pending_interaction_id": None,
                    "pending_error": None,
                }
            )
            state = self._apply_active(state, active)
            return await self._drive(run, flow, state, context)
        if active.pending_child_run_id is not None:
            child = await self.runtime.get_run(active.pending_child_run_id)
            if child.state != RunState.SUSPENDED or child.suspension_id is None:
                return await self._fail(
                    run,
                    state,
                    RuntimeErrorInfo(
                        code="flow.child_interaction_state_changed",
                        category=ErrorCategory.CONFLICT,
                        message="delegated child interaction is no longer pending",
                        safe_to_resume=True,
                    ),
                    context,
                )
            child_suspension = await self.runtime.session_store.get_suspension(
                child.suspension_id
            )
            if child_suspension.interaction_id is None:
                return await self._fail(
                    run,
                    state,
                    RuntimeErrorInfo(
                        code="flow.child_interaction_missing",
                        category=ErrorCategory.CORRUPT_STATE,
                        message="delegated child suspension has no interaction",
                    ),
                    context,
                )
            child_interaction = await self.runtime.session_store.get_interaction(
                child_suspension.interaction_id
            )
            receipt = await self.runtime.reply_interaction(
                ReplyInteraction(
                    run_id=child.run_id,
                    suspension_id=child_suspension.suspension_id,
                    interaction_id=child_interaction.interaction_id,
                    expected_revision=child.revision,
                    expected_suspension_revision=child_suspension.expected_revision,
                    expected_interaction_revision=child_interaction.expected_revision,
                    decision=resolution.decision,
                    payload=resolution.payload,
                    idempotency_key=(
                        f"flow-child-proxy:{run.run_id}:"
                        f"{active.pending_interaction_id}:{resolution.decision}"
                    ),
                ),
                context,
            )
            if receipt.decision.value == "rejected":
                return await self._fail(
                    run,
                    state,
                    receipt.error
                    or RuntimeErrorInfo(
                        code="flow.child_interaction_rejected",
                        category=ErrorCategory.CONFLICT,
                        message="delegated child rejected the proxied interaction",
                        safe_to_resume=True,
                    ),
                    context,
                )
            active = active.model_copy(update={"pending_interaction_id": None})
            state = self._apply_active(state, active)
            return await self._drive(run, flow, state, context)
        node_id = active.current_node_id
        node_execution_id = active.pending_node_execution_id or new_id("node_execution")
        results = dict(active.results)
        results[node_id] = {
            "decision": resolution.decision,
            "payload": resolution.payload,
        }
        completed = (*active.completed_node_ids, node_id)
        active = active.model_copy(
            update={
                "results": results,
                "completed_node_ids": completed,
                "pending_interaction_id": None,
                "pending_node_execution_id": None,
            }
        )
        state = self._apply_active(state, active)
        run = await self._commit(
            run,
            context,
            (
                EventDraft(
                    type="flow.node.resumed",
                    flow_execution_id=active.flow_execution_id,
                    node_execution_id=node_execution_id,
                    data=FlowEventData(
                        state="resumed", flow_id=active.flow_id, node_id=node_id
                    ),
                ),
                EventDraft(
                    type="flow.node.completed",
                    flow_execution_id=active.flow_execution_id,
                    node_execution_id=node_execution_id,
                    data=FlowEventData(
                        state="completed", flow_id=active.flow_id, node_id=node_id
                    ),
                ),
            ),
        )
        try:
            active_flow = self._flow(active.flow_id)
            next_node, edge = self._select_edge(active_flow, node_id, active)
        except SageV2Error as exc:
            return await self._fail(run, state, exc.info, context)
        if next_node == "end":
            if state.subflow_stack:
                active = active.model_copy(update={"current_node_id": "end"})
                state = self._apply_active(state, active)
                return await self._drive(run, flow, state, context)
            return await self._complete(run, state, context)
        active = active.model_copy(update={"current_node_id": next_node})
        state = self._apply_active(state, active)
        run = await self._record_edge(run, active, edge, context)
        return await self._drive(run, flow, state, context)

    async def _drive(self, run, flow, state, context):
        """Advance nodes and edges until completion or durable suspension.

        `FlowDefinition` is immutable configuration; `FlowExecutionState` is the
        checkpointed cursor/results stack. Keeping them separate lets the same
        graph run concurrently without shared mutable node state.
        """

        while run.state == RunState.RUNNING:
            current = await self.runtime.get_run(run.run_id)
            if current.state == RunState.SUSPEND_REQUESTED:
                return await self._suspend_manual(current, state, context)
            if current.state in TERMINAL_RUN_STATES:
                return current
            run = current
            active = self._active_view(state)
            # The active view is either the root state or the top subflow frame.
            # Parent frames remain frozen until the child reaches `end`.
            active_flow = self._flow(active.flow_id)
            nodes = {node.id: node for node in active_flow.nodes}
            node_id = active.current_node_id
            if node_id == "end":
                if state.subflow_stack:
                    run, state = await self._exit_subflow(run, state, active, context)
                    continue
                return await self._complete(run, state, context)
            node = nodes.get(node_id)
            if node is None:
                return await self._fail(
                    run,
                    state,
                    RuntimeErrorInfo(
                        code="flow.node_not_found",
                        category=ErrorCategory.CORRUPT_STATE,
                        message=f"node {node_id!r} is missing",
                    ),
                    context,
                )
            visits = dict(active.visit_counts)
            # Visit budgets make cycles explicit and prevent an invalid graph or
            # condition evaluator from becoming an unbounded runtime loop.
            visits[node_id] = visits.get(node_id, 0) + 1
            if visits[node_id] > self.max_node_visits:
                return await self._fail(
                    run,
                    state,
                    RuntimeErrorInfo(
                        code="flow.visit_budget_exhausted",
                        category=ErrorCategory.VALIDATION,
                        message=f"node {node_id!r} exceeded visit budget",
                        safe_to_resume=True,
                    ),
                    context,
                )
            active = active.model_copy(update={"visit_counts": visits})
            state = self._apply_active(state, active)
            if node.type == "interaction":
                return await self._suspend_interaction(
                    run, state, active, node, context
                )
            if node.type == "parallel":
                try:
                    run, state = await self._run_parallel(
                        run, active_flow, state, active, node, context
                    )
                    if run.state != RunState.RUNNING:
                        return run
                except SageV2Error as exc:
                    return await self._fail(run, state, exc.info, context)
            elif node.type in {"join", "end"}:
                run, active = await self._record_simple_node(run, active, node, context)
                state = self._apply_active(state, active)
            elif node.type == "subflow":
                try:
                    run, state = await self._enter_subflow(
                        run, state, active, node, context
                    )
                    continue
                except SageV2Error as exc:
                    return await self._fail(run, state, exc.info, context)
            else:
                try:
                    output, node_execution_id = await self._invoke_node(
                        run,
                        active,
                        node,
                        context,
                        node_execution_id=active.pending_node_execution_id,
                        resumed=active.pending_node_execution_id is not None,
                    )
                    if output.outcome == FlowNodeOutcome.SUSPENDED:
                        return await self._suspend_child_dependency(
                            run,
                            state,
                            active,
                            node,
                            output,
                            context,
                            node_execution_id,
                        )
                    if output.outcome == FlowNodeOutcome.FAILED:
                        return await self._fail(
                            run,
                            state,
                            output.error
                            or RuntimeErrorInfo(
                                code="flow.node_failed",
                                category=ErrorCategory.PROVIDER_PERMANENT,
                                message=f"node {node.id!r} failed",
                            ),
                            context,
                        )
                    run, active = await self._record_node_result(
                        run,
                        active,
                        node,
                        output,
                        context,
                        node_execution_id=node_execution_id,
                    )
                    state = self._apply_active(state, active)
                except SageV2Error as exc:
                    return await self._fail(run, state, exc.info, context)
                except Exception as exc:
                    return await self._fail(
                        run,
                        state,
                        RuntimeErrorInfo(
                            code="flow.node_provider_error",
                            category=ErrorCategory.PROVIDER_PERMANENT,
                            message=str(exc),
                        ),
                        context,
                    )
            try:
                active = self._active_view(state)
                next_node, edge = self._select_edge(active_flow, node_id, active)
            except SageV2Error as exc:
                return await self._fail(run, state, exc.info, context)
            if next_node == "end":
                if state.subflow_stack:
                    active = active.model_copy(update={"current_node_id": "end"})
                    state = self._apply_active(state, active)
                    continue
                return await self._complete(run, state, context)
            active = active.model_copy(update={"current_node_id": next_node})
            state = self._apply_active(state, active)
            run = await self._record_edge(run, active, edge, context)
        return run

    async def _invoke_node(
        self,
        run,
        state,
        node,
        context,
        *,
        node_execution_id=None,
        resumed=False,
    ):
        if node.type == "agent":
            runner = self.agent_nodes.get(node.agent or "")
        elif node.type == "tool":
            runner = self.tool_nodes.get(node.tool or "")
        else:
            runner = None
        if runner is None:
            raise self._error(
                "flow.runner_not_found",
                ErrorCategory.VALIDATION,
                f"no runner for {node.type} node {node.id!r}",
            )
        node_execution_id = node_execution_id or new_id("node_execution")
        await self._commit(
            run,
            context,
            (
                EventDraft(
                    type="flow.node.resumed" if resumed else "flow.node.started",
                    flow_execution_id=state.flow_execution_id,
                    node_execution_id=node_execution_id,
                    data=FlowEventData(
                        state="resumed" if resumed else "started",
                        flow_id=state.flow_id,
                        node_id=node.id,
                    ),
                ),
            ),
        )
        output = await runner.run(
            FlowNodeContext(
                session_id=run.session_id,
                run_id=run.run_id,
                flow_id=state.flow_id,
                flow_execution_id=state.flow_execution_id,
                node_id=node.id,
                node_execution_id=node_execution_id,
                node_type=node.type,
                config=node.config,
                prior_results=state.results,
                request_context=context,
            )
        )
        return output, node_execution_id

    async def _record_node_result(
        self,
        run,
        state,
        node,
        output,
        context,
        *,
        node_execution_id=None,
    ):
        # A node runner may have committed its own domain events. Refresh the CAS
        # revision before committing the flow lifecycle fact.
        run = await self.runtime.get_run(run.run_id)
        results = dict(state.results)
        results[node.id] = output.output
        completed = (*state.completed_node_ids, node.id)
        state = state.model_copy(
            update={
                "results": results,
                "completed_node_ids": completed,
                "pending_child_run_id": None,
                "pending_node_execution_id": None,
            }
        )
        run = await self._commit(
            run,
            context,
            (
                EventDraft(
                    type="flow.node.completed",
                    flow_execution_id=state.flow_execution_id,
                    node_execution_id=node_execution_id or new_id("node_execution"),
                    data=FlowEventData(
                        state="completed", flow_id=state.flow_id, node_id=node.id
                    ),
                ),
            ),
        )
        return run, state

    async def _record_simple_node(self, run, state, node, context):
        node_execution_id = new_id("node_execution")
        run = await self._commit(
            run,
            context,
            (
                EventDraft(
                    type="flow.node.started",
                    flow_execution_id=state.flow_execution_id,
                    node_execution_id=node_execution_id,
                    data=FlowEventData(
                        state="started", flow_id=state.flow_id, node_id=node.id
                    ),
                ),
            ),
        )
        return await self._record_node_result(
            run,
            state,
            node,
            FlowNodeResult(output={}),
            context,
            node_execution_id=node_execution_id,
        )

    async def _run_parallel(self, run, flow, root_state, state, node, context):
        """Run or resume a parallel batch without losing suspended branches."""

        branch_ids = tuple(node.config.get("branches") or ())
        if not branch_ids:
            raise self._error(
                "flow.parallel_branches_missing",
                ErrorCategory.VALIDATION,
                f"parallel node {node.id!r} has no branches",
            )
        node_map = {value.id: value for value in flow.nodes}
        branch_nodes = []
        for branch_id in branch_ids:
            branch = node_map.get(branch_id)
            if branch is None or branch.type not in {"agent", "tool"}:
                raise self._error(
                    "flow.parallel_branch_invalid",
                    ErrorCategory.VALIDATION,
                    f"parallel branch {branch_id!r} must be an agent/tool node",
                )
            runner = (
                self.agent_nodes.get(branch.agent or "")
                if branch.type == "agent"
                else self.tool_nodes.get(branch.tool or "")
            )
            if runner is None:
                raise self._error(
                    "flow.runner_not_found",
                    ErrorCategory.VALIDATION,
                    f"parallel branch {branch.id!r} has no runner",
                )
            branch_nodes.append(branch)

        pending = state.pending_parallel
        changed: tuple[ParallelBranchState, ...]
        if pending is None:
            execution_ids = {
                branch.id: new_id("node_execution") for branch in branch_nodes
            }
            pending = PendingParallelState(
                node_id=node.id,
                node_execution_id=new_id("node_execution"),
            )
            run = await self._commit(
                run,
                context,
                (
                    EventDraft(
                        type="flow.node.started",
                        flow_execution_id=state.flow_execution_id,
                        node_execution_id=pending.node_execution_id,
                        data=FlowEventData(
                            state="started", flow_id=state.flow_id, node_id=node.id
                        ),
                    ),
                    *(
                        EventDraft(
                            type="flow.node.started",
                            flow_execution_id=state.flow_execution_id,
                            node_execution_id=execution_ids[branch.id],
                            data=FlowEventData(
                                state="started",
                                flow_id=state.flow_id,
                                node_id=branch.id,
                            ),
                        )
                        for branch in branch_nodes
                    ),
                ),
            )

            async def invoke(branch):
                runner = (
                    self.agent_nodes[branch.agent or ""]
                    if branch.type == "agent"
                    else self.tool_nodes[branch.tool or ""]
                )
                return await runner.run(
                    FlowNodeContext(
                        session_id=run.session_id,
                        run_id=run.run_id,
                        flow_id=state.flow_id,
                        flow_execution_id=state.flow_execution_id,
                        node_id=branch.id,
                        node_execution_id=execution_ids[branch.id],
                        node_type=branch.type,
                        config=branch.config,
                        prior_results=state.results,
                        request_context=context,
                    )
                )

            raw_results = await asyncio.gather(
                *(invoke(branch) for branch in branch_nodes),
                return_exceptions=True,
            )
            changed = tuple(
                self._parallel_branch_state(
                    branch.id, execution_ids[branch.id], raw_result
                )
                for branch, raw_result in zip(
                    branch_nodes, raw_results, strict=True
                )
            )
            pending = pending.model_copy(update={"branches": changed})
        else:
            if pending.node_id != node.id:
                raise self._error(
                    "flow.parallel_checkpoint_mismatch",
                    ErrorCategory.CORRUPT_STATE,
                    "parallel checkpoint belongs to a different node",
                )
            active_child = state.pending_child_run_id
            branch_state = next(
                (
                    value
                    for value in pending.branches
                    if (
                        value.outcome == FlowNodeOutcome.SUSPENDED
                        and value.child_run_id == active_child
                    )
                    or (
                        active_child is None
                        and value.outcome == FlowNodeOutcome.FAILED
                    )
                ),
                None,
            )
            if branch_state is None:
                raise self._error(
                    "flow.parallel_active_branch_missing",
                    ErrorCategory.CORRUPT_STATE,
                    "parallel checkpoint has no matching active child branch",
                )
            branch = node_map[branch_state.node_id]
            run = await self._commit(
                run,
                context,
                (
                    EventDraft(
                        type="flow.node.resumed",
                        flow_execution_id=state.flow_execution_id,
                        node_execution_id=branch_state.node_execution_id,
                        data=FlowEventData(
                            state="resumed",
                            flow_id=state.flow_id,
                            node_id=branch.id,
                        ),
                    ),
                ),
            )
            runner = (
                self.agent_nodes[branch.agent or ""]
                if branch.type == "agent"
                else self.tool_nodes[branch.tool or ""]
            )
            try:
                raw_result = await runner.run(
                    FlowNodeContext(
                        session_id=run.session_id,
                        run_id=run.run_id,
                        flow_id=state.flow_id,
                        flow_execution_id=state.flow_execution_id,
                        node_id=branch.id,
                        node_execution_id=branch_state.node_execution_id,
                        node_type=branch.type,
                        config=branch.config,
                        prior_results=state.results,
                        request_context=context,
                    )
                )
            except Exception as exc:  # every started branch gets a durable outcome
                raw_result = exc
            replacement = self._parallel_branch_state(
                branch.id, branch_state.node_execution_id, raw_result
            )
            changed = (replacement,)
            pending = pending.model_copy(
                update={
                    "branches": tuple(
                        replacement if value.node_id == branch.id else value
                        for value in pending.branches
                    )
                }
            )

        run = await self.runtime.get_run(run.run_id)
        run = await self._commit(
            run,
            context,
            tuple(
                self._parallel_outcome_draft(state, branch_state)
                for branch_state in changed
            ),
        )
        state = state.model_copy(
            update={
                "pending_parallel": pending,
                "pending_child_run_id": None,
                "pending_interaction_id": None,
                "pending_node_execution_id": None,
            }
        )
        root_state = self._apply_active(root_state, state)

        suspended = next(
            (
                value
                for value in pending.branches
                if value.outcome == FlowNodeOutcome.SUSPENDED
            ),
            None,
        )
        if suspended is not None:
            branch = node_map[suspended.node_id]
            return (
                await self._suspend_child_dependency(
                    run,
                    root_state,
                    state,
                    branch,
                    FlowNodeResult(
                        outcome=FlowNodeOutcome.SUSPENDED,
                        output=suspended.output,
                        error=suspended.error,
                    ),
                    context,
                    suspended.node_execution_id,
                    emit_lifecycle_event=False,
                ),
                root_state,
            )

        failed = next(
            (
                value
                for value in pending.branches
                if value.outcome == FlowNodeOutcome.FAILED
            ),
            None,
        )
        if failed is not None:
            return (
                await self._fail(
                    run,
                    root_state,
                    failed.error
                    or RuntimeErrorInfo(
                        code="flow.parallel_branch_failed",
                        category=ErrorCategory.PROVIDER_PERMANENT,
                        message=f"parallel branch {failed.node_id!r} failed",
                    ),
                    context,
                ),
                root_state,
            )

        results = dict(state.results)
        completed = list(state.completed_node_ids)
        for branch_state in pending.branches:
            results[branch_state.node_id] = branch_state.output
            if branch_state.node_id not in completed:
                completed.append(branch_state.node_id)
        results[node.id] = {"branches": list(branch_ids)}
        if node.id not in completed:
            completed.append(node.id)
        state = state.model_copy(
            update={
                "results": results,
                "completed_node_ids": tuple(completed),
                "pending_parallel": None,
            }
        )
        root_state = self._apply_active(root_state, state)
        run = await self._commit(
            run,
            context,
            (
                EventDraft(
                    type="flow.node.completed",
                    flow_execution_id=state.flow_execution_id,
                    node_execution_id=pending.node_execution_id,
                    data=FlowEventData(
                        state="completed", flow_id=state.flow_id, node_id=node.id
                    ),
                ),
            ),
        )
        return run, root_state

    @staticmethod
    def _parallel_branch_state(node_id, node_execution_id, raw_result):
        if isinstance(raw_result, FlowNodeResult):
            child_run_id = raw_result.output.get("child_run_id")
            return ParallelBranchState(
                node_id=node_id,
                node_execution_id=node_execution_id,
                outcome=raw_result.outcome,
                output=raw_result.output,
                error=raw_result.error,
                child_run_id=(
                    child_run_id
                    if isinstance(child_run_id, str) and child_run_id
                    else None
                ),
            )
        message = str(raw_result) or raw_result.__class__.__name__
        return ParallelBranchState(
            node_id=node_id,
            node_execution_id=node_execution_id,
            outcome=FlowNodeOutcome.FAILED,
            error=RuntimeErrorInfo(
                code="flow.parallel_branch_provider_error",
                category=ErrorCategory.PROVIDER_PERMANENT,
                message=message,
            ),
        )

    @staticmethod
    def _parallel_outcome_draft(state, branch_state):
        return EventDraft(
            type=f"flow.node.{branch_state.outcome.value}",
            flow_execution_id=state.flow_execution_id,
            node_execution_id=branch_state.node_execution_id,
            data=FlowEventData(
                state=branch_state.outcome.value,
                flow_id=state.flow_id,
                node_id=branch_state.node_id,
                error=branch_state.error,
            ),
        )

    async def _enter_subflow(self, run, state, active, node, context):
        """Push the parent frame and begin a child Flow with its own execution id."""

        subflow = self._flow(node.flow or "")
        if len(state.subflow_stack) >= self.max_node_visits:
            raise self._error(
                "flow.subflow_depth_exhausted",
                ErrorCategory.VALIDATION,
                "subflow nesting exceeded the configured safety budget",
            )
        node_execution_id = new_id("node_execution")
        child_execution_id = new_id("flow_execution")
        run = await self._commit(
            run,
            context,
            (
                EventDraft(
                    type="flow.node.started",
                    flow_execution_id=active.flow_execution_id,
                    node_execution_id=node_execution_id,
                    data=FlowEventData(
                        state="started", flow_id=active.flow_id, node_id=node.id
                    ),
                ),
                EventDraft(
                    type="flow.started",
                    flow_execution_id=child_execution_id,
                    data=FlowEventData(state="started", flow_id=node.flow),
                ),
            ),
        )
        frame = FlowFrameState(
            flow_id=node.flow,
            flow_execution_id=child_execution_id,
            current_node_id=subflow.start,
            parent_node_id=node.id,
            parent_node_execution_id=node_execution_id,
        )
        return run, state.model_copy(
            update={"subflow_stack": (*state.subflow_stack, frame)}
        )

    async def _exit_subflow(self, run, state, child, context):
        """Pop a completed child frame and publish its result to the parent node."""

        parent_node_id = child.parent_node_id
        parent_execution_id = child.parent_node_execution_id
        parent_state = state.model_copy(
            update={"subflow_stack": state.subflow_stack[:-1]}
        )
        parent = self._active_view(parent_state)
        results = dict(parent.results)
        results[parent_node_id] = {
            "flow_id": child.flow_id,
            "version": self._flow(child.flow_id).version,
            "results": child.results,
        }
        parent = parent.model_copy(
            update={
                "results": results,
                "completed_node_ids": (*parent.completed_node_ids, parent_node_id),
            }
        )
        parent_state = self._apply_active(parent_state, parent)
        run = await self._commit(
            run,
            context,
            (
                EventDraft(
                    type="flow.completed",
                    flow_execution_id=child.flow_execution_id,
                    data=FlowEventData(state="completed", flow_id=child.flow_id),
                ),
                EventDraft(
                    type="flow.node.completed",
                    flow_execution_id=parent.flow_execution_id,
                    node_execution_id=parent_execution_id,
                    data=FlowEventData(
                        state="completed",
                        flow_id=parent.flow_id,
                        node_id=parent_node_id,
                    ),
                ),
            ),
        )
        parent_flow = self._flow(parent.flow_id)
        next_node, edge = self._select_edge(parent_flow, parent_node_id, parent)
        parent = parent.model_copy(update={"current_node_id": next_node})
        parent_state = self._apply_active(parent_state, parent)
        if next_node != "end":
            run = await self._record_edge(run, parent, edge, context)
        return run, parent_state

    @staticmethod
    def _active_view(state):
        return state.subflow_stack[-1] if state.subflow_stack else state

    @staticmethod
    def _apply_active(state, active):
        if state.subflow_stack:
            return state.model_copy(
                update={"subflow_stack": (*state.subflow_stack[:-1], active)}
            )
        return state.model_copy(
            update={
                "flow_id": active.flow_id,
                "current_node_id": active.current_node_id,
                "completed_node_ids": active.completed_node_ids,
                "results": active.results,
                "visit_counts": active.visit_counts,
                "pending_interaction_id": active.pending_interaction_id,
                "pending_child_run_id": active.pending_child_run_id,
                "pending_node_execution_id": active.pending_node_execution_id,
                "pending_error": active.pending_error,
                "pending_parallel": active.pending_parallel,
            }
        )

    async def _suspend_interaction(self, run, state, active, node, context):
        """Persist an Interaction node and checkpoint the exact Flow cursor."""

        interaction_id = new_id("interaction")
        node_execution_id = new_id("node_execution")
        active = active.model_copy(
            update={
                "pending_interaction_id": interaction_id,
                "pending_node_execution_id": node_execution_id,
            }
        )
        state = self._apply_active(state, active)
        checkpoint_id = new_id("checkpoint")
        checkpoint = Checkpoint(
            checkpoint_id=checkpoint_id,
            checkpoint_codec_version="flow/2",
            session_id=run.session_id,
            run_id=run.run_id,
            run_sequence=run.last_run_sequence,
            session_revision=(
                await self.runtime.session_store.get_session(run.session_id)
            ).revision,
            state=state.model_dump(mode="json"),
            resolved_spec_hash=run.resolved_spec_hash,
            created_at=self.clock(),
        )
        payload = dict(node.config.get("payload") or {"node_id": node.id})
        payload.setdefault("title", tr("approval.title", context.language))
        payload.setdefault("prompt", tr("approval.guidance", context.language))
        payload.setdefault("guidance", tr("approval.guidance", context.language))
        payload.setdefault("language", normalize_language(context.language))
        interaction = InteractionRequest(
            interaction_id=interaction_id,
            run_id=run.run_id,
            interaction_type=InteractionType.APPROVAL,
            blocking_scope=BlockingScope(node.blocking_scope or "run"),
            allowed_decisions=tuple(
                node.config.get("allowed_decisions") or ("approve", "deny")
            ),
            eligible_principal_ids=(context.actor.principal_id,),
            payload=payload,
            requested_at=self.clock(),
        )
        suspension = Suspension(
            suspension_id=new_id("suspension"),
            run_id=run.run_id,
            reason=SuspensionReason.APPROVAL_REQUIRED,
            blocking_scope=node.blocking_scope or "run",
            checkpoint_id=checkpoint_id,
            checkpoint_sequence=run.last_run_sequence,
            interaction_id=interaction_id,
            resume_policy="after_interaction_resolution",
            requested_at=self.clock(),
        )
        run = await self._commit(
            run,
            context,
            (
                EventDraft(
                    type="flow.node.started",
                    flow_execution_id=active.flow_execution_id,
                    node_execution_id=node_execution_id,
                    data=FlowEventData(
                        state="started", flow_id=active.flow_id, node_id=node.id
                    ),
                ),
                EventDraft(
                    type="flow.node.suspended",
                    flow_execution_id=active.flow_execution_id,
                    node_execution_id=node_execution_id,
                    data=FlowEventData(
                        state="suspended", flow_id=active.flow_id, node_id=node.id
                    ),
                ),
            ),
        )
        return await self.runtime.commit_suspension(
            run_id=run.run_id,
            expected_revision=run.revision,
            checkpoint=checkpoint.model_copy(
                update={"run_sequence": run.last_run_sequence}
            ),
            suspension=suspension,
            interaction=interaction,
            context=context,
            idempotency_key=f"flow-interaction:{interaction_id}",
        )

    async def _suspend_child_dependency(
        self,
        run,
        state,
        active,
        node,
        output,
        context,
        node_execution_id,
        *,
        emit_lifecycle_event=True,
    ):
        """Keep the same node execution pending while its child Run is suspended."""

        # _invoke_node commits its lifecycle start/resume event before calling
        # the runner, so refresh the parent CAS revision before suspension.
        run = await self.runtime.get_run(run.run_id)
        child_run_id = output.output.get("child_run_id")
        if not isinstance(child_run_id, str) or not child_run_id:
            return await self._fail(
                run,
                state,
                RuntimeErrorInfo(
                    code="flow.suspended_node_missing_child_run",
                    category=ErrorCategory.CORRUPT_STATE,
                    message="suspended Agent Flow node did not identify its child run",
                    safe_to_resume=False,
                ),
                context,
            )
        child = await self.runtime.get_run(child_run_id)
        proxy_interaction = None
        parent_interaction_id = None
        if child.state == RunState.SUSPENDED and child.suspension_id is not None:
            child_suspension = await self.runtime.session_store.get_suspension(
                child.suspension_id
            )
            if child_suspension.interaction_id is not None:
                child_interaction = await self.runtime.session_store.get_interaction(
                    child_suspension.interaction_id
                )
                parent_interaction_id = new_id("interaction")
                proxy_interaction = InteractionRequest(
                    interaction_id=parent_interaction_id,
                    run_id=run.run_id,
                    interaction_type=child_interaction.interaction_type,
                    blocking_scope=BlockingScope.RUN,
                    allowed_decisions=child_interaction.allowed_decisions,
                    eligible_principal_ids=(context.actor.principal_id,),
                    payload={
                        **child_interaction.payload,
                        "delegated": True,
                        "child_run_id": child_run_id,
                        "child_interaction_id": child_interaction.interaction_id,
                    },
                    requested_at=self.clock(),
                )
        active = active.model_copy(
            update={
                "pending_child_run_id": child_run_id,
                "pending_interaction_id": parent_interaction_id,
                "pending_node_execution_id": node_execution_id,
            }
        )
        state = self._apply_active(state, active)
        checkpoint_id = new_id("checkpoint")
        checkpoint = Checkpoint(
            checkpoint_id=checkpoint_id,
            checkpoint_codec_version="flow/2",
            session_id=run.session_id,
            run_id=run.run_id,
            run_sequence=run.last_run_sequence,
            session_revision=(
                await self.runtime.session_store.get_session(run.session_id)
            ).revision,
            state=state.model_dump(mode="json"),
            resolved_spec_hash=run.resolved_spec_hash,
            created_at=self.clock(),
        )
        suspension = Suspension(
            suspension_id=new_id("suspension"),
            run_id=run.run_id,
            reason=(
                SuspensionReason.INPUT_REQUIRED
                if proxy_interaction is not None
                else SuspensionReason.RESOURCE_WAIT
            ),
            blocking_scope=node.blocking_scope or "node",
            checkpoint_id=checkpoint_id,
            checkpoint_sequence=run.last_run_sequence,
            interaction_id=parent_interaction_id,
            resume_policy=(
                "after_interaction_resolution"
                if proxy_interaction is not None
                else "after_child_run_terminal"
            ),
            requested_at=self.clock(),
        )
        if emit_lifecycle_event:
            run = await self._commit(
                run,
                context,
                (
                    EventDraft(
                        type="flow.node.suspended",
                        flow_execution_id=active.flow_execution_id,
                        node_execution_id=node_execution_id,
                        data=FlowEventData(
                            state="suspended",
                            flow_id=active.flow_id,
                            node_id=node.id,
                        ),
                    ),
                ),
            )
        session = await self.runtime.session_store.get_session(run.session_id)
        return await self.runtime.commit_suspension(
            run_id=run.run_id,
            expected_revision=run.revision,
            checkpoint=checkpoint.model_copy(
                update={
                    "run_sequence": run.last_run_sequence,
                    "session_revision": session.revision,
                }
            ),
            suspension=suspension,
            interaction=proxy_interaction,
            context=context,
            idempotency_key=(
                f"flow-child-wait:{run.run_id}:{child_run_id}:{node_execution_id}"
            ),
        )

    async def _suspend_manual(self, run, state, context):
        checkpoint_id = new_id("checkpoint")
        checkpoint = Checkpoint(
            checkpoint_id=checkpoint_id,
            checkpoint_codec_version="flow/2",
            session_id=run.session_id,
            run_id=run.run_id,
            run_sequence=run.last_run_sequence,
            session_revision=(
                await self.runtime.session_store.get_session(run.session_id)
            ).revision,
            state=state.model_dump(mode="json"),
            resolved_spec_hash=run.resolved_spec_hash,
            created_at=self.clock(),
        )
        suspension = Suspension(
            suspension_id=new_id("suspension"),
            run_id=run.run_id,
            reason=SuspensionReason.MANUAL_PAUSE,
            blocking_scope="run",
            checkpoint_id=checkpoint_id,
            checkpoint_sequence=run.last_run_sequence,
            resume_policy="explicit_resume",
            requested_at=self.clock(),
        )
        return await self.runtime.commit_suspension(
            run_id=run.run_id,
            expected_revision=run.revision,
            checkpoint=checkpoint,
            suspension=suspension,
            context=context,
            idempotency_key=f"flow-pause:{suspension.suspension_id}",
        )

    def _select_edge(self, flow, node_id, state):
        candidates = sorted(
            (edge for edge in flow.edges if edge.source == node_id),
            key=lambda edge: (-edge.priority, edge.target),
        )
        matching = [
            edge
            for edge in candidates
            if edge.when is None or self.condition_evaluator(edge.when, state, node_id)
        ]
        if not matching:
            raise self._error(
                "flow.no_edge_selected",
                ErrorCategory.VALIDATION,
                f"no edge selected after node {node_id!r}",
            )
        if len(matching) > 1 and matching[0].priority == matching[1].priority:
            raise self._error(
                "flow.edge_ambiguous",
                ErrorCategory.CONFLICT,
                f"multiple equal-priority edges match after node {node_id!r}",
            )
        return matching[0].target, matching[0]

    async def _record_edge(self, run, state, edge, context):
        return await self._commit(
            run,
            context,
            (
                EventDraft(
                    type="flow.edge.selected",
                    flow_execution_id=state.flow_execution_id,
                    data=FlowEventData(
                        state="selected",
                        flow_id=state.flow_id,
                        edge_id=f"{edge.source}:{edge.target}",
                        decided_by="flow",
                    ),
                ),
            ),
        )

    async def _complete(self, run, state, context):
        result = await self.runtime.session_store.commit_run(
            run_id=run.run_id,
            expected_revision=run.revision,
            expected_states={RunState.RUNNING},
            new_state=RunState.COMPLETED,
            drafts=(
                EventDraft(
                    type="flow.completed",
                    flow_execution_id=state.flow_execution_id,
                    data=FlowEventData(state="completed", flow_id=state.flow_id),
                ),
                EventDraft(type="run.completed", data=RunEventData(state="completed")),
            ),
            context=context,
            idempotency_key=f"flow-complete:{state.flow_execution_id}",
        )
        return result.run

    async def _fail(self, run, state, error, context):
        error = localize_error(error, context.language)
        current = await self.runtime.get_run(run.run_id)
        if current.state in TERMINAL_RUN_STATES:
            return current
        resumable = error.safe_to_resume or error.retryable
        if current.state == RunState.RUNNING and resumable:
            return await self._suspend_for_error_recovery(
                current, state, error, context
            )
        error = error.model_copy(
            update={
                "metadata": {
                    **error.metadata,
                    "recovery_questionnaire": error_recovery_payload(
                        error, context.language, resumable=False
                    ),
                }
            }
        )
        active = self._active_view(state)
        result = await self.runtime.session_store.commit_run(
            run_id=current.run_id,
            expected_revision=current.revision,
            expected_states={
                RunState.RUNNING,
                RunState.SUSPEND_REQUESTED,
                RunState.RESUMING,
            },
            new_state=RunState.FAILED,
            drafts=(
                EventDraft(
                    type="flow.node.failed",
                    flow_execution_id=active.flow_execution_id,
                    data=FlowEventData(
                        state="failed",
                        flow_id=active.flow_id,
                        node_id=active.current_node_id,
                        error=error,
                    ),
                ),
                EventDraft(
                    type="run.failed", data=RunEventData(state="failed", error=error)
                ),
            ),
            context=context,
            idempotency_key=f"flow-fail:{state.flow_execution_id}:{error.code}",
        )
        return result.run

    async def _suspend_for_error_recovery(self, run, state, error, context):
        active = self._active_view(state)
        interaction_id = new_id("interaction")
        node_execution_id = active.pending_node_execution_id or new_id(
            "node_execution"
        )
        active = active.model_copy(
            update={
                "pending_interaction_id": interaction_id,
                "pending_node_execution_id": node_execution_id,
                "pending_error": error.model_dump(mode="json"),
            }
        )
        state = self._apply_active(state, active)
        run = await self._commit(
            run,
            context,
            (
                EventDraft(
                    type="flow.node.suspended",
                    flow_execution_id=active.flow_execution_id,
                    node_execution_id=node_execution_id,
                    data=FlowEventData(
                        state="error_recovery",
                        flow_id=active.flow_id,
                        node_id=active.current_node_id,
                        error=error,
                    ),
                ),
            ),
        )
        checkpoint_id = new_id("checkpoint")
        checkpoint = Checkpoint(
            checkpoint_id=checkpoint_id,
            checkpoint_codec_version="flow/2",
            session_id=run.session_id,
            run_id=run.run_id,
            run_sequence=run.last_run_sequence,
            session_revision=(
                await self.runtime.session_store.get_session(run.session_id)
            ).revision,
            state=state.model_dump(mode="json"),
            resolved_spec_hash=run.resolved_spec_hash,
            created_at=self.clock(),
        )
        interaction = InteractionRequest(
            interaction_id=interaction_id,
            run_id=run.run_id,
            interaction_type=InteractionType.USER_INPUT,
            blocking_scope=BlockingScope.RUN,
            allowed_decisions=("retry", "change_direction", "cancel"),
            eligible_principal_ids=(context.actor.principal_id,),
            payload=error_recovery_payload(
                error, context.language, resumable=True
            ),
            requested_at=self.clock(),
        )
        suspension = Suspension(
            suspension_id=new_id("suspension"),
            run_id=run.run_id,
            reason=SuspensionReason.INPUT_REQUIRED,
            blocking_scope=BlockingScope.RUN,
            checkpoint_id=checkpoint_id,
            checkpoint_sequence=run.last_run_sequence,
            interaction_id=interaction_id,
            resume_policy="after_interaction_resolution",
            requested_at=self.clock(),
        )
        return await self.runtime.commit_suspension(
            run_id=run.run_id,
            expected_revision=run.revision,
            checkpoint=checkpoint,
            suspension=suspension,
            interaction=interaction,
            context=context,
            idempotency_key=f"flow-error-suspend:{interaction_id}",
        )

    async def _commit(self, run, context, drafts):
        result = await self.runtime.session_store.commit_run(
            run_id=run.run_id,
            expected_revision=run.revision,
            expected_states={RunState.RUNNING},
            new_state=RunState.RUNNING,
            drafts=drafts,
            context=context,
            idempotency_key=new_id("flow_commit"),
        )
        return result.run

    def _flow(self, flow_id):
        try:
            return self.flows[flow_id]
        except KeyError as exc:
            raise self._error(
                "flow.not_found",
                ErrorCategory.VALIDATION,
                f"flow {flow_id!r} is not registered",
            ) from exc

    @staticmethod
    def _default_condition(expression, state, node_id):
        value = expression.strip().lower()
        if value in {"true", "always"}:
            return True
        result = state.results.get(node_id, {})
        if value == "approved":
            return str(result.get("decision", "")).startswith("approve")
        if value == "denied":
            return str(result.get("decision", "")) in {"deny", "denied", "reject"}
        if "==" in expression:
            key, expected = (part.strip() for part in expression.split("==", 1))
            return str(result.get(key)) == expected.strip("'\"")
        return bool(result.get(expression))

    @staticmethod
    def _error(code, category, message, *, safe_to_resume=False):
        return SageV2Error(
            RuntimeErrorInfo(
                code=code,
                category=category,
                message=message,
                safe_to_resume=safe_to_resume,
            )
        )

"""Checkpointable single-Agent model/tool execution loop.

The Loop owns Step orchestration, not durable storage or provider behavior. It
asks Context, Model, Tool, and Policy ports for decisions and records every
observable lifecycle change through `RuntimePort`/`SessionStore`.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from collections.abc import Callable

from sagents.v2.agent.state import AgentLoopCheckpointCodec, AgentLoopCheckpointState
from sagents.v2.agent.stream_batcher import StreamEventBatcher
from sagents.v2.model.contracts import (
    ModelEventKind,
    ModelMessage,
    ModelToolCall,
)
from sagents.v2.agent.step_request import (
    AgentStepRequestBuilder,
    DefaultAgentStepRequestBuilder,
    tools_for_invocation_mode,
)
from sagents.v2.context import ContextAssembler, DefaultContextAssembler
from sagents.v2.context.session_history import (
    RunLedgerRebuilder,
    SessionHistoryLedgerBuilder,
)
from sagents.v2.memory import (
    DirectMemoryRecallQueryGenerator,
    MemoryRecallQueryGenerator,
)
from sagents.v2.model.provider import ModelProvider
from sagents.v2.agent.policy.continuation import (
    CompositeContinuationPolicy,
    ContinuationAction,
    ContinuationContext,
    ContinuationPolicy,
    ContinuationSignalProvider,
    ContinuationSignals,
    ContinuationDecision,
    InteractionDraft,
)
from sagents.v2.agent.policy.approval_memory import (
    REMEMBER_DECISION,
    ApprovalMemory,
    RememberedApproval,
)
from sagents.v2.agent.policy.tool_policy import (
    DefaultToolPolicy,
    ToolPolicyAction,
    ToolPolicyContext,
)
from sagents.v2.tool.contracts import (
    CancelSemantics,
    ReconcileResult,
    ReconcileState,
    SideEffectLevel,
    ToolCall,
    ToolCancellationState,
    ToolExecutionResult,
)
from sagents.v2.tool.provider import ToolCatalog, ToolExecutor
from sagents.v2.tool.plugins.selection_recent import RecentToolSelectionPolicy
from sagents.v2.tool.selection import (
    ToolSelectionPolicy,
    ToolSelectionPrepareContext,
)
from sagents.v2.contracts.checkpoint import (
    Checkpoint,
    Suspension,
    SuspensionReason,
)
from sagents.v2.contracts.common import new_id, utc_now
from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)
from sagents.v2.contracts.events import (
    ContinuationEventData,
    ItemEventData,
    PolicyEventData,
    RunEventData,
    StepEventData,
    ToolEventData,
    TurnEventData,
    UsageEventData,
    EventSource,
    EventSourceType,
)
from sagents.v2.contracts.interactions import (
    BlockingScope,
    InteractionRequest,
    InteractionType,
)
from sagents.v2.contracts.items import (
    ItemSnapshot,
    ItemStatus,
    JsonBlock,
    MessageItemData,
    ReasoningItemData,
    TextBlock,
    ToolCallItemData,
    ToolResultItemData,
)
from sagents.v2.contracts.principals import RequestContext
from sagents.v2.contracts.run_state import (
    RunSnapshot,
    RunState,
    TERMINAL_RUN_STATES,
)
from sagents.v2.contracts.commands import CancelRun, InputItem
from sagents.v2.runtime.contracts import RuntimePort
from sagents.v2.runtime.session.contracts import EventDraft
from sagents.v2.i18n import (
    error_recovery_payload,
    localize_error,
    normalize_language,
    recovery_payload,
    tr,
)


class AgentLoopEngine:
    # V1 Fibre retries transient provider failures inside the logical model
    # request. V2 keeps that behavior narrowly scoped to a response that
    # contained no usable semantic fields, where replay cannot duplicate a
    # Tool call or other external side effect.
    _MAX_TRANSPARENT_EMPTY_RESPONSE_RETRIES = 2

    """Composable model/tool loop with durable, resumable side-effect barriers."""

    def __init__(
        self,
        *,
        runtime: RuntimePort,
        model: ModelProvider,
        tool_catalog: ToolCatalog,
        tool_executor: ToolExecutor,
        tool_policy: DefaultToolPolicy | None = None,
        approval_memory: ApprovalMemory | None = None,
        tool_selection_policy: ToolSelectionPolicy | None = None,
        continuation_policy: ContinuationPolicy | None = None,
        continuation_signal_provider: ContinuationSignalProvider | None = None,
        context_assembler: ContextAssembler | None = None,
        step_request_builder: AgentStepRequestBuilder | None = None,
        ledger_rebuilder: RunLedgerRebuilder | None = None,
        automatic_memory_recall: bool = False,
        memory_recall_limit: int = 5,
        memory_recall_query_generator: MemoryRecallQueryGenerator | None = None,
        tool_selection_model: ModelProvider | None = None,
        delegated_run_controller=None,
        expected_resolved_spec_hash: str | None = None,
        clock: Callable = utc_now,
    ) -> None:
        self.runtime = runtime
        self.model = model
        self.tool_catalog = tool_catalog
        self.tool_executor = tool_executor
        self.tool_policy = tool_policy or DefaultToolPolicy()
        # 审批记忆：没有端口时 approve_and_remember 只等价于 approve_once。
        self.approval_memory = approval_memory
        self.tool_selection_policy = (
            tool_selection_policy or RecentToolSelectionPolicy()
        )
        self.tool_selection_model = tool_selection_model or model
        self.continuation_policy = continuation_policy or CompositeContinuationPolicy()
        self.continuation_signal_provider = continuation_signal_provider
        self.context_assembler = context_assembler or DefaultContextAssembler(
            history_reader=runtime.session_store
        )
        self.step_request_builder = (
            step_request_builder
            or DefaultAgentStepRequestBuilder(
                context_assembler=self.context_assembler,
                tool_catalog=self.tool_catalog,
                tool_selection_policy=self.tool_selection_policy,
                token_estimator=getattr(self.context_assembler, "estimator", None),
                context_budget=getattr(self.context_assembler, "budget", None),
            )
        )
        self.ledger_rebuilder = ledger_rebuilder or SessionHistoryLedgerBuilder(
            runtime.session_store
        )
        self.automatic_memory_recall = automatic_memory_recall
        self.memory_recall_limit = max(1, min(int(memory_recall_limit), 100))
        self.memory_recall_query_generator = (
            memory_recall_query_generator or DirectMemoryRecallQueryGenerator()
        )
        self.delegated_run_controller = delegated_run_controller
        self.expected_resolved_spec_hash = expected_resolved_spec_hash
        self.clock = clock
        from sagents.v2.runtime.lifecycle import DurableRunLifecycle

        self.lifecycle = DurableRunLifecycle(runtime)

    async def execute(self, run_id: str, context: RequestContext) -> RunSnapshot:
        return await self.execute_coordinated(run_id, context)

    async def execute_coordinated(
        self, run_id: str, context: RequestContext
    ) -> RunSnapshot:
        """Start the first Turn for a newly accepted Run."""

        run = await self.runtime.get_run(run_id)
        self._assert_resolved_spec_compatible(run.resolved_spec_hash)
        if run.state == RunState.QUEUED:
            run = await self.runtime.start_execution(
                run_id=run_id,
                expected_revision=run.revision,
                context=context,
                idempotency_key=f"loop-start:{run_id}",
            )
        if run.state != RunState.RUNNING:
            raise self._conflict(
                "loop.run_not_runnable", f"run is {run.state.value}, not running"
            )
        command = await self.runtime.session_store.get_start_command(run_id)
        context = self._context_for_command(context, command)
        turn_id = new_id("turn")
        messages = await self.context_assembler.initial_ledger(
            command, run_id=run.run_id
        )
        state = AgentLoopCheckpointState(
            turn_id=turn_id,
            step_number=1,
            messages=messages,
            pending_flow_boundary=command.config.flow_boundary,
        )
        run = await self._commit_running(
            run,
            context,
            (
                EventDraft(
                    type="turn.started",
                    turn_id=turn_id,
                    data=TurnEventData(state="started"),
                ),
            ),
        )
        tool_selection_task = asyncio.create_task(
            self._prepare_tool_selection(
                command=command,
                run_id=run_id,
                messages=messages,
                language=context.language,
            )
        )
        try:
            if self.automatic_memory_recall:
                run, state = await self._run_automatic_memory_recall(
                    run, state, command, context
                )
            await tool_selection_task
        except BaseException:
            if not tool_selection_task.done():
                tool_selection_task.cancel()
                await asyncio.gather(tool_selection_task, return_exceptions=True)
            raise
        return await self._drive(run, state, context)

    async def _prepare_tool_selection(
        self, *, command, run_id: str, messages, language: str | None
    ) -> None:
        """Prepare the selected plugin beside Memory Recall, once per Run."""

        catalog_tools = await self.tool_catalog.list_tools(run_id=run_id)
        catalog_tools = tools_for_invocation_mode(
            catalog_tools, command.invocation_mode
        )
        await self.tool_selection_policy.prepare(
            ToolSelectionPrepareContext(
                run_id=run_id,
                tools=catalog_tools,
                messages=messages,
                language=normalize_language(language),
                model=self.tool_selection_model,
            )
        )

    async def _run_automatic_memory_recall(self, run, state, command, context):
        """Run v1-compatible Memory recall as a real Tool input/output pair."""

        latest_user = next(
            (item for item in reversed(command.input) if item.role == "user"), None
        )
        if latest_user is None:
            return run, state
        user_input = "\n".join(
            block.text for block in latest_user.content if isinstance(block, TextBlock)
        ).strip()
        if not user_input:
            return run, state
        query = await self.memory_recall_query_generator.generate(
            user_input, run_id=run.run_id
        )
        if not query.strip():
            return run, state
        try:
            definition = await self.tool_catalog.get_tool(
                "search_memory", run_id=run.run_id
            )
        except SageV2Error as exc:
            if exc.info.code == "tool.not_found":
                return run, state
            raise

        scope = command.config.metadata.get("memory_scope")
        configured_limit = scope.get("limit") if isinstance(scope, dict) else None
        limit = self.memory_recall_limit
        if configured_limit is not None:
            try:
                limit = max(1, min(int(configured_limit), 100))
            except (TypeError, ValueError):
                pass
        model_call = ModelToolCall(
            tool_call_id=new_id("call_memory_recall"),
            name="search_memory",
            arguments={"query": query, "top_k": limit},
        )
        call = ToolCall(
            tool_call_id=model_call.tool_call_id,
            tool_name=model_call.name,
            arguments=model_call.arguments,
            operation_id=new_id("operation"),
            idempotency_key=f"{run.run_id}:automatic-memory-recall",
            owner_run_id=run.run_id,
            owner_agent_id=command.agent_id,
            owner_session_id=run.session_id,
        )
        step_id = new_id("step_memory_recall")
        item_id = new_id("item")
        item = self._item(
            item_id,
            run.run_id,
            state.turn_id,
            step_id,
            ToolCallItemData(
                tool_call_id=model_call.tool_call_id,
                tool_name=model_call.name,
                arguments=model_call.arguments,
            ),
        )
        run = await self._commit_running(
            run,
            context,
            (
                EventDraft(
                    type="step.started",
                    turn_id=state.turn_id,
                    step_id=step_id,
                    data=StepEventData(state="started", attempt=1),
                ),
                EventDraft(
                    type="item.completed",
                    turn_id=state.turn_id,
                    step_id=step_id,
                    item_id=item_id,
                    data=ItemEventData(operation="completed", item=item),
                ),
            ),
        )
        assistant = ModelMessage(
            role="assistant",
            tool_calls=(model_call,),
        )
        state = state.model_copy(update={"messages": (*state.messages, assistant)})
        run = await self._record_tool_proposal(
            run, call, context, state.turn_id, step_id
        )
        policy = await self.tool_policy.decide(
            ToolPolicyContext(
                run_id=run.run_id,
                actor=context.actor,
                definition=definition,
                call=call,
                invocation_mode=command.invocation_mode,
            )
        )
        policy = await self._consult_approval_memory(run, policy)
        run = await self._record_policy(
            run, call, policy, context, state.turn_id, step_id
        )
        if policy.action == ToolPolicyAction.ALLOW:
            run, result = await self._dispatch_tool(
                run, call, context, state.turn_id, step_id, state
            )
            if result is None:
                return run, state
        else:
            reason = (
                policy.reason
                if policy.action == ToolPolicyAction.DENY
                else "automatic memory recall requires approval"
            )
            result = ToolExecutionResult(
                tool_call_id=call.tool_call_id,
                operation_id=call.operation_id,
                content=(TextBlock(text=f"memory recall skipped: {reason}"),),
                error=RuntimeErrorInfo(
                    code="memory.recall_not_authorized",
                    category=ErrorCategory.POLICY_DENIED,
                    message=reason,
                    safe_to_resume=True,
                ),
            )
            run = await self._commit_tool_result(
                run,
                call,
                result,
                context,
                state.turn_id,
                step_id=step_id,
                declined=True,
            )
        state = state.model_copy(
            update={"messages": (*state.messages, self._tool_result_message(result))}
        )
        run = await self._commit_running(
            run,
            context,
            (
                EventDraft(
                    type="step.completed",
                    turn_id=state.turn_id,
                    step_id=step_id,
                    data=StepEventData(state="completed", attempt=1),
                ),
            ),
        )
        return run, state

    async def resume(self, run_id: str, context: RequestContext) -> RunSnapshot:
        return await self.resume_coordinated(run_id, context)

    async def recover_interrupted(
        self, run_id: str, context: RequestContext
    ) -> RunSnapshot | None:
        """Recover a process-lost Tool barrier without replaying the Tool.

        Returns ``None`` when the durable ledger contains no crossed side-effect
        barrier.  In that case the dispatcher may settle the uncheckpointed
        model/control work as resource loss.  Once ``tool.call.started`` exists,
        however, only reconciliation or explicit human resolution is safe.
        """

        run = await self.runtime.get_run(run_id)
        self._assert_resolved_spec_compatible(run.resolved_spec_hash)
        if run.state not in {RunState.RUNNING, RunState.SUSPEND_REQUESTED}:
            return run
        command = await self.runtime.session_store.get_start_command(run_id)
        context = self._context_for_command(context, command)
        events = await self.runtime.session_store.read_events(run_id)
        settled_types = {
            "tool.call.succeeded",
            "tool.call.failed",
            "tool.call.cancelled",
            "tool.call.reconciled",
        }
        settled_operations = {
            event.data.operation_id
            for event in events
            if event.type in settled_types
            and isinstance(event.data, ToolEventData)
            and event.data.operation_id is not None
        }
        started = next(
            (
                event
                for event in reversed(events)
                if event.type == "tool.call.started"
                and isinstance(event.data, ToolEventData)
                and event.data.operation_id not in settled_operations
            ),
            None,
        )
        if started is None:
            return None
        tool_data = started.data
        proposal = next(
            (
                event
                for event in reversed(events)
                if event.type == "tool.call.proposed"
                and isinstance(event.data, ToolEventData)
                and event.data.operation_id == tool_data.operation_id
            ),
            None,
        )
        proposal_missing = proposal is None or proposal.data.arguments is None
        call = ToolCall(
            tool_call_id=tool_data.tool_call_id,
            tool_name=tool_data.tool_name,
            # Dispatch has already crossed the side-effect barrier. A damaged
            # pre-dispatch projection must never turn that into a safe replay.
            arguments={} if proposal_missing else proposal.data.arguments,
            operation_id=tool_data.operation_id,
            idempotency_key=tool_data.idempotency_key,
            owner_run_id=run.run_id,
            owner_agent_id=command.agent_id,
            owner_session_id=run.session_id,
        )
        messages = await self.ledger_rebuilder.rebuild(
            command,
            run_id=run_id,
            through_run_sequence=run.last_run_sequence,
        )
        step_number = next(
            (
                event.data.attempt
                for event in reversed(events)
                if event.type == "step.started"
                and event.step_id == started.step_id
                and isinstance(event.data, StepEventData)
            ),
            1,
        )
        state = AgentLoopCheckpointState(
            turn_id=started.turn_id or new_id("turn"),
            step_number=step_number,
            messages=messages,
            pending_flow_boundary=command.config.flow_boundary,
        )
        try:
            definition = await self.tool_catalog.get_tool(call.tool_name, run_id=run_id)
        except Exception:
            definition = None
        unknown_event = next(
            (
                event
                for event in reversed(events)
                if event.type == "tool.call.unknown"
                and isinstance(event.data, ToolEventData)
                and event.data.operation_id == call.operation_id
            ),
            None,
        )
        uncertainty = (
            RuntimeErrorInfo(
                code="tool.recovery_ledger_incomplete",
                category=ErrorCategory.UNCERTAIN_SIDE_EFFECT,
                message=(
                    "worker restarted after tool dispatch, but the durable "
                    "proposal arguments are unavailable"
                ),
                safe_to_resume=True,
                metadata={
                    "tool_name": call.tool_name,
                    "operation_id": call.operation_id,
                },
            )
            if proposal_missing
            else unknown_event.data.error
            if unknown_event is not None and unknown_event.data.error is not None
            else RuntimeErrorInfo(
                code="tool.outcome_unknown_after_worker_restart",
                category=ErrorCategory.UNCERTAIN_SIDE_EFFECT,
                message=(
                    "worker restarted after tool dispatch; the external outcome "
                    "must be reconciled"
                ),
                safe_to_resume=True,
                metadata={
                    "tool_name": call.tool_name,
                    "operation_id": call.operation_id,
                },
            )
        )
        if unknown_event is None:
            run = await self._record_tool_unknown(
                run,
                call,
                uncertainty,
                context,
                state.turn_id,
                started.step_id,
            )
        if definition is not None and definition.supports_reconciliation:
            run, result = await self._reconcile_or_suspend_tool(
                run,
                call,
                context,
                state.turn_id,
                started.step_id,
                state,
                uncertainty,
            )
            if result is None:
                return run
            state = state.model_copy(
                update={
                    "messages": (
                        *state.messages,
                        self._tool_result_message(result),
                    ),
                    "step_number": state.step_number + 1,
                    "expanded_tool_names": (
                        self.tool_selection_policy.expanded_tools(run.run_id)
                    ),
                }
            )
            run = await self._commit_running(
                run,
                context,
                (
                    EventDraft(
                        type="step.completed",
                        turn_id=state.turn_id,
                        step_id=started.step_id,
                        data=StepEventData(state="completed", attempt=step_number),
                    ),
                ),
            )
            return await self._drive(run, state, context)
        return await self._suspend_for_tool_uncertainty(
            run,
            state,
            call,
            uncertainty,
            context,
            started.step_id,
            definition,
            supports_reconciliation=(
                definition is not None and definition.supports_reconciliation
            ),
        )

    async def resume_coordinated(
        self, run_id: str, context: RequestContext
    ) -> RunSnapshot:
        """Restore a suspended Loop and finish its pending barrier before driving.

        Approval and uncertain-side-effect checkpoints resume differently. An
        approved call may dispatch for the first time; an uncertain call must be
        reconciled or manually resolved and must never be blindly replayed.
        """

        run = await self.runtime.get_run(run_id)
        if run.state != RunState.RESUMING or run.suspension_id is None:
            raise self._conflict(
                "loop.run_not_resuming", "run must be resuming with a suspension"
            )
        suspension = await self.runtime.session_store.get_suspension(run.suspension_id)
        checkpoint = await self.runtime.session_store.get_checkpoint(
            suspension.checkpoint_id
        )
        self._assert_resolved_spec_compatible(
            run.resolved_spec_hash,
            checkpoint_hash=checkpoint.resolved_spec_hash,
        )
        if checkpoint.checkpoint_codec_version not in {
            "agent-loop/1",
            "agent-loop/2",
            "agent-loop/3",
        }:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="loop.checkpoint_incompatible",
                    category=ErrorCategory.UNSUPPORTED_SCHEMA,
                    message="checkpoint is not an Agent Loop checkpoint",
                )
            )
        state = AgentLoopCheckpointCodec.decode(checkpoint.state)
        self.tool_selection_policy.restore_expanded_tools(
            run_id, state.expanded_tool_names
        )
        command = await self.runtime.session_store.get_start_command(run_id)
        context = self._context_for_command(context, command)
        rebuilt_messages = await self.ledger_rebuilder.rebuild(
            command,
            run_id=run_id,
            through_run_sequence=checkpoint.run_sequence,
        )
        rebuilt_digest = self._ledger_digest(rebuilt_messages)
        if state.ledger_digest is not None and state.ledger_digest != rebuilt_digest:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="loop.checkpoint_ledger_mismatch",
                    category=ErrorCategory.CORRUPT_STATE,
                    message=(
                        "canonical Item events do not match the checkpoint ledger "
                        "digest"
                    ),
                    safe_to_resume=False,
                )
            )
        # Old reference checkpoints embedded messages. Prefer canonical events
        # when equivalent, but retain the old payload as a one-time migration
        # fallback if it contains facts (for example old steering input) that
        # were not yet emitted as completed Items.
        if (
            state.state_version == "1"
            and state.messages
            and self._ledger_digest(state.messages) != rebuilt_digest
        ):
            rebuilt_messages = state.messages
        state = state.model_copy(
            update={"messages": rebuilt_messages, "ledger_digest": rebuilt_digest}
        )
        resolution = None
        if suspension.interaction_id is not None:
            resolution = await self.runtime.session_store.get_interaction_resolution(
                suspension.interaction_id
            )
        run = await self.runtime.mark_resumed(
            run_id=run_id,
            expected_revision=run.revision,
            context=context,
            idempotency_key=f"loop-resumed:{suspension.suspension_id}:{suspension.expected_revision}",
        )
        if state.pending_tool_call is not None:
            if suspension.interaction_id is None:
                raise self._conflict(
                    "loop.interaction_missing",
                    "pending approval tool call has no interaction",
                )
            assert resolution is not None
            if state.pending_tool_phase == "delegation_interaction":
                run, result = await self._resume_delegated_tool(
                    run,
                    state,
                    resolution.decision,
                    resolution.payload,
                    context,
                )
                if result is None:
                    return run
            elif state.pending_tool_phase == "reconciliation":
                run, result = await self._resume_uncertain_tool(
                    run,
                    state,
                    resolution.decision,
                    resolution.payload,
                    context,
                )
                if result is None:
                    return run
            else:
                approved = resolution.decision.startswith("approve")
                if resolution.decision == REMEMBER_DECISION:
                    # 先记后跑：记忆记录的是用户的授权决定，与工具结果无关；
                    # remember 是幂等的 set，重放 resume 不会重复。
                    run = await self._remember_tool_approval(
                        run, state, resolution, context
                    )
                if approved:
                    run, result = await self._dispatch_tool(
                        run,
                        state.pending_tool_call,
                        context,
                        state.turn_id,
                        state.pending_tool_step_id,
                        state,
                    )
                    if result is None:
                        return run
                else:
                    declined_error = localize_error(
                        RuntimeErrorInfo(
                            code="tool.declined",
                            category=ErrorCategory.POLICY_DENIED,
                            message=f"tool call declined with {resolution.decision}",
                            message_key="error.tool.declined",
                            safe_to_resume=True,
                        ),
                        context.language,
                    )
                    result = ToolExecutionResult(
                        tool_call_id=state.pending_tool_call.tool_call_id,
                        operation_id=state.pending_tool_call.operation_id,
                        content=(TextBlock(text=declined_error.message),),
                        error=declined_error,
                    )
                    run = await self._commit_tool_result(
                        run,
                        state.pending_tool_call,
                        result,
                        context,
                        state.turn_id,
                        step_id=state.pending_tool_step_id,
                        declined=True,
                    )
            state = state.model_copy(
                update={
                    "messages": (*state.messages, self._tool_result_message(result)),
                    "pending_tool_call": None,
                    "pending_tool_policy": None,
                    "pending_tool_phase": None,
                    "pending_tool_step_id": None,
                    "pending_tool_error": None,
                    "pending_tool_result": None,
                    "pending_child_interactions": (),
                    "expanded_tool_names": (
                        self.tool_selection_policy.expanded_tools(run.run_id)
                    ),
                    "step_number": state.step_number + 1,
                }
            )
        elif suspension.interaction_id is not None and resolution is not None:
            interaction = await self.runtime.session_store.get_interaction(
                suspension.interaction_id
            )
            if interaction.interaction_type == InteractionType.USER_INPUT:
                if resolution.decision == "cancel":
                    await self.runtime.cancel_run(
                        CancelRun(
                            run_id=run.run_id,
                            expected_revision=run.revision,
                            idempotency_key=(
                                f"interaction-cancel:{interaction.interaction_id}"
                            ),
                            reason="interaction_cancelled",
                        ),
                        context,
                    )
                    await self._release_run_resources(run.run_id)
                    return await self.runtime.get_run(run.run_id)
                try:
                    input_items = self._interaction_input_items(
                        resolution.payload,
                        interaction_id=interaction.interaction_id,
                        decision=resolution.decision,
                    )
                except SageV2Error as exc:
                    localized = localize_error(exc.info, context.language)
                    return await self._suspend_for_continuation_interaction(
                        run,
                        state,
                        ContinuationDecision(
                            action=ContinuationAction.REQUEST_INTERACTION,
                            reason_code=exc.info.code,
                            reason=localized.message,
                            interaction=InteractionDraft(
                                interaction_type="interaction_correction",
                                allowed_decisions=("submit", "cancel"),
                                payload={
                                    **recovery_payload(
                                        "recovery.input_prompt",
                                        context.language,
                                        reason_code=exc.info.code,
                                    ),
                                    "error": localized.model_dump(
                                        mode="json", exclude_none=True
                                    ),
                                    "preserve_step_budget": True,
                                },
                            ),
                        ),
                        context,
                        None,
                    )
                if input_items:
                    run = await self._commit_interaction_input(
                        run,
                        state,
                        input_items,
                        interaction.interaction_id,
                        context,
                    )
                    state = state.model_copy(
                        update={
                            "messages": (
                                *state.messages,
                                *(
                                    ModelMessage(
                                        role=item.role,
                                        content=item.content,
                                        metadata=item.metadata,
                                    )
                                    for item in input_items
                                ),
                            )
                        }
                    )
        return await self._drive(run, state, context)

    async def _drive(
        self,
        run: RunSnapshot,
        state: AgentLoopCheckpointState,
        context: RequestContext,
    ) -> RunSnapshot:
        """Run Steps until completion, failure, or a durable suspension.

        Each iteration has five ordered phases: consume control input, construct
        a model request, commit the streamed response, settle tool calls, and ask
        ContinuationPolicy what happens next. Reordering these phases can expose
        uncommitted output or repeat an external side effect after recovery.
        """

        command = await self.runtime.session_store.get_start_command(run.run_id)
        context = self._context_for_command(context, command)
        max_steps = command.config.max_steps or 24
        empty_response_retries = 0
        context_overflow_retries = 0
        additional_input_reserve_tokens = 0
        while run.state == RunState.RUNNING:
            # Phase 1: observe control-plane state only at a safe boundary. A
            # pause never snapshots the middle of arbitrary Python mutation.
            current = await self.runtime.get_run(run.run_id)
            if current.state == RunState.SUSPEND_REQUESTED:
                return await self._suspend_at_safe_point(current, state, context)
            if current.state in TERMINAL_RUN_STATES:
                await self._release_run_resources(run.run_id)
                return current
            run = current
            claimed = await self.runtime.session_store.claim_steers(
                run_id=run.run_id,
                expected_revision=run.revision,
                turn_id=state.turn_id,
                context=context,
            )
            if claimed.entries:
                # Steering is appended to the model ledger in durable inbox
                # order. It is not an Interaction reply and does not resume a
                # suspended Run by itself.
                run = claimed.run
                steering_messages = tuple(
                    ModelMessage(
                        role=item.role,
                        content=item.content,
                        metadata=item.metadata,
                    )
                    for entry in claimed.entries
                    for item in entry.input
                )
                state = state.model_copy(
                    update={"messages": (*state.messages, *steering_messages)}
                )
            step_id = new_id("step")
            run = await self._commit_running(
                run,
                context,
                (
                    EventDraft(
                        type="step.started",
                        turn_id=state.turn_id,
                        step_id=step_id,
                        data=StepEventData(state="started", attempt=state.step_number),
                    ),
                ),
            )
            # Phase 2: ContextAssembler creates the provider-facing projection.
            # The raw ledger and canonical RuntimeEvents are left unchanged.
            prepared_step = await self.step_request_builder.prepare(
                command=command,
                run_id=run.run_id,
                turn_id=state.turn_id,
                step_id=step_id,
                messages=state.messages,
                pending_continuation_reason=state.pending_continuation_reason,
                language=context.language,
                additional_input_reserve_tokens=additional_input_reserve_tokens,
            )
            request = prepared_step.request
            tools = prepared_step.tools
            try:
                # Phase 3: deltas are emitted as replay-buffered events, followed
                # by completed Items that are authoritative for final content.
                run, response, partial_suspension = await self._stream_model(
                    run, request, context, state, step_id
                )
            except SageV2Error as exc:
                if (
                    exc.info.code == "model.context_window_exceeded"
                    and exc.info.retryable
                    and context_overflow_retries == 0
                    and getattr(self.context_assembler, "budget", None) is not None
                ):
                    context_overflow_retries = 1
                    estimated = int(
                        request.metadata.get("request_budget", {}).get(
                            "estimated_input_tokens", 0
                        )
                    )
                    additional_input_reserve_tokens = max(512, estimated // 10)
                    retry_error = exc.info.model_copy(
                        update={
                            "metadata": {
                                **exc.info.metadata,
                                "adaptive_input_reserve_tokens": (
                                    additional_input_reserve_tokens
                                ),
                                "transparent_retry_attempt": 1,
                                "transparent_retry_limit": 1,
                            }
                        }
                    )
                    run = await self._commit_running(
                        run,
                        context,
                        (
                            EventDraft(
                                type="step.retry_scheduled",
                                turn_id=state.turn_id,
                                step_id=step_id,
                                data=StepEventData(
                                    state="retry_scheduled",
                                    attempt=1,
                                    retry_at=self.clock(),
                                    error=retry_error,
                                ),
                            ),
                        ),
                    )
                    continue
                if (
                    exc.info.code == "model.empty_semantic_response"
                    and empty_response_retries
                    < self._MAX_TRANSPARENT_EMPTY_RESPONSE_RETRIES
                ):
                    empty_response_retries += 1
                    retry_error = exc.info.model_copy(
                        update={
                            "retryable": True,
                            "metadata": {
                                **exc.info.metadata,
                                "transparent_retry_attempt": empty_response_retries,
                                "transparent_retry_limit": (
                                    self._MAX_TRANSPARENT_EMPTY_RESPONSE_RETRIES
                                ),
                            },
                        }
                    )
                    run = await self._commit_running(
                        run,
                        context,
                        (
                            EventDraft(
                                type="step.retry_scheduled",
                                turn_id=state.turn_id,
                                step_id=step_id,
                                data=StepEventData(
                                    state="retry_scheduled",
                                    attempt=empty_response_retries,
                                    retry_at=self.clock(),
                                    error=retry_error,
                                ),
                            ),
                        ),
                    )
                    continue
                error = exc.info
                if error.code == "model.empty_semantic_response":
                    error = error.model_copy(
                        update={
                            "retryable": True,
                            "metadata": {
                                **error.metadata,
                                "transparent_retries_exhausted": (
                                    empty_response_retries
                                ),
                            },
                        }
                    )
                return await self._fail(run, state, step_id, error, context)
            except Exception as exc:
                return await self._fail(
                    run,
                    state,
                    step_id,
                    RuntimeErrorInfo(
                        code="model.provider_error",
                        category=ErrorCategory.PROVIDER_PERMANENT,
                        message=str(exc),
                        safe_to_resume=True,
                    ),
                    context,
                )
            if partial_suspension is not None:
                return partial_suspension
            assert response is not None
            empty_response_retries = 0
            context_overflow_retries = 0
            additional_input_reserve_tokens = 0
            messages = state.messages
            # Human-readable reasoning remains a separate canonical Item, while
            # opaque provider continuation state is attached to the assistant
            # ledger entry. Providers such as MiniMax, OpenAI Responses, and
            # Anthropic require that state after a tool call.
            if response.text or response.tool_calls or response.provider_state:
                messages = (
                    *messages,
                    ModelMessage(
                        role="assistant",
                        content=(
                            (TextBlock(text=response.text),) if response.text else ()
                        ),
                        tool_calls=response.tool_calls,
                        provider_state=response.provider_state,
                    ),
                )
            state = state.model_copy(
                update={
                    "messages": messages,
                    "total_input_tokens": state.total_input_tokens
                    + response.usage.input_tokens,
                    "total_output_tokens": state.total_output_tokens
                    + response.usage.output_tokens,
                    "response_fingerprints": (
                        *state.response_fingerprints,
                        self._response_fingerprint(response),
                    ),
                    "retry_model_step": False,
                    "force_tool_choice_required_next": False,
                    "pending_continuation_reason": None,
                }
            )

            if response.tool_calls:
                # Phase 4: proposal and policy decision are committed before any
                # external ToolExecutor receives the call.
                for model_call in response.tool_calls:
                    try:
                        definition = await self.tool_catalog.get_tool(
                            model_call.name, run_id=run.run_id
                        )
                    except SageV2Error as exc:
                        if exc.info.code == "tool.not_found":
                            language = str(
                                command.config.metadata.get("response_language")
                                or context.language
                                or "en"
                            )
                            decision = ContinuationDecision(
                                action=ContinuationAction.REQUEST_INTERACTION,
                                reason_code="tool.not_found",
                                reason=tr("recovery.tool_not_found", language),
                                interaction=InteractionDraft(
                                    interaction_type="agent_recovery",
                                    allowed_decisions=("submit", "cancel"),
                                    payload={
                                        **recovery_payload(
                                            "recovery.tool_not_found",
                                            language,
                                            reason_code="tool.not_found",
                                        ),
                                        "tool_name": model_call.name,
                                    },
                                ),
                            )
                            run = await self._record_continuation(
                                run, decision, context, state.turn_id, step_id
                            )
                            return await self._suspend_for_continuation_interaction(
                                run, state, decision, context, step_id
                            )
                        return await self._fail(run, state, step_id, exc.info, context)
                    tool_call = ToolCall(
                        tool_call_id=model_call.tool_call_id,
                        tool_name=model_call.name,
                        arguments=model_call.arguments,
                        operation_id=new_id("operation"),
                        idempotency_key=f"{run.run_id}:{model_call.tool_call_id}",
                        owner_run_id=run.run_id,
                        owner_agent_id=command.agent_id,
                        owner_session_id=run.session_id,
                    )
                    run = await self._record_tool_proposal(
                        run, tool_call, context, state.turn_id, step_id
                    )
                    policy = await self.tool_policy.decide(
                        ToolPolicyContext(
                            run_id=run.run_id,
                            actor=context.actor,
                            definition=definition,
                            call=tool_call,
                            invocation_mode=command.invocation_mode,
                        )
                    )
                    policy = await self._consult_approval_memory(run, policy)
                    run = await self._record_policy(
                        run, tool_call, policy, context, state.turn_id, step_id
                    )
                    if policy.action == ToolPolicyAction.DENY:
                        denied = localize_error(
                            RuntimeErrorInfo(
                                code="tool.policy_denied",
                                category=ErrorCategory.POLICY_DENIED,
                                message=policy.reason,
                                safe_to_resume=True,
                            ),
                            context.language,
                        )
                        result = ToolExecutionResult(
                            tool_call_id=tool_call.tool_call_id,
                            operation_id=tool_call.operation_id,
                            content=(TextBlock(text=denied.message),),
                            error=denied,
                        )
                        run = await self._commit_tool_result(
                            run,
                            tool_call,
                            result,
                            context,
                            state.turn_id,
                            step_id=step_id,
                            declined=True,
                        )
                        state = state.model_copy(
                            update={
                                "messages": (
                                    *state.messages,
                                    self._tool_result_message(result),
                                )
                            }
                        )
                        continue
                    if policy.action == ToolPolicyAction.REQUIRE_INTERACTION:
                        state = state.model_copy(
                            update={
                                "pending_tool_call": tool_call,
                                "pending_tool_policy": policy,
                                "pending_tool_phase": "approval",
                                "pending_tool_step_id": step_id,
                            }
                        )
                        return await self._suspend_for_tool_approval(
                            run, state, policy, context, step_id
                        )
                    run, result = await self._dispatch_tool(
                        run, tool_call, context, state.turn_id, step_id, state
                    )
                    if result is None:
                        return run
                    state = state.model_copy(
                        update={
                            "messages": (
                                *state.messages,
                                self._tool_result_message(result),
                            ),
                            "expanded_tool_names": (
                                self.tool_selection_policy.expanded_tools(run.run_id)
                            ),
                        }
                    )

            repeated = self._trailing_repeat_count(state.response_fingerprints)
            signals = await self._continuation_signals(run.run_id, state)
            # Phase 5: completion is policy, not an implicit consequence of EOF
            # or a provider finish_reason.
            decision = await self.continuation_policy.decide(
                ContinuationContext(
                    run_id=run.run_id,
                    step_number=state.step_number,
                    max_steps=max_steps,
                    response=response,
                    ledger=state.messages,
                    language=str(
                        command.config.metadata.get("response_language")
                        or context.language
                        or "en"
                    ),
                    agent_system_requirements=self._system_requirements(
                        request.messages
                    ),
                    available_tools=tuple(tool.name for tool in tools),
                    pending_tool_calls=0,
                    repeated_fingerprint_count=repeated,
                    explicit_status=signals.explicit_status,
                    explicit_status_note=signals.explicit_status_note,
                    requested_interaction=signals.interaction,
                    flow_boundary=signals.flow_boundary,
                    elapsed_seconds=max(
                        0.0, (self.clock() - run.created_at).total_seconds()
                    ),
                    deadline_seconds=command.config.deadline_seconds,
                    total_tokens=state.total_input_tokens + state.total_output_tokens,
                    max_total_tokens=(
                        command.config.max_total_tokens
                        or command.config.metadata.get("max_total_tokens")
                    ),
                )
            )
            if decision.usage.input_tokens or decision.usage.output_tokens:
                state = state.model_copy(
                    update={
                        "total_input_tokens": state.total_input_tokens
                        + decision.usage.input_tokens,
                        "total_output_tokens": state.total_output_tokens
                        + decision.usage.output_tokens,
                    }
                )
            run = await self._record_continuation(
                run, decision, context, state.turn_id, step_id
            )
            if decision.reason_code in {"flow.node_complete", "flow.node_continue"}:
                state = state.model_copy(update={"pending_flow_boundary": None})
            if decision.action == ContinuationAction.COMPLETE_RUN:
                return await self._complete(run, state, step_id, context)
            if decision.action == ContinuationAction.FAIL:
                return await self._fail(
                    run,
                    state,
                    step_id,
                    decision.error
                    or RuntimeErrorInfo(
                        code=decision.reason_code,
                        category=ErrorCategory.VALIDATION,
                        message=decision.reason,
                        safe_to_resume=True,
                    ),
                    context,
                )
            if decision.action == ContinuationAction.REQUEST_INTERACTION:
                return await self._suspend_for_continuation_interaction(
                    run, state, decision, context, step_id
                )
            if decision.action in {
                ContinuationAction.COMPLETE_TURN,
                ContinuationAction.HANDOFF,
            }:
                return await self._complete(run, state, step_id, context)
            run = await self._commit_running(
                run,
                context,
                (
                    EventDraft(
                        type="step.completed",
                        turn_id=state.turn_id,
                        step_id=step_id,
                        data=StepEventData(
                            state="completed", attempt=state.step_number
                        ),
                    ),
                ),
            )
            continuation_reason = None
            if (
                decision.action == ContinuationAction.CONTINUE_STEP
                and decision.reason
                and decision.reason_code
                in {
                    "plan.explanation_required",
                    "plan.required",
                    "goal.explanation_required",
                    "goal.incomplete",
                    "judge.continue",
                    "judge.explanation_required",
                    "judge.v1_must_continue",
                }
            ):
                continuation_reason = self._normalized_continuation_reason(
                    decision.reason
                )
            state = state.model_copy(
                update={
                    "step_number": state.step_number + 1,
                    # Kept in the checkpoint schema only for compatibility with
                    # runs created before Tool choice became explicitly auto.
                    "force_tool_choice_required_next": False,
                    "pending_continuation_reason": continuation_reason,
                }
            )
        return run

    @staticmethod
    def _system_requirements(messages: tuple[ModelMessage, ...]) -> str:
        values = []
        for message in messages:
            if message.role not in {"system", "developer"}:
                continue
            values.extend(
                block.text for block in message.content if isinstance(block, TextBlock)
            )
        return "\n".join(value for value in values if value.strip())

    @staticmethod
    def _normalized_continuation_reason(reason: str) -> str | None:
        value = " ".join(str(reason or "").split()).strip()
        if not value:
            return None
        return value[:240].replace("<", "[").replace(">", "]").strip()

    async def _continuation_signals(
        self, run_id: str, state: AgentLoopCheckpointState
    ) -> ContinuationSignals:
        """Resolve typed host/Tool signals without inferring them from text."""

        signals = ContinuationSignals(flow_boundary=state.pending_flow_boundary)
        if self.continuation_signal_provider is None:
            return signals
        external = self.continuation_signal_provider(run_id)
        if inspect.isawaitable(external):
            external = await external
        if not isinstance(external, ContinuationSignals):
            raise TypeError(
                "continuation signal provider must return ContinuationSignals"
            )
        return signals.model_copy(
            update={
                "explicit_status": external.explicit_status,
                "explicit_status_note": external.explicit_status_note,
                "interaction": external.interaction,
                "flow_boundary": external.flow_boundary or signals.flow_boundary,
            }
        )

    async def _stream_model(self, run, request, context, state, step_id):
        return await self.stream_model_step(run, request, context, state, step_id)

    async def _control_aware_model_events(self, stream, run, command):
        """Poll durable control/deadline state without cancelling socket reads."""

        iterator = stream.__aiter__()
        pending = None
        poll_seconds = 0.1
        try:
            while True:
                if pending is None:
                    pending = asyncio.create_task(anext(iterator))
                timeout = poll_seconds
                deadline_expired = False
                if command.config.deadline_seconds is not None:
                    remaining = command.config.deadline_seconds - max(
                        0.0, (self.clock() - run.created_at).total_seconds()
                    )
                    if remaining <= 0:
                        deadline_expired = True
                        timeout = 0
                    else:
                        timeout = min(timeout, remaining)
                done, _ = await asyncio.wait({pending}, timeout=timeout)
                if done:
                    try:
                        event = pending.result()
                    except StopAsyncIteration:
                        return
                    pending = None
                    yield event, None
                    continue
                if deadline_expired:
                    raise SageV2Error(
                        RuntimeErrorInfo(
                            code="budget.deadline",
                            category=ErrorCategory.VALIDATION,
                            message=tr("error.budget.deadline", None),
                            safe_to_resume=True,
                        )
                    )
                current = await self.runtime.get_run(run.run_id)
                if current.state != RunState.RUNNING:
                    yield None, current
                    return
        finally:
            if pending is not None and not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)

    async def stream_model_step(self, run, request, context, state, step_id):
        """Normalize one provider stream into canonical Item lifecycle events.

        A cooperative pause closes the provider stream, commits any visible
        partial Items as SUSPENDED, and checkpoints `retry_model_step=True`.
        Tool execution has not started at this point, so retrying the model Step
        is safe after resume.
        """

        text_item_id = new_id("item")
        reasoning_item_id = new_id("item")
        text = ""
        reasoning = ""
        text_started = False
        reasoning_started = False
        response = None
        stream = self.model.stream(request)
        command = await self.runtime.session_store.get_start_command(run.run_id)
        controlled_events = self._control_aware_model_events(stream, run, command)

        async def commit_delta_batch(batch_run, drafts):
            try:
                return await self._commit_running(batch_run, context, drafts)
            except SageV2Error as exc:
                if exc.info.category != ErrorCategory.CONFLICT:
                    raise
                latest = await self.runtime.get_run(batch_run.run_id)
                if latest.state in TERMINAL_RUN_STATES:
                    return latest
                if latest.state not in {
                    RunState.RUNNING,
                    RunState.SUSPEND_REQUESTED,
                }:
                    raise
                return await self._commit_running(
                    latest,
                    context,
                    drafts,
                    expected_states={latest.state},
                )

        batcher = StreamEventBatcher(run, commit_delta_batch)
        try:
            async for model_event, observed_run in controlled_events:
                current = observed_run or await self.runtime.get_run(run.run_id)
                await batcher.observe_run(current)
                if current.state == RunState.SUSPEND_REQUESTED:
                    run = await batcher.flush()
                    current = await self.runtime.get_run(run.run_id)
                    if text or reasoning:
                        drafts = []
                        if text:
                            drafts.append(
                                self._partial_item_draft(
                                    run.run_id,
                                    state.turn_id,
                                    step_id,
                                    text_item_id,
                                    text,
                                    reasoning=False,
                                )
                            )
                        if reasoning:
                            drafts.append(
                                self._partial_item_draft(
                                    run.run_id,
                                    state.turn_id,
                                    step_id,
                                    reasoning_item_id,
                                    reasoning,
                                    reasoning=True,
                                )
                            )
                        current = await self._commit_running(
                            current,
                            context,
                            tuple(drafts),
                            expected_states={RunState.SUSPEND_REQUESTED},
                        )
                    suspended = await self._suspend_at_safe_point(
                        current,
                        state.model_copy(update={"retry_model_step": True}),
                        context,
                    )
                    return suspended, None, suspended
                if current.state in TERMINAL_RUN_STATES:
                    return current, None, current
                run = current
                if model_event is None:
                    continue
                if model_event.kind == ModelEventKind.TEXT_DELTA:
                    drafts = []
                    if not text_started:
                        drafts.append(
                            EventDraft(
                                type="message.started",
                                turn_id=state.turn_id,
                                step_id=step_id,
                                item_id=text_item_id,
                                data=ItemEventData(operation="started"),
                            )
                        )
                        text_started = True
                    text += model_event.delta or ""
                    drafts.append(
                        EventDraft(
                            type="message.delta",
                            turn_id=state.turn_id,
                            step_id=step_id,
                            item_id=text_item_id,
                            data=ItemEventData(
                                operation="delta", delta=model_event.delta
                            ),
                        )
                    )
                    for draft in drafts:
                        run = await batcher.add(draft)
                elif model_event.kind == ModelEventKind.REASONING_DELTA:
                    drafts = []
                    if not reasoning_started:
                        drafts.append(
                            EventDraft(
                                type="reasoning.started",
                                turn_id=state.turn_id,
                                step_id=step_id,
                                item_id=reasoning_item_id,
                                data=ItemEventData(operation="started"),
                            )
                        )
                        reasoning_started = True
                    reasoning += model_event.delta or ""
                    drafts.append(
                        EventDraft(
                            type="reasoning.delta",
                            turn_id=state.turn_id,
                            step_id=step_id,
                            item_id=reasoning_item_id,
                            data=ItemEventData(
                                operation="delta", delta=model_event.delta
                            ),
                        )
                    )
                    for draft in drafts:
                        run = await batcher.add(draft)
                else:
                    response = model_event.response
        finally:
            try:
                run = await batcher.flush()
            finally:
                try:
                    # Stop the pending `anext` task before asking its source
                    # stream to close; Python async generators reject aclose
                    # while an iteration task is still running.
                    await controlled_events.aclose()
                finally:
                    # Provider streams may own sockets/tasks. A persistence
                    # error while flushing must not bypass their cleanup.
                    closer = getattr(stream, "aclose", None)
                    if closer is not None:
                        await closer()
        if response is None:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="model.stream_incomplete",
                    category=ErrorCategory.PROVIDER_TRANSIENT,
                    message="model stream ended without a completed response",
                    retryable=True,
                    safe_to_resume=True,
                )
            )
        drafts: list[EventDraft] = []
        if response.reasoning or reasoning_started:
            reasoning_text = response.reasoning or reasoning
            item = self._item(
                reasoning_item_id,
                run.run_id,
                state.turn_id,
                step_id,
                ReasoningItemData(content=(TextBlock(text=reasoning_text),)),
            )
            drafts.append(
                EventDraft(
                    type="reasoning.completed",
                    turn_id=state.turn_id,
                    step_id=step_id,
                    item_id=reasoning_item_id,
                    data=ItemEventData(operation="completed", item=item),
                )
            )
        if response.text or text_started or response.provider_state:
            text_value = response.text or text
            item = self._item(
                text_item_id,
                run.run_id,
                state.turn_id,
                step_id,
                MessageItemData(
                    role="assistant",
                    content=((TextBlock(text=text_value),) if text_value else ()),
                    provider_state=response.provider_state,
                ),
            )
            drafts.append(
                EventDraft(
                    type="message.completed",
                    turn_id=state.turn_id,
                    step_id=step_id,
                    item_id=text_item_id,
                    data=ItemEventData(operation="completed", item=item),
                )
            )
        for model_call in response.tool_calls:
            item_id = new_id("item")
            item = self._item(
                item_id,
                run.run_id,
                state.turn_id,
                step_id,
                ToolCallItemData(
                    tool_call_id=model_call.tool_call_id,
                    tool_name=model_call.name,
                    arguments=model_call.arguments,
                ),
            )
            drafts.append(
                EventDraft(
                    type="item.completed",
                    turn_id=state.turn_id,
                    step_id=step_id,
                    item_id=item_id,
                    data=ItemEventData(operation="completed", item=item),
                )
            )
        drafts.append(
            EventDraft(
                type="usage.recorded",
                turn_id=state.turn_id,
                step_id=step_id,
                data=UsageEventData(usage=response.usage),
            )
        )
        run = await self._commit_running(run, context, tuple(drafts))
        return run, response, None

    async def _record_tool_proposal(self, run, call, context, turn_id, step_id):
        return await self._commit_running(
            run,
            context,
            (
                EventDraft(
                    type="tool.call.proposed",
                    turn_id=turn_id,
                    step_id=step_id,
                    data=ToolEventData(
                        tool_call_id=call.tool_call_id,
                        tool_name=call.tool_name,
                        state="proposed",
                        operation_id=call.operation_id,
                        idempotency_key=call.idempotency_key,
                        arguments=call.arguments,
                    ),
                ),
            ),
        )

    async def _record_policy(self, run, call, policy, context, turn_id, step_id):
        payload = policy.interaction_payload
        return await self._commit_running(
            run,
            context,
            (
                EventDraft(
                    type="policy.decision.recorded",
                    turn_id=turn_id,
                    step_id=step_id,
                    data=PolicyEventData(
                        decision_id=policy.decision_id,
                        decision=policy.action.value,
                        policy_version=policy.policy_version,
                        reason=policy.reason,
                        remembered_by=payload.get("remembered_by"),
                        remembered_scope=payload.get("remembered_scope"),
                    ),
                ),
            ),
        )

    async def _consult_approval_memory(self, run, policy):
        """用会话内已记住的审批收敛决定；未命中则补上 approve_and_remember 选项。

        只收紧不放宽：只有策略已经判定 REQUIRE_INTERACTION 且允许记住的调用
        才会查记忆，DENY（缺 scope、plan 模式、assessor 拒绝）永远不被记忆覆盖。
        """

        if (
            self.approval_memory is None
            or policy.action != ToolPolicyAction.REQUIRE_INTERACTION
            or not policy.persistent_approval_allowed
            or policy.approval_matcher is None
        ):
            return policy
        remembered = await self.approval_memory.lookup(
            session_id=run.session_id, matcher=policy.approval_matcher
        )
        if remembered is not None:
            return policy.model_copy(
                update={
                    "action": ToolPolicyAction.ALLOW,
                    "reason": (
                        f"approved earlier in this {remembered.scope} by "
                        f"{remembered.remembered_by}: {remembered.matcher.summary}"
                    ),
                    "allowed_decisions": (),
                    "interaction_payload": {
                        **policy.interaction_payload,
                        "remembered_by": remembered.remembered_by,
                        "remembered_scope": remembered.scope,
                        "remembered_at": remembered.remembered_at.isoformat(),
                    },
                }
            )
        allowed = list(policy.allowed_decisions)
        if REMEMBER_DECISION not in allowed:
            position = (
                allowed.index("approve_once") + 1 if "approve_once" in allowed else 0
            )
            allowed.insert(position, REMEMBER_DECISION)
        return policy.model_copy(
            update={
                "allowed_decisions": tuple(allowed),
                "interaction_payload": {
                    **policy.interaction_payload,
                    "persistent_approval_allowed": True,
                    "approval_scopes": sorted(self.approval_memory.supported_scopes),
                },
            }
        )

    async def _remember_tool_approval(self, run, state, resolution, context):
        """approve_and_remember：把匹配器写入审批记忆并留下审计事件。"""

        policy = state.pending_tool_policy
        if (
            self.approval_memory is None
            or policy is None
            or policy.approval_matcher is None
            or not policy.persistent_approval_allowed
        ):
            # 没有记忆端口或策略不允许记住：宿主自行处理（例如写回自己的配置）。
            return run
        supported = self.approval_memory.supported_scopes
        requested = str(resolution.payload.get("scope") or "session")
        # 不支持的作用域一律收紧到 session，绝不放宽。
        scope = requested if requested in supported else "session"
        approval = RememberedApproval(
            matcher=policy.approval_matcher,
            scope=scope,
            remembered_at=self.clock(),
            remembered_by=context.actor.principal_id,
        )
        await self.approval_memory.remember(session_id=run.session_id, approval=approval)
        return await self._commit_running(
            run,
            context,
            (
                EventDraft(
                    type="policy.approval.remembered",
                    turn_id=state.turn_id,
                    step_id=state.pending_tool_step_id,
                    data=PolicyEventData(
                        decision_id=policy.decision_id,
                        decision=REMEMBER_DECISION,
                        policy_version=policy.policy_version,
                        reason=approval.matcher.summary,
                        remembered_by=approval.remembered_by,
                        remembered_scope=scope,
                    ),
                ),
            ),
        )

    async def _dispatch_tool(
        self, run, call, context, turn_id, step_id=None, state=None
    ):
        return await self.dispatch_tool_call(
            run, call, context, turn_id, step_id=step_id, state=state
        )

    async def _execute_tool_with_control(self, run, call, context):
        """Interrupt only when both Tool metadata and Executor permit it."""

        definition = await self.tool_catalog.get_tool(call.tool_name, run_id=run.run_id)
        execution = asyncio.create_task(self.tool_executor.execute(call, context))
        command = await self.runtime.session_store.get_start_command(run.run_id)
        cancellable = definition.cancel_semantics in {
            CancelSemantics.COOPERATIVE,
            CancelSemantics.FORCEABLE,
        }
        cancel = getattr(self.tool_executor, "cancel", None)
        monitor_control = cancellable and callable(cancel)
        try:
            while True:
                if not monitor_control:
                    return run, await execution
                done, _ = await asyncio.wait({execution}, timeout=0.1)
                if done:
                    return await self.runtime.get_run(run.run_id), execution.result()
                current = await self.runtime.get_run(run.run_id)
                deadline_expired = (
                    command.config.deadline_seconds is not None
                    and (self.clock() - current.created_at).total_seconds()
                    >= command.config.deadline_seconds
                )
                if current.state == RunState.RUNNING and not deadline_expired:
                    continue
                if (
                    current.state
                    not in {
                        RunState.SUSPEND_REQUESTED,
                        *TERMINAL_RUN_STATES,
                    }
                    and not deadline_expired
                ):
                    continue
                cancellation = await cancel(call.operation_id, context)
                if cancellation.state == ToolCancellationState.CANCELLED:
                    execution.cancel()
                    await asyncio.gather(execution, return_exceptions=True)
                    if current.state in TERMINAL_RUN_STATES:
                        return current, None
                    error = (
                        RuntimeErrorInfo(
                            code="budget.deadline",
                            category=ErrorCategory.VALIDATION,
                            message=tr("error.budget.deadline", context.language),
                            safe_to_resume=True,
                        )
                        if deadline_expired
                        else RuntimeErrorInfo(
                            code="tool.cancelled_for_pause",
                            category=ErrorCategory.CANCELLED,
                            message=(
                                "tool execution was cooperatively cancelled for pause"
                            ),
                            safe_to_resume=True,
                        )
                    )
                    return current, ToolExecutionResult(
                        tool_call_id=call.tool_call_id,
                        operation_id=call.operation_id,
                        content=(TextBlock(text=error.message),),
                        error=error,
                        metadata={"cancellation_confirmed": True},
                    )
                if cancellation.state == ToolCancellationState.UNKNOWN:
                    # The original execution channel is still our strongest
                    # evidence source. Keep waiting for it; if it fails with an
                    # uncertain-side-effect error, the normal reconcile path
                    # records that fact without duplicating the operation.
                    monitor_control = False
                    continue
                # TOO_LATE/NOT_SUPPORTED means the operation must settle; do
                # not keep issuing cancellation requests on every poll.
                monitor_control = False
        finally:
            if not execution.done():
                # This only runs when the parent task itself is torn down. It
                # does not claim that the external side effect was cancelled.
                execution.cancel()
                await asyncio.gather(execution, return_exceptions=True)

    async def dispatch_tool_call(
        self, run, call, context, turn_id, step_id=None, state=None
    ):
        """Cross the tool side-effect barrier and settle or reconcile its result.

        `dispatching` is committed before calling the provider. Once control
        crosses into ToolExecutor, a transport failure may mean the operation
        succeeded remotely; such failures become UNKNOWN, never an automatic
        retry.
        """

        run = await self._commit_running(
            run,
            context,
            (
                EventDraft(
                    type="tool.call.dispatching",
                    turn_id=turn_id,
                    step_id=step_id,
                    data=ToolEventData(
                        tool_call_id=call.tool_call_id,
                        tool_name=call.tool_name,
                        state="dispatching",
                        operation_id=call.operation_id,
                        idempotency_key=call.idempotency_key,
                    ),
                ),
                EventDraft(
                    type="tool.call.started",
                    turn_id=turn_id,
                    step_id=step_id,
                    data=ToolEventData(
                        tool_call_id=call.tool_call_id,
                        tool_name=call.tool_name,
                        state="running",
                        operation_id=call.operation_id,
                        idempotency_key=call.idempotency_key,
                    ),
                ),
            ),
        )
        try:
            run, result = await self._execute_tool_with_control(run, call, context)
            if result is None:
                return run, None
        except SageV2Error as exc:
            localized = localize_error(exc.info, context.language)
            result = ToolExecutionResult(
                tool_call_id=call.tool_call_id,
                operation_id=call.operation_id,
                content=(TextBlock(text=localized.message),),
                error=localized,
            )
        except Exception as exc:
            localized = localize_error(
                RuntimeErrorInfo(
                    code="tool.provider_error",
                    category=ErrorCategory.PROVIDER_PERMANENT,
                    message=str(exc),
                    safe_to_resume=True,
                ),
                context.language,
            )
            result = ToolExecutionResult(
                tool_call_id=call.tool_call_id,
                operation_id=call.operation_id,
                content=(TextBlock(text=localized.message),),
                error=localized,
            )
        if result.error is not None:
            localized = localize_error(result.error, context.language)
            if await self._tool_failure_is_uncertain(run, call, localized):
                uncertainty = self._as_uncertain_tool_error(localized)
                run = await self._record_tool_unknown(
                    run, call, uncertainty, context, turn_id, step_id
                )
                return await self._reconcile_or_suspend_tool(
                    run,
                    call,
                    context,
                    turn_id,
                    step_id,
                    state,
                    uncertainty,
                )
            # A Tool may return a structured, model-actionable failure (MCP
            # ``isError`` is one example). Preserve that authoritative content,
            # while the persisted error remains localized for host/UI use.
            if result.metadata.get("tool_result_received") is True:
                result = result.model_copy(update={"error": localized})
            else:
                result = result.model_copy(
                    update={
                        "error": localized,
                        "content": (TextBlock(text=localized.message),),
                    }
                )
        elif call.tool_name == "tool_expand_tools":
            requested_names = call.arguments.get("tool_names")
            if requested_names is None:
                requested_names = call.arguments.get("names")
            if isinstance(requested_names, (list, tuple)):
                self.tool_selection_policy.expand_tools(
                    run_id=call.owner_run_id,
                    names=tuple(
                        name for name in requested_names if isinstance(name, str)
                    ),
                )
        pending_delegations = result.metadata.get("delegation_interactions")
        if (
            state is not None
            and isinstance(pending_delegations, list)
            and pending_delegations
        ):
            pending_state = state.model_copy(
                update={
                    "pending_tool_call": call,
                    "pending_tool_phase": "delegation_interaction",
                    "pending_tool_step_id": step_id,
                    "pending_tool_result": result.model_dump(mode="json"),
                    "pending_child_interactions": tuple(pending_delegations),
                }
            )
            return (
                await self._suspend_for_delegated_interaction(
                    run,
                    pending_state,
                    call,
                    pending_delegations[0],
                    context,
                    step_id,
                ),
                None,
            )
        current = await self.runtime.get_run(run.run_id)
        if current.state in TERMINAL_RUN_STATES:
            return current, None
        run = current
        if run.state == RunState.SUSPEND_REQUESTED:
            run = await self._commit_tool_result(
                run,
                call,
                result,
                context,
                turn_id,
                step_id=step_id,
                declined=result.error is not None
                and result.error.code == "tool.cancelled_for_pause",
                expected_states={RunState.SUSPEND_REQUESTED},
            )
            assert state is not None
            paused_state = state.model_copy(
                update={
                    "messages": (*state.messages, self._tool_result_message(result))
                }
            )
            return await self._suspend_at_safe_point(run, paused_state, context), None
        run = await self._commit_tool_result(
            run, call, result, context, turn_id, step_id=step_id
        )
        return run, result

    async def _tool_failure_is_uncertain(self, run, call, error) -> bool:
        """Classify post-dispatch failures without assuming a write was rolled back."""

        # A protocol-level tool error is an authoritative response, not a lost
        # response. The remote side confirmed that the operation failed, so a
        # write must not be escalated to an unknown-side-effect suspension.
        if error.metadata.get("tool_result_received") is True:
            return False
        if error.category == ErrorCategory.UNCERTAIN_SIDE_EFFECT:
            return True
        if error.metadata.get("side_effect_state") == "not_applied":
            return False
        definition = await self.tool_catalog.get_tool(call.tool_name, run_id=run.run_id)
        return definition.side_effect_level in {
            SideEffectLevel.WRITE,
            SideEffectLevel.REVERSIBLE,
            SideEffectLevel.IRREVERSIBLE,
        }

    @staticmethod
    def _as_uncertain_tool_error(error: RuntimeErrorInfo) -> RuntimeErrorInfo:
        if error.category == ErrorCategory.UNCERTAIN_SIDE_EFFECT:
            return error
        return error.model_copy(
            update={
                "category": ErrorCategory.UNCERTAIN_SIDE_EFFECT,
                "retryable": False,
                "metadata": {
                    **error.metadata,
                    "original_category": error.category.value,
                },
            }
        )

    async def _resume_delegated_tool(self, run, state, decision, payload, context):
        if self.delegated_run_controller is None:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="agent.delegation_controller_missing",
                    category=ErrorCategory.INTERNAL,
                    message="delegated interaction controller is unavailable",
                )
            )
        pending = list(state.pending_child_interactions)
        if not pending or state.pending_tool_result is None:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="agent.delegation_checkpoint_invalid",
                    category=ErrorCategory.CORRUPT_STATE,
                    message="delegated interaction checkpoint is incomplete",
                )
            )
        current = pending.pop(0)
        child_run_id = str(current.get("child_run_id") or "")
        child_result = await self.delegated_run_controller.resolve_interaction(
            child_run_id,
            decision=decision,
            payload=payload,
            context=context,
        )
        tool_result = ToolExecutionResult.model_validate(state.pending_tool_result)
        content = []
        for block in tool_result.content:
            if not isinstance(block, JsonBlock) or not isinstance(block.value, dict):
                content.append(block)
                continue
            value = dict(block.value)
            values = []
            for item in value.get("results") or ():
                if isinstance(item, dict) and item.get("child_run_id") == child_run_id:
                    values.append(child_result.model_dump(mode="json"))
                else:
                    values.append(item)
            value["results"] = values
            content.append(JsonBlock(value=value))
        tool_result = tool_result.model_copy(
            update={
                "content": tuple(content),
                "metadata": {
                    **tool_result.metadata,
                    "delegation_interactions": [],
                },
            }
        )
        if child_result.outcome == RunState.SUSPENDED:
            next_interaction = await self.delegated_run_controller.pending_interaction(
                child_run_id
            )
            if next_interaction is not None:
                pending.insert(
                    0,
                    {
                        "agent_id": child_result.agent_id,
                        "child_run_id": child_run_id,
                        "interaction": next_interaction,
                    },
                )
        if pending:
            pending_state = state.model_copy(
                update={
                    "pending_tool_result": tool_result.model_dump(mode="json"),
                    "pending_child_interactions": tuple(pending),
                }
            )
            return (
                await self._suspend_for_delegated_interaction(
                    run,
                    pending_state,
                    state.pending_tool_call,
                    pending[0],
                    context,
                    state.pending_tool_step_id,
                ),
                None,
            )
        run = await self._commit_tool_result(
            run,
            state.pending_tool_call,
            tool_result,
            context,
            state.turn_id,
            step_id=state.pending_tool_step_id,
        )
        return run, tool_result

    async def _suspend_for_delegated_interaction(
        self, run, state, call, pending, context, step_id
    ):
        raw = pending.get("interaction") if isinstance(pending, dict) else None
        child = InteractionRequest.model_validate(raw)
        interaction_id = new_id("interaction")
        checkpoint, suspension = self._checkpoint_records(
            run,
            state,
            reason=SuspensionReason.INPUT_REQUIRED,
            interaction_id=interaction_id,
        )
        interaction = InteractionRequest(
            interaction_id=interaction_id,
            run_id=run.run_id,
            turn_id=state.turn_id,
            step_id=step_id,
            interaction_type=child.interaction_type,
            blocking_scope=BlockingScope.RUN,
            allowed_decisions=child.allowed_decisions,
            eligible_principal_ids=(context.actor.principal_id,),
            payload={
                **child.payload,
                "delegated": True,
                "child_run_id": pending.get("child_run_id"),
                "child_interaction_id": child.interaction_id,
                "tool_name": call.tool_name,
            },
            requested_at=self.clock(),
        )
        return await self.runtime.commit_suspension(
            run_id=run.run_id,
            expected_revision=run.revision,
            checkpoint=checkpoint,
            suspension=suspension,
            interaction=interaction,
            context=context,
            idempotency_key=f"delegation-suspend:{interaction_id}",
        )

    async def _record_tool_unknown(self, run, call, error, context, turn_id, step_id):
        return await self._commit_running(
            run,
            context,
            (
                EventDraft(
                    type="tool.call.unknown",
                    turn_id=turn_id,
                    step_id=step_id,
                    data=ToolEventData(
                        tool_call_id=call.tool_call_id,
                        tool_name=call.tool_name,
                        state="unknown",
                        operation_id=call.operation_id,
                        idempotency_key=call.idempotency_key,
                        error=error,
                    ),
                ),
            ),
        )

    async def _reconcile_or_suspend_tool(
        self, run, call, context, turn_id, step_id, state, uncertainty
    ):
        """Resolve an uncertain side effect without executing the call again."""

        definition = await self.tool_catalog.get_tool(call.tool_name, run_id=run.run_id)
        if definition.supports_reconciliation:
            run = await self._commit_running(
                run,
                context,
                (
                    EventDraft(
                        type="tool.call.reconciling",
                        turn_id=turn_id,
                        step_id=step_id,
                        data=ToolEventData(
                            tool_call_id=call.tool_call_id,
                            tool_name=call.tool_name,
                            state="reconciling",
                            operation_id=call.operation_id,
                            idempotency_key=call.idempotency_key,
                        ),
                    ),
                ),
            )
            try:
                reconcile_call = getattr(self.tool_executor, "reconcile_call", None)
                reconciled = (
                    await reconcile_call(call, context)
                    if callable(reconcile_call)
                    else await self.tool_executor.reconcile(call.operation_id, context)
                )
            except Exception as exc:
                reconciled = ReconcileResult(
                    operation_id=call.operation_id,
                    state=ReconcileState.UNKNOWN,
                    error=RuntimeErrorInfo(
                        code="tool.reconcile_failed",
                        category=ErrorCategory.PROVIDER_TRANSIENT,
                        message=str(exc),
                        retryable=True,
                        safe_to_resume=True,
                    ),
                )
            if reconciled.state == ReconcileState.SUCCEEDED and reconciled.result:
                run = await self._commit_tool_result(
                    run,
                    call,
                    reconciled.result,
                    context,
                    turn_id,
                    step_id=step_id,
                    event_type_override="tool.call.reconciled",
                )
                return run, reconciled.result
            if reconciled.state == ReconcileState.FAILED:
                result = reconciled.result or ToolExecutionResult(
                    tool_call_id=call.tool_call_id,
                    operation_id=call.operation_id,
                    error=reconciled.error
                    or RuntimeErrorInfo(
                        code="tool.reconciled_failed",
                        category=ErrorCategory.PROVIDER_PERMANENT,
                        message="tool provider confirmed that the operation failed",
                        safe_to_resume=True,
                    ),
                )
                run = await self._commit_tool_result(
                    run,
                    call,
                    result,
                    context,
                    turn_id,
                    step_id=step_id,
                    event_type_override="tool.call.reconciled",
                )
                return run, result
        if state is None:
            raise SageV2Error(uncertainty)
        return (
            await self._suspend_for_tool_uncertainty(
                run, state, call, uncertainty, context, step_id, definition
            ),
            None,
        )

    async def _resume_uncertain_tool(self, run, state, decision, payload, context):
        call = state.pending_tool_call
        assert call is not None
        step_id = state.pending_tool_step_id
        if decision == "reconcile":
            uncertainty = RuntimeErrorInfo.model_validate(
                state.pending_tool_error
                or {
                    "code": "tool.outcome_unknown",
                    "category": ErrorCategory.UNCERTAIN_SIDE_EFFECT,
                    "message": "tool outcome remains unknown",
                    "safe_to_resume": True,
                }
            )
            return await self._reconcile_or_suspend_tool(
                run,
                call,
                context,
                state.turn_id,
                step_id,
                state,
                uncertainty,
            )
        if decision == "confirm_succeeded":
            result = ToolExecutionResult(
                tool_call_id=call.tool_call_id,
                operation_id=call.operation_id,
                content=(
                    TextBlock(
                        text=str(
                            payload.get(
                                "result_text",
                                "operation manually confirmed as succeeded",
                            )
                        )
                    ),
                ),
                metadata={"manually_confirmed": True},
            )
            run = await self._commit_tool_result(
                run,
                call,
                result,
                context,
                state.turn_id,
                step_id=step_id,
                event_type_override="tool.call.reconciled",
            )
            return run, result
        error = RuntimeErrorInfo(
            code="tool.outcome_manually_failed",
            category=(
                ErrorCategory.CANCELLED
                if decision == "cancel"
                else ErrorCategory.UNCERTAIN_SIDE_EFFECT
            ),
            message=f"unknown tool outcome resolved with {decision}",
            safe_to_resume=True,
        )
        result = ToolExecutionResult(
            tool_call_id=call.tool_call_id,
            operation_id=call.operation_id,
            content=(TextBlock(text=error.message),),
            error=error,
            metadata={"manually_confirmed": True},
        )
        run = await self._commit_tool_result(
            run,
            call,
            result,
            context,
            state.turn_id,
            step_id=step_id,
            declined=decision == "cancel",
            event_type_override=(
                None if decision == "cancel" else "tool.call.reconciled"
            ),
        )
        return run, result

    async def _commit_tool_result(
        self,
        run,
        call,
        result,
        context,
        turn_id,
        step_id=None,
        declined=False,
        event_type_override=None,
        expected_states=None,
    ):
        """Atomically commit the Tool lifecycle result and model-visible Item."""

        if result.error is not None:
            localized = localize_error(result.error, context.language)
            result = result.model_copy(
                update={
                    "error": localized,
                    "content": (TextBlock(text=localized.message),),
                }
            )

        item_id = new_id("item")
        status = (
            ItemStatus.DECLINED
            if declined
            else ItemStatus.FAILED
            if result.error is not None
            else ItemStatus.COMPLETED
        )
        item = self._item(
            item_id,
            run.run_id,
            turn_id,
            step_id,
            ToolResultItemData(
                tool_call_id=call.tool_call_id,
                content=result.content,
                error=result.error,
                metadata=result.metadata,
            ),
            status=status,
        )
        event_type = event_type_override or (
            "tool.call.cancelled"
            if declined
            else "tool.call.failed"
            if result.error is not None
            else "tool.call.succeeded"
        )
        return await self._commit_running(
            run,
            context,
            (
                EventDraft(
                    type=event_type,
                    turn_id=turn_id,
                    step_id=step_id,
                    data=ToolEventData(
                        tool_call_id=call.tool_call_id,
                        tool_name=call.tool_name,
                        state=status.value,
                        operation_id=call.operation_id,
                        idempotency_key=call.idempotency_key,
                        result_item_id=item_id,
                        error=result.error,
                    ),
                ),
                EventDraft(
                    type="item.completed",
                    turn_id=turn_id,
                    step_id=step_id,
                    item_id=item_id,
                    data=ItemEventData(operation="completed", item=item),
                ),
            ),
            expected_states=expected_states,
        )

    async def _suspend_for_tool_uncertainty(
        self,
        run,
        state,
        call,
        error,
        context,
        step_id,
        definition=None,
        *,
        supports_reconciliation: bool | None = None,
    ):
        """Require explicit reconciliation when a Tool outcome is unknowable."""

        can_reconcile = (
            bool(definition.supports_reconciliation)
            if supports_reconciliation is None and definition is not None
            else bool(supports_reconciliation)
        )
        interaction_id = new_id("interaction")
        pending_state = state.model_copy(
            update={
                "pending_tool_call": call,
                "pending_tool_phase": "reconciliation",
                "pending_tool_step_id": step_id,
                "pending_tool_error": error.model_dump(mode="json"),
            }
        )
        checkpoint, suspension = self._checkpoint_records(
            run,
            pending_state,
            reason=SuspensionReason.POLICY_HOLD,
            interaction_id=interaction_id,
        )
        decisions = ["confirm_succeeded", "mark_failed", "cancel"]
        if can_reconcile:
            decisions.insert(0, "reconcile")
        interaction = InteractionRequest(
            interaction_id=interaction_id,
            run_id=run.run_id,
            turn_id=state.turn_id,
            step_id=step_id,
            interaction_type=InteractionType.APPROVAL,
            blocking_scope=BlockingScope.RUN,
            allowed_decisions=tuple(decisions),
            eligible_principal_ids=(context.actor.principal_id,),
            payload={
                **recovery_payload(
                    "recovery.uncertain_tool",
                    context.language,
                    reason_code="tool_outcome_unknown",
                ),
                "reason": "tool_outcome_unknown",
                "tool_name": call.tool_name,
                "arguments": call.arguments,
                "side_effect_level": (
                    definition.side_effect_level.value
                    if definition is not None
                    else None
                ),
                "operation_id": call.operation_id,
                "idempotency_key": call.idempotency_key,
                "supports_reconciliation": can_reconcile,
                "error_code": error.code,
            },
            requested_at=self.clock(),
        )
        return await self.runtime.commit_suspension(
            run_id=run.run_id,
            expected_revision=run.revision,
            checkpoint=checkpoint,
            suspension=suspension,
            interaction=interaction,
            context=context,
            idempotency_key=f"uncertain-tool-suspend:{interaction_id}",
        )

    async def _suspend_for_tool_approval(self, run, state, policy, context, step_id):
        """Checkpoint before dispatch so approval cannot race the side effect."""

        interaction_id = new_id("interaction")
        checkpoint, suspension = self._checkpoint_records(
            run,
            state,
            reason=SuspensionReason.APPROVAL_REQUIRED,
            interaction_id=interaction_id,
        )
        payload = dict(policy.interaction_payload)
        diagnostic_risk = payload.get("risk_reason")
        if payload.get("risk_category") == "plan_approval":
            payload.pop("risk_reason", None)
        elif diagnostic_risk:
            payload["diagnostic_risk_reason"] = diagnostic_risk
            payload["risk_reason"] = tr("approval.risk", context.language)
        tool_name = str(payload.get("tool_name") or state.pending_tool_call.tool_name)
        payload.update(
            {
                "title": tr("approval.title", context.language),
                "prompt": tr("approval.tool_prompt", context.language, tool=tool_name),
                "guidance": tr("approval.guidance", context.language),
                "language": normalize_language(context.language),
            }
        )
        interaction = InteractionRequest(
            interaction_id=interaction_id,
            run_id=run.run_id,
            turn_id=state.turn_id,
            step_id=step_id,
            interaction_type=InteractionType.APPROVAL,
            blocking_scope=BlockingScope.RUN,
            allowed_decisions=policy.allowed_decisions,
            eligible_principal_ids=(context.actor.principal_id,),
            payload=payload,
            requested_at=self.clock(),
        )
        run = await self._commit_running(
            run,
            context,
            (
                EventDraft(
                    type="tool.call.awaiting_approval",
                    turn_id=state.turn_id,
                    step_id=step_id,
                    data=ToolEventData(
                        tool_call_id=state.pending_tool_call.tool_call_id,
                        tool_name=state.pending_tool_call.tool_name,
                        state="awaiting_approval",
                        operation_id=state.pending_tool_call.operation_id,
                        idempotency_key=state.pending_tool_call.idempotency_key,
                    ),
                ),
            ),
        )
        return await self.runtime.commit_suspension(
            run_id=run.run_id,
            expected_revision=run.revision,
            checkpoint=checkpoint.model_copy(
                update={
                    "run_sequence": run.last_run_sequence,
                    "session_revision": (
                        await self.runtime.session_store.get_session(run.session_id)
                    ).revision,
                }
            ),
            suspension=suspension,
            interaction=interaction,
            context=context,
            idempotency_key=f"approval-suspend:{interaction_id}",
        )

    async def _suspend_for_continuation_interaction(
        self, run, state, decision, context, step_id
    ):
        interaction_id = new_id("interaction")
        reset_budget = bool(decision.interaction.payload.get("reset_step_budget"))
        preserve_budget = bool(decision.interaction.payload.get("preserve_step_budget"))
        next_step = (
            1
            if reset_budget
            else state.step_number
            if preserve_budget
            else state.step_number + 1
        )
        checkpoint, suspension = self._checkpoint_records(
            run,
            state.model_copy(update={"step_number": next_step}),
            reason=SuspensionReason.INPUT_REQUIRED,
            interaction_id=interaction_id,
        )
        draft = decision.interaction
        assert draft is not None
        interaction = InteractionRequest(
            interaction_id=interaction_id,
            run_id=run.run_id,
            turn_id=state.turn_id,
            step_id=step_id,
            interaction_type=InteractionType.USER_INPUT,
            allowed_decisions=draft.allowed_decisions,
            eligible_principal_ids=(context.actor.principal_id,),
            payload=draft.payload,
            requested_at=self.clock(),
        )
        return await self.runtime.commit_suspension(
            run_id=run.run_id,
            expected_revision=run.revision,
            checkpoint=checkpoint,
            suspension=suspension,
            interaction=interaction,
            context=context,
            idempotency_key=f"continuation-suspend:{interaction_id}",
        )

    async def _suspend_at_safe_point(self, run, state, context):
        return await self.commit_safe_point_suspension(run, state, context)

    async def commit_safe_point_suspension(self, run, state, context):
        """Commit a manual-pause checkpoint between externally visible actions."""

        checkpoint, suspension = self._checkpoint_records(
            run, state, reason=SuspensionReason.MANUAL_PAUSE
        )
        return await self.runtime.commit_suspension(
            run_id=run.run_id,
            expected_revision=run.revision,
            checkpoint=checkpoint,
            suspension=suspension,
            context=context,
            idempotency_key=f"manual-suspend:{suspension.suspension_id}",
        )

    def _checkpoint_records(self, run, state, *, reason, interaction_id=None):
        """Build matching Checkpoint/Suspension records for one atomic commit."""

        checkpoint_id = new_id("checkpoint")
        checkpoint_state = AgentLoopCheckpointCodec.encode(
            state, ledger_digest=self._ledger_digest(state.messages)
        )
        checkpoint = Checkpoint(
            checkpoint_id=checkpoint_id,
            checkpoint_codec_version=AgentLoopCheckpointCodec.version,
            session_id=run.session_id,
            run_id=run.run_id,
            run_sequence=run.last_run_sequence,
            session_revision=run.accepted_session_revision,
            state=checkpoint_state,
            resolved_spec_hash=run.resolved_spec_hash,
            created_at=self.clock(),
        )
        suspension = Suspension(
            suspension_id=new_id("suspension"),
            run_id=run.run_id,
            reason=reason,
            blocking_scope="run",
            checkpoint_id=checkpoint_id,
            checkpoint_sequence=run.last_run_sequence,
            interaction_id=interaction_id,
            resume_policy=(
                "after_interaction_resolution"
                if interaction_id is not None
                else "explicit_resume"
            ),
            requested_at=self.clock(),
        )
        return checkpoint, suspension

    async def _record_continuation(self, run, decision, context, turn_id, step_id):
        drafts = [
            EventDraft(
                type="continuation.decided",
                turn_id=turn_id,
                step_id=step_id,
                data=ContinuationEventData(
                    action=decision.action.value,
                    reason_code=decision.reason_code,
                    reason=decision.reason,
                    decision_hash=decision.stable_hash(),
                    next_agent=decision.next_agent,
                    details=decision.metadata,
                ),
            )
        ]
        if (
            decision.usage.input_tokens
            or decision.usage.output_tokens
            or decision.usage.cost is not None
        ):
            drafts.append(
                EventDraft(
                    type="usage.recorded",
                    turn_id=turn_id,
                    step_id=step_id,
                    data=UsageEventData(usage=decision.usage),
                )
            )
        return await self._commit_running(
            run,
            context,
            tuple(drafts),
        )

    @staticmethod
    def _context_for_command(context: RequestContext, command) -> RequestContext:
        language = normalize_language(
            str(command.config.metadata.get("response_language") or context.language)
        )
        if context.language == language:
            return context
        return context.model_copy(update={"language": language})

    @staticmethod
    def _ledger_digest(messages) -> str:
        """Hash provider-neutral ledger facts, excluding regenerated context."""

        payload = []
        for message in messages:
            value = message.model_dump(mode="json")
            # These provenance keys are deterministically added by event
            # projection but are intentionally absent from the live model
            # response object. They do not change provider-visible semantics.
            value["metadata"] = {
                key: item
                for key, item in value.get("metadata", {}).items()
                if key
                not in {
                    "source_session_id",
                    "source_run_id",
                    "source_item_id",
                }
            }
            payload.append(value)
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"

    @staticmethod
    def _interaction_input_items(
        payload,
        *,
        interaction_id: str,
        decision: str,
    ) -> tuple[InputItem, ...]:
        """Normalize a user-input resolution into ordinary canonical messages."""

        raw_items = payload.get("input", ())
        if isinstance(raw_items, dict):
            raw_items = (raw_items,)
        items = tuple(InputItem.model_validate(value) for value in raw_items)
        if not items:
            text = payload.get("text") or payload.get("guidance")
            if isinstance(text, str) and text.strip():
                items = (
                    InputItem(role="user", content=(TextBlock(text=text.strip()),)),
                )
        if decision in {"submit", "change_direction"} and not items:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="interaction.input_required",
                    category=ErrorCategory.VALIDATION,
                    message=(f"{decision} requires payload.text, guidance, or input"),
                    safe_to_resume=True,
                )
            )
        normalized = []
        for item in items:
            if item.role != "user":
                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="interaction.invalid_input_role",
                        category=ErrorCategory.VALIDATION,
                        message="user-input interactions accept only user messages",
                        safe_to_resume=True,
                    )
                )
            normalized.append(
                item.model_copy(
                    update={
                        "metadata": {
                            **item.metadata,
                            "interaction_id": interaction_id,
                            "interaction_decision": decision,
                        }
                    }
                )
            )
        return tuple(normalized)

    async def _commit_interaction_input(
        self,
        run,
        state,
        items,
        interaction_id,
        context,
    ):
        drafts = []
        for input_item in items:
            item_id = new_id("item")
            data = MessageItemData(
                role=input_item.role,
                content=input_item.content,
                metadata=input_item.metadata,
            )
            item = self._item(
                item_id,
                run.run_id,
                state.turn_id,
                None,
                data,
            )
            drafts.append(
                EventDraft(
                    type="message.completed",
                    turn_id=state.turn_id,
                    item_id=item_id,
                    interaction_id=interaction_id,
                    data=ItemEventData(operation="completed", item=item),
                    source=EventSource(
                        source_type=EventSourceType.USER,
                        source_id=context.actor.principal_id,
                    ),
                )
            )
        result = await self.runtime.session_store.commit_run(
            run_id=run.run_id,
            expected_revision=run.revision,
            expected_states={RunState.RUNNING},
            new_state=RunState.RUNNING,
            drafts=tuple(drafts),
            context=context,
            idempotency_key=f"interaction-input:{interaction_id}",
        )
        return result.run

    async def _complete(self, run, state, step_id, context):
        completed = await self.lifecycle.commit(
            run,
            new_state=RunState.COMPLETED,
            expected_states={RunState.RUNNING},
            drafts=(
                EventDraft(
                    type="step.completed",
                    turn_id=state.turn_id,
                    step_id=step_id,
                    data=StepEventData(state="completed", attempt=state.step_number),
                ),
                EventDraft(
                    type="turn.completed",
                    turn_id=state.turn_id,
                    data=TurnEventData(state="completed", stop_reason="completed"),
                ),
                EventDraft(
                    type="run.completed",
                    data=RunEventData(state="completed"),
                ),
            ),
            context=context,
            idempotency_key=f"loop-complete:{run.run_id}:{state.step_number}",
        )
        await self._release_run_resources(run.run_id)
        return completed

    async def _fail(self, run, state, step_id, error, context):
        error = localize_error(error, context.language)
        current = await self.runtime.get_run(run.run_id)
        if current.state in TERMINAL_RUN_STATES:
            await self._release_run_resources(run.run_id)
            return current
        resumable = error.safe_to_resume or error.retryable
        if current.state == RunState.RUNNING and resumable:
            decision = ContinuationDecision(
                action=ContinuationAction.REQUEST_INTERACTION,
                reason_code=error.code,
                reason=error.message,
                interaction=InteractionDraft(
                    interaction_type="error_recovery",
                    allowed_decisions=("retry", "change_direction", "cancel"),
                    payload=error_recovery_payload(
                        error, context.language, resumable=True
                    ),
                ),
            )
            current = await self._record_continuation(
                current, decision, context, state.turn_id, step_id
            )
            return await self._suspend_for_continuation_interaction(
                current, state, decision, context, step_id
            )
        recovery = error_recovery_payload(error, context.language, resumable=False)
        error = error.model_copy(
            update={
                "metadata": {
                    **error.metadata,
                    "recovery_questionnaire": recovery,
                }
            }
        )
        failed = await self.lifecycle.commit(
            current,
            new_state=RunState.FAILED,
            expected_states={
                RunState.RUNNING,
                RunState.SUSPEND_REQUESTED,
                RunState.RESUMING,
            },
            drafts=(
                EventDraft(
                    type="step.failed",
                    turn_id=state.turn_id,
                    step_id=step_id,
                    data=StepEventData(
                        state="failed", attempt=state.step_number, error=error
                    ),
                ),
                EventDraft(
                    type="turn.failed",
                    turn_id=state.turn_id,
                    data=TurnEventData(state="failed", error=error),
                ),
                EventDraft(
                    type="run.failed",
                    data=RunEventData(state="failed", error=error),
                ),
            ),
            context=context,
            idempotency_key=f"loop-fail:{run.run_id}:{state.step_number}:{error.code}",
        )
        await self._release_run_resources(run.run_id)
        return failed

    async def _release_run_resources(self, run_id: str) -> None:
        """Best-effort cleanup after the durable Run reached a terminal state."""

        providers = (
            self.tool_selection_policy,
            self.tool_catalog,
            self.tool_executor,
        )
        seen: set[int] = set()
        for provider in providers:
            if id(provider) in seen:
                continue
            seen.add(id(provider))
            release = getattr(provider, "release_run", None)
            if not callable(release):
                continue
            try:
                result = release(run_id)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                # Terminal state is already durable. Cleanup failure must not
                # turn a completed/failed Run into a caller-visible failure.
                continue

    async def _commit_running(
        self, run, context, drafts, *, expected_states=None
    ) -> RunSnapshot:
        return await self.lifecycle.commit(
            run,
            expected_states=expected_states or {RunState.RUNNING},
            new_state=run.state,
            drafts=drafts,
            context=context,
            idempotency_key=new_id("loop_commit"),
        )

    def _item(
        self, item_id, run_id, turn_id, step_id, data, status=ItemStatus.COMPLETED
    ):
        now = self.clock()
        encoded = json.dumps(
            data.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
        return ItemSnapshot(
            item_id=item_id,
            run_id=run_id,
            turn_id=turn_id,
            step_id=step_id,
            status=status,
            data=data,
            content_hash=f"sha256:{hashlib.sha256(encoded).hexdigest()}",
            created_at=now,
            updated_at=now,
        )

    def _partial_item_draft(
        self, run_id, turn_id, step_id, item_id, content, *, reasoning
    ):
        data = (
            ReasoningItemData(content=(TextBlock(text=content),))
            if reasoning
            else MessageItemData(role="assistant", content=(TextBlock(text=content),))
        )
        item = self._item(
            item_id,
            run_id,
            turn_id,
            step_id,
            data,
            status=ItemStatus.SUSPENDED,
        )
        return EventDraft(
            type="item.completed",
            turn_id=turn_id,
            step_id=step_id,
            item_id=item_id,
            data=ItemEventData(operation="completed", item=item),
        )

    @staticmethod
    def _tool_result_message(result):
        content = result.content
        if not content and result.error is not None:
            content = (TextBlock(text=result.error.message),)
        return ModelMessage(
            role="tool",
            tool_call_id=result.tool_call_id,
            content=content,
            metadata=result.metadata,
        )

    @staticmethod
    def _response_fingerprint(response):
        payload = {
            "text": response.text,
            "tools": [
                {"name": call.name, "arguments": call.arguments}
                for call in response.tool_calls
            ],
        }
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _trailing_repeat_count(values):
        if not values:
            return 0
        latest = values[-1]
        count = 0
        for value in reversed(values):
            if value != latest:
                break
            count += 1
        return count

    def _assert_resolved_spec_compatible(
        self, run_hash: str, *, checkpoint_hash: str | None = None
    ) -> None:
        """Fail closed when a Run is routed to a different resolved runtime.

        A persisted hash is only useful when the executing composition checks
        it.  This prevents a queued Run or checkpoint from silently resuming
        against changed tools, policies, prompts, or model bindings.
        """

        expected = self.expected_resolved_spec_hash
        if expected is None:
            return
        observed = {run_hash}
        if checkpoint_hash is not None:
            observed.add(checkpoint_hash)
        if observed == {expected}:
            return
        raise SageV2Error(
            RuntimeErrorInfo(
                code="loop.resolved_spec_incompatible",
                category=ErrorCategory.UNSUPPORTED_SCHEMA,
                message="run was created by an incompatible resolved runtime",
                safe_to_resume=False,
                metadata={
                    "expected_resolved_spec_hash": expected,
                    "run_resolved_spec_hash": run_hash,
                    "checkpoint_resolved_spec_hash": checkpoint_hash,
                },
            )
        )

    @staticmethod
    def _conflict(code, message):
        return SageV2Error(
            RuntimeErrorInfo(
                code=code,
                category=ErrorCategory.CONFLICT,
                message=message,
                safe_to_resume=True,
            )
        )

"""Checkpointable single-Agent model/tool execution loop.

The Loop owns Step orchestration, not durable storage or provider behavior. It
asks Context, Model, Tool, and Policy ports for decisions and records every
observable lifecycle change through `HarnessRuntime`/`SessionStore`.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable

from sagents.v2.agent.state import AgentLoopCheckpointState
from sagents.v2.model.contracts import (
    ModelEventKind,
    ModelMessage,
    ModelRequest,
    ModelToolDefinition,
)
from sagents.v2.context import ContextAssembler, DefaultContextAssembler
from sagents.v2.context.session_history import (
    RunLedgerRebuilder,
    SessionHistoryLedgerBuilder,
)
from sagents.v2.model.provider import ModelProvider
from sagents.v2.agent.policy.continuation import (
    CompositeContinuationPolicy,
    ContinuationAction,
    ContinuationContext,
    ContinuationPolicy,
)
from sagents.v2.agent.policy.tool_policy import (
    DefaultToolPolicy,
    ToolPolicyAction,
    ToolPolicyContext,
)
from sagents.v2.tool.contracts import (
    ReconcileResult,
    ReconcileState,
    ToolCall,
    ToolExecutionResult,
)
from sagents.v2.tool.provider import ToolCatalog, ToolExecutor
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
from sagents.v2.runtime.kernel import HarnessRuntime
from sagents.v2.runtime.session.ephemeral import EventDraft


class AgentLoopEngine:
    """Composable model/tool loop with durable, resumable side-effect barriers."""

    def __init__(
        self,
        *,
        runtime: HarnessRuntime,
        model: ModelProvider,
        tool_catalog: ToolCatalog,
        tool_executor: ToolExecutor,
        tool_policy: DefaultToolPolicy | None = None,
        continuation_policy: ContinuationPolicy | None = None,
        context_assembler: ContextAssembler | None = None,
        ledger_rebuilder: RunLedgerRebuilder | None = None,
        clock: Callable = utc_now,
    ) -> None:
        self.runtime = runtime
        self.model = model
        self.tool_catalog = tool_catalog
        self.tool_executor = tool_executor
        self.tool_policy = tool_policy or DefaultToolPolicy()
        self.continuation_policy = continuation_policy or CompositeContinuationPolicy()
        self.context_assembler = context_assembler or DefaultContextAssembler(
            history_reader=runtime.session_store
        )
        self.ledger_rebuilder = ledger_rebuilder or SessionHistoryLedgerBuilder(
            runtime.session_store
        )
        self.clock = clock

    async def execute(self, run_id: str, context: RequestContext) -> RunSnapshot:
        """Start the first Turn for a newly accepted Run."""

        run = await self.runtime.get_run(run_id)
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
        turn_id = new_id("turn")
        messages = await self.context_assembler.initial_ledger(
            command, run_id=run.run_id
        )
        state = AgentLoopCheckpointState(
            turn_id=turn_id,
            step_number=1,
            messages=messages,
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
        return await self._drive(run, state, context)

    async def resume(self, run_id: str, context: RequestContext) -> RunSnapshot:
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
        state = AgentLoopCheckpointState.model_validate(checkpoint.state)
        command = await self.runtime.session_store.get_start_command(run_id)
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
            if state.pending_tool_phase == "reconciliation":
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
                    result = ToolExecutionResult(
                        tool_call_id=state.pending_tool_call.tool_call_id,
                        operation_id=state.pending_tool_call.operation_id,
                        content=(
                            TextBlock(text=f"tool declined: {resolution.decision}"),
                        ),
                        error=RuntimeErrorInfo(
                            code="tool.declined",
                            category=ErrorCategory.POLICY_DENIED,
                            message=f"tool call declined with {resolution.decision}",
                            safe_to_resume=True,
                        ),
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
                    return await self.runtime.get_run(run.run_id)
                input_items = self._interaction_input_items(
                    resolution.payload,
                    interaction_id=interaction.interaction_id,
                    decision=resolution.decision,
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
        max_steps = command.config.max_steps or 24
        model_binding = command.config.model_bindings.get("primary", "primary")
        while run.state == RunState.RUNNING:
            # Phase 1: observe control-plane state only at a safe boundary. A
            # pause never snapshots the middle of arbitrary Python mutation.
            current = await self.runtime.get_run(run.run_id)
            if current.state == RunState.SUSPEND_REQUESTED:
                return await self._suspend_at_safe_point(current, state, context)
            if current.state in TERMINAL_RUN_STATES:
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
            tools = await self.tool_catalog.list_tools(run_id=run.run_id)
            # Phase 2: ContextAssembler creates the provider-facing projection.
            # The raw ledger and canonical RuntimeEvents are left unchanged.
            request = ModelRequest(
                request_id=new_id("model_request"),
                run_id=run.run_id,
                model_binding=model_binding,
                messages=await self.context_assembler.prepare_messages(
                    command, state.messages, run_id=run.run_id
                ),
                tools=tuple(
                    ModelToolDefinition(
                        name=tool.name,
                        description=tool.description,
                        input_schema=tool.input_schema,
                        strict=tool.strict,
                        output_schema=tool.output_schema,
                    )
                    for tool in tools
                ),
                max_output_tokens=(
                    command.config.max_output_tokens
                    or command.config.metadata.get("max_output_tokens")
                ),
                metadata={"turn_id": state.turn_id, "step_id": step_id},
            )
            try:
                # Phase 3: deltas are emitted as replay-buffered events, followed
                # by completed Items that are authoritative for final content.
                run, response, partial_suspension = await self._stream_model(
                    run, request, context, state, step_id
                )
            except SageV2Error as exc:
                return await self._fail(run, state, step_id, exc.info, context)
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
            assistant_message = ModelMessage(
                role="assistant",
                content=(TextBlock(text=response.text),) if response.text else (),
                tool_calls=response.tool_calls,
            )
            state = state.model_copy(
                update={
                    "messages": (*state.messages, assistant_message),
                    "total_input_tokens": state.total_input_tokens
                    + response.usage.input_tokens,
                    "total_output_tokens": state.total_output_tokens
                    + response.usage.output_tokens,
                    "response_fingerprints": (
                        *state.response_fingerprints,
                        self._response_fingerprint(response),
                    ),
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
                        return await self._fail(run, state, step_id, exc.info, context)
                    tool_call = ToolCall(
                        tool_call_id=model_call.tool_call_id,
                        tool_name=model_call.name,
                        arguments=model_call.arguments,
                        operation_id=new_id("operation"),
                        idempotency_key=f"{run.run_id}:{model_call.tool_call_id}",
                        owner_run_id=run.run_id,
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
                        )
                    )
                    run = await self._record_policy(
                        run, tool_call, policy, context, state.turn_id, step_id
                    )
                    if policy.action == ToolPolicyAction.DENY:
                        result = ToolExecutionResult(
                            tool_call_id=tool_call.tool_call_id,
                            operation_id=tool_call.operation_id,
                            content=(TextBlock(text=f"tool denied: {policy.reason}"),),
                            error=RuntimeErrorInfo(
                                code="tool.policy_denied",
                                category=ErrorCategory.POLICY_DENIED,
                                message=policy.reason,
                                safe_to_resume=True,
                            ),
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
                            )
                        }
                    )

            repeated = self._trailing_repeat_count(state.response_fingerprints)
            # Phase 5: completion is policy, not an implicit consequence of EOF
            # or a provider finish_reason.
            decision = await self.continuation_policy.decide(
                ContinuationContext(
                    run_id=run.run_id,
                    step_number=state.step_number,
                    max_steps=max_steps,
                    response=response,
                    pending_tool_calls=0,
                    repeated_fingerprint_count=repeated,
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
            run = await self._record_continuation(
                run, decision, context, state.turn_id, step_id
            )
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
            state = state.model_copy(update={"step_number": state.step_number + 1})
        return run

    async def _stream_model(self, run, request, context, state, step_id):
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
        try:
            async for model_event in stream:
                current = await self.runtime.get_run(run.run_id)
                if current.state == RunState.SUSPEND_REQUESTED:
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
                    run = await self._commit_running(run, context, tuple(drafts))
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
                    run = await self._commit_running(run, context, tuple(drafts))
                else:
                    response = model_event.response
        finally:
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
        if response.text or text_started:
            text_value = response.text or text
            item = self._item(
                text_item_id,
                run.run_id,
                state.turn_id,
                step_id,
                MessageItemData(
                    role="assistant", content=(TextBlock(text=text_value),)
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
                    ),
                ),
            ),
        )

    async def _dispatch_tool(
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
            result = await self.tool_executor.execute(call, context)
        except SageV2Error as exc:
            if exc.info.category == ErrorCategory.UNCERTAIN_SIDE_EFFECT:
                run = await self._record_tool_unknown(
                    run, call, exc.info, context, turn_id, step_id
                )
                return await self._reconcile_or_suspend_tool(
                    run,
                    call,
                    context,
                    turn_id,
                    step_id,
                    state,
                    exc.info,
                )
            result = ToolExecutionResult(
                tool_call_id=call.tool_call_id,
                operation_id=call.operation_id,
                content=(TextBlock(text=exc.info.message),),
                error=exc.info,
            )
        except Exception as exc:
            result = ToolExecutionResult(
                tool_call_id=call.tool_call_id,
                operation_id=call.operation_id,
                content=(TextBlock(text=str(exc)),),
                error=RuntimeErrorInfo(
                    code="tool.provider_error",
                    category=ErrorCategory.PROVIDER_PERMANENT,
                    message=str(exc),
                    safe_to_resume=True,
                ),
            )
        run = await self._commit_tool_result(
            run, call, result, context, turn_id, step_id=step_id
        )
        return run, result

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
                reconciled = await self.tool_executor.reconcile(
                    call.operation_id, context
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
    ):
        """Atomically commit the Tool lifecycle result and model-visible Item."""

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
        )

    async def _suspend_for_tool_uncertainty(
        self, run, state, call, error, context, step_id, definition
    ):
        """Require explicit reconciliation when a Tool outcome is unknowable."""

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
        if definition.supports_reconciliation:
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
                "reason": "tool_outcome_unknown",
                "tool_name": call.tool_name,
                "operation_id": call.operation_id,
                "idempotency_key": call.idempotency_key,
                "supports_reconciliation": definition.supports_reconciliation,
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
        interaction = InteractionRequest(
            interaction_id=interaction_id,
            run_id=run.run_id,
            turn_id=state.turn_id,
            step_id=step_id,
            interaction_type=InteractionType.APPROVAL,
            blocking_scope=BlockingScope.RUN,
            allowed_decisions=policy.allowed_decisions,
            eligible_principal_ids=(context.actor.principal_id,),
            payload=policy.interaction_payload,
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
        checkpoint, suspension = self._checkpoint_records(
            run,
            state.model_copy(update={"step_number": state.step_number + 1}),
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
        checkpoint_state = state.model_dump(mode="json", exclude={"messages"})
        checkpoint_state["state_version"] = "2"
        checkpoint_state["ledger_digest"] = self._ledger_digest(state.messages)
        checkpoint = Checkpoint(
            checkpoint_id=checkpoint_id,
            checkpoint_codec_version="agent-loop/2",
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
        return await self._commit_running(
            run,
            context,
            (
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
                    ),
                ),
            ),
        )

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
        if decision == "change_direction" and not items:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="interaction.input_required",
                    category=ErrorCategory.VALIDATION,
                    message="change_direction requires payload.text, guidance, or input",
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
        result = await self.runtime.session_store.commit_run(
            run_id=run.run_id,
            expected_revision=run.revision,
            expected_states={RunState.RUNNING},
            new_state=RunState.COMPLETED,
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
        return result.run

    async def _fail(self, run, state, step_id, error, context):
        current = await self.runtime.get_run(run.run_id)
        if current.state in TERMINAL_RUN_STATES:
            return current
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
        return result.run

    async def _commit_running(
        self, run, context, drafts, *, expected_states=None
    ) -> RunSnapshot:
        result = await self.runtime.session_store.commit_run(
            run_id=run.run_id,
            expected_revision=run.revision,
            expected_states=expected_states or {RunState.RUNNING},
            new_state=run.state,
            drafts=drafts,
            context=context,
            idempotency_key=new_id("loop_commit"),
        )
        return result.run

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

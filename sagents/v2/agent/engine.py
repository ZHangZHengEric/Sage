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
from datetime import timedelta
from dataclasses import dataclass
from collections.abc import Callable, AsyncGenerator, Awaitable
from typing import Any, cast

from sagents.v2.runtime.execution.ownership import (
    can_defer_run,
    is_lease_loss,
    require_execution_ownership,
)
from sagents.v2.contracts.conversation import order_tool_context
from sagents.v2.agent.progress import inspection_progress, repeated_cycles
from sagents.v2.agent.state import AgentLoopCheckpointCodec, AgentLoopCheckpointState
from sagents.v2.agent.stream_batcher import StreamEventBatcher
from sagents.v2.agent.model_recovery import (
    can_repair_model_arguments,
    argument_recovery_guidance,
)
from sagents.v2.model.contracts import (
    ModelEventKind,
    ModelStreamEvent,
    ModelMessage,
    ModelResponse,
    ModelToolCall,
)
from sagents.v2.agent.step_request import (
    AgentStepRequestBuilder,
    DefaultAgentStepRequestBuilder,
    tools_for_invocation_mode,
)
from sagents.v2.context import ContextAssembler, DefaultContextAssembler
from sagents.v2.context.system_context import with_session_context
from sagents.v2.context.session_history import (
    RunLedgerRebuilder,
    SessionHistoryLedgerBuilder,
)
from sagents.v2.memory import (
    DirectMemoryRecallQueryGenerator,
    MemoryRecallQueryGenerator,
)
from sagents.v2.model.provider import ModelProvider
from sagents.v2.agent.policy.plugins.continuation import CompositeContinuationPolicy
from sagents.v2.agent.policy.continuation import (
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
    ApprovalScope,
)
from sagents.v2.agent.policy.plugins.tool_policy import DefaultToolPolicy
from sagents.v2.agent.policy.tool_policy import ToolPolicyAction, ToolPolicyContext, ToolPolicyDecision
from sagents.v2.tool.contracts import (
    CancelSemantics,
    ReconcileResult,
    ReconcileState,
    ResumeStrategy,
    SideEffectLevel,
    ToolCall,
    ToolCancellationState,
    ToolCancellationResult,
    ToolExecutionResult,
)
from sagents.v2.tool.arguments import apply_system_context_overrides
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
    error_diagnostic_message,
    exception_diagnostic_message,
)
from sagents.v2.contracts.events import (
    CheckpointEventData,
    ContinuationEventData,
    ItemEventData,
    InteractionEventData,
    SkillStateEventData,
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
    ImageBlock,
    ItemSnapshot,
    ItemStatus,
    JsonBlock,
    MessageItemData,
    ReasoningItemData,
    TextBlock,
    ToolCallItemData,
    ToolResultItemData,
    UsageSummary,
)
from sagents.v2.contracts.principals import RequestContext
from sagents.v2.contracts.run_state import (
    RunSnapshot,
    RunState,
    TERMINAL_RUN_STATES,
)
from sagents.v2.contracts.commands import CancelRun, InputItem, StartRun
from sagents.v2.runtime.contracts import RuntimePort
from sagents.v2.runtime.session.contracts import EventDraft
from sagents.v2.prompt_i18n import run_prompt_language
from sagents.v2.i18n import (
    error_recovery_payload,
    localize_error,
    normalize_language,
    recovery_payload,
    tr,
)


from sagents.v2.tool.result_processing import ToolResultProcessor


class _SkillInitializationPaused(Exception):
    """A completed preload is a safe boundary for a requested pause."""


@dataclass(frozen=True)
class _DriveIteration:
    run: RunSnapshot
    state: AgentLoopCheckpointState
    empty_response_retries: int
    context_overflow_retries: int
    stop: bool = False


class AgentLoopEngine:
    # Retry only the uncommitted model request, before Tool dispatch. Partial
    # Items are cancelled and never enter canonical model history.
    _PROVIDER_RETRY_BASE_SECONDS = 1.0
    _PROVIDER_RETRY_MAX_SECONDS = 60.0
    _MAX_TRANSPARENT_EMPTY_RESPONSE_RETRIES = 2
    _MAX_MODEL_ARGUMENT_RECOVERIES = 2

    """Composable model/tool loop with durable, resumable side-effect barriers."""

    def __init__(
        self,
        *,
        runtime: RuntimePort,
        model: ModelProvider,
        tool_catalog: ToolCatalog,
        tool_executor: ToolExecutor,
        tool_result_processor: ToolResultProcessor | None = None,
        tool_result_runtime=None,
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
        self_configuration=None,
        skill_loader=None,
        preload_skills: tuple[str, ...] = (),
        clock: Callable = utc_now,
    ) -> None:
        self.self_configuration = self_configuration
        if self_configuration is not None:
            if step_request_builder is not None:
                raise ValueError(
                    "self configuration requires the standard step request builder"
                )
            from copy import copy

            # Hosts may reuse their base loader for child loops. Keep capability
            # additions private to this Agent rather than mutating that shared loader.
            skill_loader = copy(skill_loader) if skill_loader is not None else None
            tool_catalog, tool_executor = self_configuration.bind(
                tool_catalog, tool_executor, skill_loader
            )
            if context_assembler is None:
                context_assembler = DefaultContextAssembler(
                    history_reader=runtime.session_store
                )
            if not isinstance(context_assembler, DefaultContextAssembler):
                raise ValueError("self configuration requires DefaultContextAssembler")
            context_assembler = copy(context_assembler)
            from sagents.v2.skill.context import (
                AvailableSkillsContextProvider,
                ActiveSkillsContextProvider,
            )

            # Existing providers captured the pre-bind catalog. Replace those
            # references so a freshly registered Skill is discoverable immediately.
            providers = tuple(
                provider
                for provider in context_assembler.providers
                if not isinstance(
                    provider,
                    (AvailableSkillsContextProvider, ActiveSkillsContextProvider),
                )
            )
            assert skill_loader is not None
            context_assembler.providers = (
                *providers,
                AvailableSkillsContextProvider(skill_loader.catalog),
                ActiveSkillsContextProvider(skill_loader),
                self_configuration,
            )
        self.skill_loader = skill_loader
        self.preload_skills = preload_skills
        self._last_skill_states: dict[str, dict] = {}
        self.runtime = runtime
        self.model = model
        self.tool_catalog = tool_catalog
        self.tool_executor = tool_executor
        self.tool_result_processor = tool_result_processor
        self.tool_result_runtime = tool_result_runtime
        self.tool_policy = tool_policy or DefaultToolPolicy()
        # 审批记忆：没有端口时 approve_and_remember 只等价于 approve_once。
        self.approval_memory = approval_memory
        self.tool_selection_policy = (
            tool_selection_policy or RecentToolSelectionPolicy()
        )
        self.tool_selection_model = tool_selection_model or model
        self._prepared_tool_selection_runs: set[str] = set()
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
        self._budget_usage_cache: dict[str, tuple[int, int]] = {}
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
        command = with_session_context(command, run.session_id)
        context = self._context_for_command(context, command)
        await self._prepare_self_configuration(run_id, context)
        await self._restore_skill_state(run_id)
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
            recovery_state=state,
        )
        try:
            run = await self._initialize_skills(run, command, context)
        except _SkillInitializationPaused:
            return await self._suspend_at_safe_point(
                await self.runtime.get_run(run.run_id), state, context
            )
        except Exception as exc:
            return await self._fail_skill_initialization(run, state, command, exc, context)
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
        except BaseException as exc:
            if not tool_selection_task.done():
                tool_selection_task.cancel()
            await asyncio.gather(tool_selection_task, return_exceptions=True)
            if isinstance(exc, Exception):
                error = (
                    exc.info
                    if isinstance(exc, SageV2Error)
                    else RuntimeErrorInfo(
                        code="loop.preparation_failed",
                        category=ErrorCategory.PROVIDER_PERMANENT,
                        message=exception_diagnostic_message(exc),
                        safe_to_resume=True,
                    )
                )
                if self._provider_retry_allowed(error, command, state) and (
                    not self.automatic_memory_recall
                    or (not tool_selection_task.cancelled() and tool_selection_task.exception() is exc)
                ):
                    run, state = await self._schedule_provider_retry(
                        await self.runtime.get_run(run.run_id), state,
                        new_id("step_preparation"), error, command, context,
                    )
                    if can_defer_run(run.run_id):
                        return run
                    return await self._drive(run, state, context)
                return await self._fail(
                    run, state, new_id("step_preparation"), error, context
                )
            raise
        return await self._drive(run, state, context)

    async def _restore_skill_state(self, run_id, *, checkpoint_state=None, legacy=False) -> None:
        if not self.preload_skills or self.skill_loader is None:
            return
        snapshot = checkpoint_state
        if snapshot is None:
            events = await self.runtime.session_store.read_events(run_id)
            snapshot = next((event.data.state for event in reversed(events)
                             if event.type == "skill.state" and isinstance(event.data, SkillStateEventData)), None)
        if snapshot is None and legacy:
            # Old suspended Runs never acquire newly configured defaults.
            snapshot = await self.skill_loader.snapshot_run(run_id)
            snapshot.update(preloads_complete=True, history_initialized=True)
        if snapshot is not None:
            await self.skill_loader.restore_run(run_id, snapshot)
            self._last_skill_states[run_id] = snapshot

    async def _initialize_skills(self, run, command, context) -> RunSnapshot:
        if not self.preload_skills:
            return run
        if self.skill_loader is None:
            raise ValueError("preload_skills requires a skill loading provider")

        async def persist():
            nonlocal run
            current = await self.runtime.get_run(run.run_id)
            try:
                run = await self._commit_running(
                    current, context, (),
                    expected_states={RunState.RUNNING, RunState.SUSPEND_REQUESTED},
                )
            except SageV2Error as exc:
                # A pause can win CAS while the activation snapshot is read.
                # Retry only the state commit, never the completed skill load.
                if exc.info.code != "run.revision_conflict":
                    raise
                current = await self.runtime.get_run(run.run_id)
                if current.state != RunState.SUSPEND_REQUESTED:
                    raise
                run = await self._commit_running(
                    current, context, (), expected_states={RunState.SUSPEND_REQUESTED}
                )
            if run.state == RunState.SUSPEND_REQUESTED:
                raise _SkillInitializationPaused()

        await self.skill_loader.initialize_preloads(
            self.preload_skills, run_id=run.run_id, on_progress=persist
        )
        return run

    async def _fail_skill_initialization(self, run, state, command, exc, context) -> RunSnapshot:
        cause = exc.info if isinstance(exc, SageV2Error) else None
        snapshot = (await self.skill_loader.snapshot_run(run.run_id)
                    if self.skill_loader is not None else {})
        pending = [name for name in self.preload_skills
                   if name not in snapshot.get("processed_preloads", ())]
        error = RuntimeErrorInfo(
            code="skill.preload_failed",
            category=cause.category if cause else ErrorCategory.PROVIDER_PERMANENT,
            message=(f"Skill initialization failed for Agent {command.agent_id!r}, "
                     f"Run {run.run_id!r}, skill {pending[0] if pending else None!r}: "
                     f"{cause.message if cause else exception_diagnostic_message(exc)}"),
            safe_to_resume=cause.safe_to_resume if cause else False,
            retryable=cause.retryable if cause else False,
            metadata={"agent_id": command.agent_id, "run_id": run.run_id,
                      "skill_name": pending[0] if pending else None,
                      "stage": "preload", "cause_code": cause.code if cause else None,
                      "cause": cause.model_dump(mode="json") if cause else None},
        )
        current = await self.runtime.get_run(run.run_id)
        step_id = new_id("step_preload")
        if current.state in TERMINAL_RUN_STATES or (
            current.state == RunState.RUNNING
            and not (error.safe_to_resume or error.retryable)
        ):
            return await self._fail(current, state, step_id, error, context)
        current = await self._commit_running(current, context, (EventDraft(
            type="step.failed", turn_id=state.turn_id, step_id=step_id,
            data=StepEventData(state="failed", error=error),
        ),), expected_states={RunState.RUNNING, RunState.SUSPEND_REQUESTED})
        if current.state == RunState.SUSPEND_REQUESTED:
            return await self._suspend_at_safe_point(current, state, context)
        return await self._fail(current, state, step_id, error, context)

    async def _prepare_self_configuration(self, run_id, context) -> None:
        if self.self_configuration is not None:
            changed = await self.self_configuration.prepare(run_id, context)
            if changed:
                self._prepared_tool_selection_runs.discard(run_id)

    async def _prepare_tool_selection(
        self, *, command, run_id: str, messages, language: str | None
    ) -> None:
        """Prepare once per Run in this engine, including reconstructed engines."""

        if run_id in self._prepared_tool_selection_runs:
            return

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
        self._prepared_tool_selection_runs.add(run_id)

    async def _run_automatic_memory_recall(self, run, state, command, context) -> tuple[RunSnapshot, AgentLoopCheckpointState]:
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
        generate = self.memory_recall_query_generator.generate
        # Third-party query generators using the original port remain compatible.
        query_options = {"run_id": run.run_id}
        if "language" in inspect.signature(generate).parameters:
            query_options["language"] = run_prompt_language(command.config.metadata)
        query = await generate(user_input, **query_options)
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
            arguments=apply_system_context_overrides(
                definition, {"query": query, "top_k": limit}, command.config.metadata
            ),
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
            run, result = await self._commit_tool_result(
                run,
                call,
                result,
                context,
                state.turn_id,
                step_id=step_id,
                declined=True,
            )
        run, followups = await self._persist_followup_user_messages(
            run, (result,), context, state.turn_id, step_id
        )
        state = state.model_copy(
            update={
                "messages": (
                    *state.messages,
                    self._tool_result_message(result),
                    *followups,
                )
            }
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
        """Recover durable loop state without replaying completed side effects.

        Running checkpoints cover model/control work as well as tool batches.
        Legacy Runs without one retain the conservative tool-barrier recovery.
        """

        run = await self.runtime.get_run(run_id)
        self._assert_resolved_spec_compatible(run.resolved_spec_hash)
        if run.state not in {RunState.RUNNING, RunState.SUSPEND_REQUESTED}:
            return run
        command = await self.runtime.session_store.get_start_command(run_id)
        command = with_session_context(command, run.session_id)
        context = self._context_for_command(context, command)
        events = await self.runtime.session_store.read_events(run_id)
        if run.checkpoint_id is not None:
            checkpoint = await self.runtime.session_store.get_checkpoint(
                run.checkpoint_id
            )
            resumed_after_checkpoint = any(
                event.type == "run.resumed"
                and event.run_sequence > checkpoint.run_sequence
                for event in events
            )
            if (
                checkpoint.state.get("execution_checkpoint") is True
                or resumed_after_checkpoint
            ):
                if (
                    checkpoint.checkpoint_codec_version
                    != AgentLoopCheckpointCodec.version
                ):
                    raise SageV2Error(
                        RuntimeErrorInfo(
                            code="loop.checkpoint_incompatible",
                            category=ErrorCategory.UNSUPPORTED_SCHEMA,
                            message="running checkpoint codec is unsupported",
                            safe_to_resume=False,
                        )
                    )
                self._assert_resolved_spec_compatible(
                    run.resolved_spec_hash,
                    checkpoint_hash=checkpoint.resolved_spec_hash,
                )
                state = AgentLoopCheckpointCodec.decode(checkpoint.state)
                prefix = await self.ledger_rebuilder.rebuild(
                    command,
                    run_id=run_id,
                    through_run_sequence=checkpoint.run_sequence,
                )
                if state.ledger_digest != self._ledger_digest(prefix):
                    raise SageV2Error(
                        RuntimeErrorInfo(
                            code="loop.checkpoint_ledger_mismatch",
                            category=ErrorCategory.CORRUPT_STATE,
                            message="canonical Items do not match the running checkpoint ledger",
                            safe_to_resume=False,
                        )
                    )
                messages = await self.ledger_rebuilder.rebuild(command, run_id=run_id)
                await self._restore_skill_state(
                    run_id, checkpoint_state=state.skill_state, legacy=True
                )
                self.tool_selection_policy.restore_expanded_tools(
                    run_id, state.expanded_tool_names
                )
                # Results can land after the model-response checkpoint. Restore
                # expansion from authoritative successful calls, not fresh defaults.
                proposals = {
                    e.data.operation_id: e.data
                    for e in events
                    if e.type == "tool.call.proposed"
                    and isinstance(e.data, ToolEventData)
                }
                for event in events:
                    if (
                        event.type in {"tool.call.succeeded", "tool.call.reconciled"}
                        and isinstance(event.data, ToolEventData)
                        and event.data.error is None
                    ):
                        proposal = proposals.get(event.data.operation_id)
                        if (
                            proposal is not None
                            and proposal.tool_name == "tool_expand_tools"
                        ):
                            self.tool_selection_policy.expand_tools(
                                run_id=run_id,
                                names=tuple(
                                    (proposal.arguments or {}).get("tool_names")
                                    or (proposal.arguments or {}).get("names")
                                    or ()
                                ),
                            )
                if state.self_configuration_revision is not None:
                    if self.self_configuration is None:
                        raise self._conflict(
                            "self_configuration.unavailable",
                            "saved self configuration is unavailable",
                        )
                    await self.self_configuration.verify_checkpoint(
                        run_id, state.self_configuration_revision
                    )
                state = state.model_copy(
                    update={
                        "messages": messages,
                        "pending_questionnaire_completed": (
                            state.pending_questionnaire_completed
                            or self._recovered_questionnaire_completed(
                                run, state, events
                            )
                        ),
                        "expanded_tool_names": self.tool_selection_policy.expanded_tools(
                            run_id
                        ),
                        "total_input_tokens": sum(
                            e.data.usage.input_tokens
                            for e in events
                            if isinstance(e.data, UsageEventData)
                        ),
                        "total_output_tokens": sum(
                            e.data.usage.output_tokens
                            for e in events
                            if isinstance(e.data, UsageEventData)
                        ),
                    }
                )
                if resumed_after_checkpoint and not checkpoint.state.get(
                    "execution_checkpoint"
                ):
                    resolved = next(
                        (
                            event
                            for event in reversed(events)
                            if event.type == "interaction.resolved"
                            and event.run_sequence > checkpoint.run_sequence
                        ),
                        None,
                    )
                    if resolved is not None:
                        assert isinstance(resolved.data, InteractionEventData)
                        interaction_id = resolved.data.interaction_id
                        resolution = (
                            await self.runtime.session_store.get_interaction_resolution(
                                interaction_id
                            )
                        )
                        return await self._continue_resolved_checkpoint(
                            run, state, resolution, interaction_id, command, context
                        )
                return await self._drive(run, state, context)
        await self._restore_skill_state(run_id, legacy=True)
        if any(
            event.type in {"tool.call.succeeded", "tool.call.reconciled"}
            and isinstance(event.data, ToolEventData)
            and event.data.tool_name == "agent_self_configure"
            for event in events
        ):
            if self.self_configuration is None:
                raise self._conflict(
                    "self_configuration.unavailable",
                    "The Run requires its saved self configuration",
                )
            await self.self_configuration.verify_checkpoint(run_id, 0)
        await self._prepare_self_configuration(run_id, context)
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
        tool_data = cast(ToolEventData, started.data)
        assert tool_data.operation_id is not None and tool_data.idempotency_key is not None
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
        proposal_data = cast(ToolEventData, proposal.data) if proposal is not None else None
        proposal_arguments = proposal_data.arguments if proposal_data is not None else None
        proposal_missing = proposal_arguments is None
        call = ToolCall(
            tool_call_id=tool_data.tool_call_id,
            tool_name=tool_data.tool_name,
            # Dispatch has already crossed the side-effect barrier. A damaged
            # pre-dispatch projection must never turn that into a safe replay.
            arguments=proposal_arguments if proposal_arguments is not None else {},
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
            model_argument_recovery_attempts=sum(
                event.type == "step.retry_scheduled"
                and isinstance(event.data, StepEventData)
                and event.data.error is not None
                and can_repair_model_arguments(event.data.error)
                for event in events
            ),
            pending_flow_boundary=command.config.flow_boundary,
            pending_response_step_id=started.step_id,
            pending_response_system_requirements=self._system_requirements(messages),
            total_input_tokens=sum(
                event.data.usage.input_tokens
                for event in events
                if isinstance(event.data, UsageEventData)
            ),
            total_output_tokens=sum(
                event.data.usage.output_tokens
                for event in events
                if isinstance(event.data, UsageEventData)
            ),
        )
        if await self._tool_execution_receipt(run, call) is not None:
            return await self._drive(run, state, context)
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
        unknown_data = cast(ToolEventData, unknown_event.data) if unknown_event is not None else None
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
            else unknown_data.error
            if unknown_data is not None and unknown_data.error is not None
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
        if definition is not None and (
            definition.supports_reconciliation
            or definition.resume_strategy == ResumeStrategy.AGENT_RECOVERY
        ):
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
            run, followups = await self._persist_followup_user_messages(
                run, (result,), context, state.turn_id, started.step_id
            )
            state = state.model_copy(
                update={
                    "pending_questionnaire_completed": (
                        self._validated_questionnaire_result(call, result)
                    ),
                    "messages": (
                        *state.messages,
                        self._tool_result_message(result),
                        *followups,
                    ),
                    "expanded_tool_names": (
                        self.tool_selection_policy.expanded_tools(run.run_id)
                    ),
                }
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

    def _recovered_questionnaire_completed(self, run, state, events) -> bool:
        items = {
            event.item_id: event.data.item
            for event in events
            if isinstance(event.data, ItemEventData) and event.data.item is not None
        }
        for event in events:
            data = event.data
            if (
                event.step_id != state.pending_response_step_id
                or event.type not in {"tool.call.succeeded", "tool.call.reconciled"}
                or not isinstance(data, ToolEventData)
                or data.tool_name != "questionnaire_async"
                or data.error is not None
            ):
                continue
            item = items.get(data.result_item_id)
            if item is None or not isinstance(item.data, ToolResultItemData):
                continue
            assert data.operation_id is not None and data.idempotency_key is not None
            call = ToolCall(
                tool_call_id=data.tool_call_id,
                tool_name=data.tool_name,
                arguments={},
                operation_id=data.operation_id,
                idempotency_key=data.idempotency_key,
                owner_run_id=run.run_id,
            )
            result = ToolExecutionResult(
                tool_call_id=data.tool_call_id,
                operation_id=data.operation_id,
                content=item.data.content,
                metadata=item.data.metadata,
                error=item.data.error,
            )
            if self._validated_questionnaire_result(call, result):
                return True
        return False

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
        await self._restore_skill_state(
            run_id, checkpoint_state=state.skill_state, legacy=True
        )
        if state.self_configuration_revision is not None:
            if self.self_configuration is None:
                raise self._conflict(
                    "self_configuration.unavailable",
                    "The Run requires its saved self configuration",
                )
            await self.self_configuration.verify_checkpoint(
                run_id, state.self_configuration_revision
            )
        self.tool_selection_policy.restore_expanded_tools(
            run_id, state.expanded_tool_names
        )
        command = await self.runtime.session_store.get_start_command(run_id)
        command = with_session_context(command, run.session_id)
        context = self._context_for_command(context, command)
        await self._prepare_self_configuration(run_id, context)
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
        if (
            state.pending_tool_call is not None
            and state.pending_response_step_id is None
        ):
            # Older checkpoints saved only the current barrier, but all calls
            # in its model response are already present in the Item ledger.
            state = state.model_copy(
                update={
                    "pending_response_step_id": state.pending_tool_step_id,
                    "pending_response_system_requirements": self._system_requirements(
                        rebuilt_messages
                    ),
                }
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
        return await self._continue_resolved_checkpoint(
            run, state, resolution, suspension.interaction_id, command, context
        )

    async def _continue_resolved_checkpoint(
        self, run, state, resolution, interaction_id, command, context
    ) -> RunSnapshot:
        settled = bool(
            state.pending_tool_call is not None
            and any(
                message.tool_call_id == state.pending_tool_call.tool_call_id
                for message in self._pending_response_results(state)
            )
        )
        if settled:
            state = state.model_copy(
                update={
                    "pending_tool_call": None,
                    "pending_tool_policy": None,
                    "pending_tool_phase": None,
                    "pending_tool_step_id": None,
                    "pending_tool_error": None,
                    "pending_tool_result": None,
                    "pending_child_interactions": (),
                }
            )
        if state.pending_tool_call is not None:
            if interaction_id is None:
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
                current_policy = None
                if approved:
                    # Host policy may have tightened while this Run was suspended.
                    # A saved approval cannot override a current DENY.
                    definition = await self.tool_catalog.get_tool(
                        state.pending_tool_call.tool_name, run_id=run.run_id
                    )
                    current_policy = await self.tool_policy.decide(
                        ToolPolicyContext(
                            run_id=run.run_id,
                            actor=context.actor,
                            definition=definition,
                            call=state.pending_tool_call,
                            invocation_mode=command.invocation_mode,
                        )
                    )
                    if current_policy.action == ToolPolicyAction.DENY:
                        approved = False
                        run = await self._record_policy(
                            run,
                            state.pending_tool_call,
                            current_policy,
                            context,
                            state.turn_id,
                            state.pending_tool_step_id,
                        )
                if (
                    approved
                    and resolution.decision == REMEMBER_DECISION
                    and current_policy is not None
                    and current_policy.persistent_approval_allowed
                    and state.pending_tool_policy is not None
                    and current_policy.approval_matcher
                    == state.pending_tool_policy.approval_matcher
                ):
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
                    policy_denied = (
                        current_policy is not None
                        and current_policy.action == ToolPolicyAction.DENY
                    )
                    declined_error = localize_error(
                        RuntimeErrorInfo(
                            code="tool.policy_denied"
                            if policy_denied
                            else "tool.declined",
                            category=ErrorCategory.POLICY_DENIED,
                            message=(
                                current_policy.reason
                                if current_policy is not None and policy_denied
                                else f"tool call declined with {resolution.decision}"
                            ),
                            message_key=None
                            if policy_denied
                            else "error.tool.declined",
                            safe_to_resume=True,
                        ),
                        context.language,
                    )
                    feedback = str(resolution.payload.get("text") or "").strip()
                    declined_content = [TextBlock(text=declined_error.message)]
                    if feedback and resolution.decision == "deny":
                        declined_content.append(
                            TextBlock(
                                text=json.dumps(
                                    {"user_feedback": feedback}, ensure_ascii=False
                                )
                            )
                        )
                    result = ToolExecutionResult(
                        tool_call_id=state.pending_tool_call.tool_call_id,
                        operation_id=state.pending_tool_call.operation_id,
                        content=tuple(declined_content),
                        error=declined_error,
                    )
                    run, result = await self._commit_tool_result(
                        run,
                        state.pending_tool_call,
                        result,
                        context,
                        state.turn_id,
                        step_id=state.pending_tool_step_id,
                        declined=True,
                    )
            run, followups = await self._persist_followup_user_messages(
                run,
                (result,),
                context,
                state.turn_id,
                state.pending_tool_step_id,
            )
            state = state.model_copy(
                update={
                    "messages": (
                        *state.messages,
                        self._tool_result_message(result),
                        *followups,
                    ),
                    "pending_questionnaire_completed": (
                        state.pending_questionnaire_completed
                        or self._validated_questionnaire_result(
                            state.pending_tool_call, result
                        )
                    ),
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
                }
            )
        elif interaction_id is not None and resolution is not None and not settled:
            interaction = await self.runtime.session_store.get_interaction(
                interaction_id
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
                if input_items and not any(
                    message.metadata.get("interaction_id") == interaction_id
                    for message in state.messages
                ):
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
        command = with_session_context(command, run.session_id)
        context = self._context_for_command(context, command)
        max_steps = command.config.max_steps or 24
        empty_response_retries = 0
        context_overflow_retries = 0
        while run.state in {RunState.RUNNING, RunState.SUSPEND_REQUESTED}:
            iteration = await self._drive_step(run, state, context, command, max_steps,
                empty_response_retries, context_overflow_retries)
            run, state = iteration.run, iteration.state
            empty_response_retries = iteration.empty_response_retries
            context_overflow_retries = iteration.context_overflow_retries
            if iteration.stop:
                return run
        return run

    async def _drive_step(
        self, run: RunSnapshot, state: AgentLoopCheckpointState,
        context: RequestContext, command: StartRun, max_steps: int,
        empty_response_retries: int, context_overflow_retries: int,
    ) -> _DriveIteration:
        from sagents.v2.runtime.execution.budgets import evaluate_run_budget
        if run.state == RunState.SUSPEND_REQUESTED:
            return _DriveIteration(await self._suspend_at_safe_point(run, state, context), state, empty_response_retries, context_overflow_retries, stop=True)
        budget = await evaluate_run_budget(self.runtime.session_store, run, self.clock(), usage_cache=self._budget_usage_cache)
        if budget.error is not None:
            return _DriveIteration(await self._fail(run, state, None, budget.error, context, allow_recovery=False), state, empty_response_retries, context_overflow_retries, stop=True)
        if state.provider_retry_at is not None:
            delay = max(0, (state.provider_retry_at - self.clock()).total_seconds())
            if budget.deadline is not None:
                delay = min(delay, max(0, (budget.deadline - self.clock()).total_seconds()))
            if delay > 0 and can_defer_run(run.run_id):
                return _DriveIteration(run, state, empty_response_retries, context_overflow_retries, stop=True)
            if command.config.deadline_seconds is not None:
                remaining = command.config.deadline_seconds - max(
                    0, (self.clock() - run.created_at).total_seconds()
                )
                delay = min(delay, max(0, remaining))
            await self._wait_for_model_retry(run.run_id, delay)
            current = await self.runtime.get_run(run.run_id)
            if current.state == RunState.SUSPEND_REQUESTED:
                return _DriveIteration(await self._suspend_at_safe_point(current, state, context), state, empty_response_retries, context_overflow_retries, stop=True)
            if current.state in TERMINAL_RUN_STATES:
                await self._release_run_resources(run.run_id)
                return _DriveIteration(current, state, empty_response_retries, context_overflow_retries, stop=True)
            run = current
            budget = await evaluate_run_budget(self.runtime.session_store, run, self.clock(), usage_cache=self._budget_usage_cache)
            if budget.error is not None:
                return _DriveIteration(await self._fail(run, state, None, budget.error, context, allow_recovery=False), state, empty_response_retries, context_overflow_retries, stop=True)
            state = state.model_copy(update={
                "provider_retry_at": None, "automatic_resume_at": None,
                "automatic_resume_reason": None,
            })
        elif state.automatic_resume_at is not None:
            state = state.model_copy(update={
                "automatic_resume_at": None, "automatic_resume_reason": None,
            })
        try:
            run = await self._initialize_skills(run, command, context)
        except _SkillInitializationPaused:
            return _DriveIteration(await self._suspend_at_safe_point(await self.runtime.get_run(run.run_id), state, context), state, empty_response_retries, context_overflow_retries, stop=True)
        except Exception as exc:
            return _DriveIteration(await self._fail_skill_initialization(run, state, command, exc, context), state, empty_response_retries, context_overflow_retries, stop=True)
        await self._prepare_self_configuration(run.run_id, context)
        if self.self_configuration is not None:
            state = state.model_copy(
                update={
                    "self_configuration_revision": self.self_configuration.revision
                }
            )
        state = state.model_copy(
            update={"messages": order_tool_context(state.messages)}
        )
        # Phase 1: observe control-plane state only at a safe boundary. A
        # pause never snapshots the middle of arbitrary Python mutation.
        current = await self.runtime.get_run(run.run_id)
        if current.state == RunState.SUSPEND_REQUESTED:
            return _DriveIteration(await self._suspend_at_safe_point(current, state, context), state, empty_response_retries, context_overflow_retries, stop=True)
        if current.state in TERMINAL_RUN_STATES:
            await self._release_run_resources(run.run_id)
            return _DriveIteration(current, state, empty_response_retries, context_overflow_retries, stop=True)
        run = current
        if state.pending_response_step_id is not None:
            step_id = state.pending_response_step_id
            response = self._pending_response(state)
            system_requirements = state.pending_response_system_requirements
            available_tools = state.pending_response_tool_names or tuple(
                tool.name
                for tool in await self.tool_catalog.list_tools(run_id=run.run_id)
            )
        else:
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
                        data=StepEventData(
                            state="started", attempt=state.step_number
                        ),
                    ),
                ),
                recovery_state=state,
            )
            # Phase 2: ContextAssembler creates the provider-facing projection.
            # The raw ledger and canonical RuntimeEvents are left unchanged.
            # Resume/recovery can use a fresh engine whose selection plugin has
            # no process-local preparation state. Expanded tools were restored
            # from the checkpoint; prepare the current catalog before select().
            try:
                await self._prepare_tool_selection(
                    command=command,
                    run_id=run.run_id,
                    messages=state.messages,
                    language=context.language,
                )
                prepared_step = await self.step_request_builder.prepare(
                    command=command,
                    run_id=run.run_id,
                    turn_id=state.turn_id,
                    step_id=step_id,
                    messages=state.messages,
                    pending_continuation_reason=state.pending_continuation_reason,
                    language=context.language,
                )
            except SageV2Error as exc:
                if self._provider_retry_allowed(exc.info, command, state):
                    run, state = await self._schedule_provider_retry(
                        run, state, step_id, exc.info, command, context
                    )
                    if can_defer_run(run.run_id):
                        return _DriveIteration(run, state, empty_response_retries, context_overflow_retries, stop=True)
                    return _DriveIteration(run, state, empty_response_retries, context_overflow_retries)
                return _DriveIteration(await self._fail(run, state, step_id, exc.info, context), state, empty_response_retries, context_overflow_retries, stop=True)
            except Exception as exc:
                return _DriveIteration(await self._fail(run, state, step_id, RuntimeErrorInfo(code='loop.request_preparation_failed', category=ErrorCategory.PROVIDER_PERMANENT, message=exception_diagnostic_message(exc), safe_to_resume=True), context), state, empty_response_retries, context_overflow_retries, stop=True)
            request = prepared_step.request
            budget = await evaluate_run_budget(self.runtime.session_store, run, self.clock(), usage_cache=self._budget_usage_cache)
            if budget.error is not None:
                return _DriveIteration(await self._fail(run, state, step_id, budget.error, context, allow_recovery=False), state, empty_response_retries, context_overflow_retries, stop=True)
            if budget.remaining_tokens is not None:
                request = request.model_copy(update={"max_output_tokens": min(
                    request.max_output_tokens or budget.remaining_tokens,
                    budget.remaining_tokens,
                )})
            tools = prepared_step.tools
            system_requirements = self._system_requirements(request.messages)
            available_tools = tuple(tool.name for tool in tools)
            try:
                # Phase 3: deltas are emitted as replay-buffered events, followed
                # by completed Items that are authoritative for final content.
                run, response, partial_suspension = await self._stream_model(
                    run, request, context, state, step_id
                )
            except SageV2Error as exc:
                # The stream may have flushed deltas and cancelled partial
                # Items before raising; use its latest durable revision.
                run = await self.runtime.get_run(run.run_id)
                if run.state == RunState.SUSPEND_REQUESTED:
                    return _DriveIteration(await self._suspend_at_safe_point(run, state.model_copy(update={'retry_model_step': True}), context), state, empty_response_retries, context_overflow_retries, stop=True)
                if run.state in TERMINAL_RUN_STATES:
                    return _DriveIteration(run, state, empty_response_retries, context_overflow_retries, stop=True)
                if self._provider_retry_allowed(exc.info, command, state):
                    run, state = await self._schedule_provider_retry(
                        run, state, step_id, exc.info, command, context
                    )
                    if can_defer_run(run.run_id):
                        return _DriveIteration(run, state, empty_response_retries, context_overflow_retries, stop=True)
                    return _DriveIteration(run, state, empty_response_retries, context_overflow_retries)
                if (
                    can_repair_model_arguments(exc.info)
                    and state.pending_tool_call is None
                    and state.pending_response_step_id is None
                ):
                    run, state = await self._recover_model_arguments(
                        run,
                        state,
                        step_id,
                        exc.info,
                        command,
                        context,
                    )
                    if run.state != RunState.RUNNING:
                        return _DriveIteration(run, state, empty_response_retries, context_overflow_retries, stop=True)
                    return _DriveIteration(run, state, empty_response_retries, context_overflow_retries)
                if (
                    exc.info.code == "model.context_window_exceeded"
                    and context_overflow_retries < 6
                    and callable(
                        getattr(self.context_assembler, "request_compression", None)
                    )
                ):
                    context_overflow_retries += 1
                    cast(Callable[[str], Any], getattr(self.context_assembler, "request_compression"))(run.run_id)
                    retry_error = exc.info.model_copy(
                        update={
                            "metadata": {
                                **exc.info.metadata,
                                "transparent_retry_attempt": context_overflow_retries,
                                "transparent_retry_limit": 6,
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
                                    attempt=context_overflow_retries,
                                    retry_at=self.clock(),
                                    error=retry_error,
                                ),
                            ),
                        ),
                    )
                    return _DriveIteration(run, state, empty_response_retries, context_overflow_retries)
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
                    return _DriveIteration(run, state, empty_response_retries, context_overflow_retries)
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
                return _DriveIteration(await self._fail(run, state, step_id, error, context), state, empty_response_retries, context_overflow_retries, stop=True)
            except Exception as exc:
                return _DriveIteration(await self._fail(run, state, step_id, RuntimeErrorInfo(code='model.provider_error', category=ErrorCategory.PROVIDER_PERMANENT, message=str(exc), safe_to_resume=True), context), state, empty_response_retries, context_overflow_retries, stop=True)
            if partial_suspension is not None:
                return _DriveIteration(partial_suspension, state, empty_response_retries, context_overflow_retries, stop=True)
            assert response is not None
            observe_response = getattr(
                self.step_request_builder, "observe_response", None
            )
            if observe_response is not None:
                observe_response(request, response)
            empty_response_retries = 0
            context_overflow_retries = 0
            state = self._state_after_model_response(
                state, response, step_id, system_requirements, available_tools
            )

        questionnaire_completed = state.pending_questionnaire_completed
        completed_tool_results: list[ToolExecutionResult] = []
        read_tools: set[str] = set()
        if response.tool_calls:
            budget = await evaluate_run_budget(self.runtime.session_store, run, self.clock(), usage_cache=self._budget_usage_cache)
            if budget.error is not None:
                return _DriveIteration(await self._fail(run, state, step_id, budget.error, context, allow_recovery=False), state, empty_response_retries, context_overflow_retries, stop=True)
            # Phase 4: proposal and policy decision are committed before any
            # external ToolExecutor receives the call.
            settled = {
                message.tool_call_id
                for message in self._pending_response_results(state)
            }
            prepared_calls: list[ToolCall] = []
            approval_calls: list[tuple[ToolCall, ToolPolicyDecision]] = []
            crossed = await self._crossed_tool_calls(run, step_id)
            for model_call in response.tool_calls:
                if model_call.tool_call_id in settled:
                    continue
                if model_call.tool_call_id in crossed:
                    prepared_calls.append(crossed[model_call.tool_call_id])
                    continue
                try:
                    definition = await self.tool_catalog.get_tool(
                        model_call.name, run_id=run.run_id
                    )
                except SageV2Error as exc:
                    if exc.info.code == "tool.not_found":
                        # A rejected name has never crossed the execution barrier.
                        # Settle it as Tool feedback, then execute valid siblings.
                        call = ToolCall(
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
                            run, call, context, state.turn_id, step_id
                        )
                        error = RuntimeErrorInfo(
                            code="tool.not_found",
                            category=ErrorCategory.VALIDATION,
                            message=f"Tool {model_call.name!r} is unavailable. Use an exact available Tool name: {', '.join(available_tools)}. No execution occurred.",
                            safe_to_resume=True,
                            metadata={
                                "side_effect_state": "not_applied",
                                "tool_execution_started": False,
                            },
                        )
                        result = ToolExecutionResult(
                            tool_call_id=call.tool_call_id,
                            operation_id=call.operation_id,
                            error=error,
                            content=(TextBlock(text=error.message),),
                        )
                        run, result = await self._commit_tool_result(
                            run,
                            call,
                            result,
                            context,
                            state.turn_id,
                            step_id=step_id,
                        )
                        state = state.model_copy(
                            update={
                                "messages": (
                                    *state.messages,
                                    self._tool_result_message(result),
                                )
                            }
                        )
                        completed_tool_results.append(result)
                        continue
                    return _DriveIteration(await self._fail(run, state, step_id, exc.info, context), state, empty_response_retries, context_overflow_retries, stop=True)
                if definition.side_effect_level.value in {"read", "none"}:
                    read_tools.add(definition.name)
                tool_call = ToolCall(
                    tool_call_id=model_call.tool_call_id,
                    tool_name=model_call.name,
                    arguments=apply_system_context_overrides(
                        definition, model_call.arguments, command.config.metadata
                    ),
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
                    run, result = await self._commit_tool_result(
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
                    completed_tool_results.append(result)
                    continue
                if policy.action == ToolPolicyAction.REQUIRE_INTERACTION:
                    approval_calls.append((tool_call, policy))
                else:
                    prepared_calls.append(tool_call)

            run, state, batch_results = await self._execute_tool_batch(
                run, prepared_calls, crossed, context, state, step_id
            )
            completed_tool_results.extend(batch_results.values())
            questionnaire_completed = state.pending_questionnaire_completed
            if run.state in TERMINAL_RUN_STATES:
                return _DriveIteration(run, state, empty_response_retries, context_overflow_retries, stop=True)
            for tool_call in prepared_calls:
                if tool_call.tool_call_id in batch_results:
                    continue
                run, result = await self._dispatch_tool(
                    run, tool_call, context, state.turn_id, step_id, state
                )
                if result is None:
                    return _DriveIteration(run, state, empty_response_retries, context_overflow_retries, stop=True)
                questionnaire_completed = (
                    questionnaire_completed
                    or self._validated_questionnaire_result(tool_call, result)
                )
                # Persist supplemental context before a later sibling can
                # suspend, so resume cannot lose an already-settled result's context.
                run, followups = await self._persist_followup_user_messages(
                    run, (result,), context, state.turn_id, step_id
                )
                state = state.model_copy(
                    update={
                        "pending_questionnaire_completed": questionnaire_completed,
                        "messages": order_tool_context(
                            (
                                *state.messages,
                                self._tool_result_message(result),
                                *followups,
                            )
                        ),
                        "expanded_tool_names": (
                            self.tool_selection_policy.expanded_tools(run.run_id)
                        ),
                    }
                )
                completed_tool_results.append(
                    result.model_copy(
                        update={
                            "metadata": {
                                key: value
                                for key, value in result.metadata.items()
                                if key != "followup_user_message"
                            },
                        }
                    )
                )
            if run.state == RunState.SUSPEND_REQUESTED:
                run, followups = await self._persist_followup_user_messages(
                    run, completed_tool_results, context, state.turn_id, step_id
                )
                state = state.model_copy(
                    update={
                        "messages": (*state.messages, *followups),
                    }
                )
                return _DriveIteration(await self._suspend_at_safe_point(run, state, context), state, empty_response_retries, context_overflow_retries, stop=True)
            if approval_calls:
                tool_call, policy = approval_calls[0]
                run, followups = await self._persist_followup_user_messages(
                    run, completed_tool_results, context, state.turn_id, step_id
                )
                state = state.model_copy(
                    update={
                        "messages": (*state.messages, *followups),
                        "pending_tool_call": tool_call,
                        "pending_tool_policy": policy,
                        "pending_tool_phase": "approval",
                        "pending_tool_step_id": step_id,
                    }
                )
                return _DriveIteration(await self._suspend_for_tool_approval(run, state, policy, context, step_id), state, empty_response_retries, context_overflow_retries, stop=True)
            run, followups = await self._persist_followup_user_messages(
                run,
                completed_tool_results,
                context,
                state.turn_id,
                step_id,
            )
            if followups:
                state = state.model_copy(
                    update={"messages": (*state.messages, *followups)}
                )

        state = state.model_copy(
            update={"messages": order_tool_context(state.messages)}
        )
        state = inspection_progress(
            state, response, completed_tool_results, read_tools
        )
        repeated = repeated_cycles(state.response_fingerprints)
        budget = await evaluate_run_budget(self.runtime.session_store, run, self.clock(), usage_cache=self._budget_usage_cache)
        if budget.error is not None:
            return _DriveIteration(await self._fail(run, state, step_id, budget.error, context, allow_recovery=False), state, empty_response_retries, context_overflow_retries, stop=True)
        signals = await self._continuation_signals(run.run_id, state)
        # Phase 5: completion is policy, not an implicit consequence of EOF
        # or a provider finish_reason.
        continuation_context = ContinuationContext(
            run_id=run.run_id,
            step_number=state.step_number,
            max_steps=max_steps,
            response=response,
            ledger=state.messages,
            language=run_prompt_language(command.config.metadata),
            agent_system_requirements=system_requirements,
            available_tools=available_tools,
            pending_tool_calls=0,
            repeated_fingerprint_count=repeated,
            no_progress_steps=state.no_progress_steps,
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
        if questionnaire_completed:
            # Match the established questionnaire_async contract: a
            # successfully validated result is a terminal boundary for this
            # Run, while the answer arrives as the next user turn. The
            # durable Tool result remains the UI's questionnaire source.
            decision = ContinuationDecision(
                action=ContinuationAction.COMPLETE_RUN,
                reason_code="tool.questionnaire_ready",
                reason="validated questionnaire is awaiting the next user turn",
                metadata={
                    "source": "questionnaire_async",
                    "awaiting_user_input": True,
                },
            )
        else:
            decision = await self.continuation_policy.decide(continuation_context)
        if decision.usage.input_tokens or decision.usage.output_tokens:
            state = state.model_copy(
                update={
                    "total_input_tokens": state.total_input_tokens
                    + decision.usage.input_tokens,
                    "total_output_tokens": state.total_output_tokens
                    + decision.usage.output_tokens,
                }
            )
        advance_stage = (
            decision.action == ContinuationAction.REQUEST_INTERACTION
            and decision.reason_code in {"budget.max_steps", "status.missing_at_limit"}
            and command.config.automatic_stage_continuation
            and command.config.flow_boundary is None
            and (command.config.max_stages is None or state.stage_number < command.config.max_stages)
            and (command.config.deadline_seconds is None or continuation_context.elapsed_seconds < command.config.deadline_seconds)
            and (continuation_context.max_total_tokens is None or state.total_input_tokens + state.total_output_tokens < continuation_context.max_total_tokens)
        )
        if advance_stage:
            decision = decision.model_copy(update={
                "action": ContinuationAction.CONTINUE_STEP,
                "reason_code": "stage.continue",
                "reason": "continue the task in the next checkpointed execution stage",
                "interaction": None,
            })
        run = await self._record_continuation(
            run, decision, context, state.turn_id, step_id
        )
        state = state.model_copy(
            update={
                "pending_response_step_id": None,
                "pending_response_system_requirements": "",
                "pending_response_tool_names": (),
                "pending_questionnaire_completed": False,
            }
        )
        if decision.reason_code in {"flow.node_complete", "flow.node_continue"}:
            state = state.model_copy(update={"pending_flow_boundary": None})
        if decision.action == ContinuationAction.COMPLETE_RUN:
            return _DriveIteration(await self._complete(run, state, step_id, context), state, empty_response_retries, context_overflow_retries, stop=True)
        if decision.action == ContinuationAction.FAIL:
            return _DriveIteration(await self._fail(run, state, step_id, decision.error or RuntimeErrorInfo(code=decision.reason_code, category=ErrorCategory.VALIDATION, message=decision.reason, safe_to_resume=True), context), state, empty_response_retries, context_overflow_retries, stop=True)
        if advance_stage:
            completed_step = state.step_number
            state = state.model_copy(update={
                "stage_number": state.stage_number + 1, "step_number": 1,
                "automatic_resume_at": self.clock(),
                "automatic_resume_reason": "stage.continue",
                "pending_continuation_reason": (
                    "Continue the original task from the saved results. "
                    "This is a new execution stage, not a new user request. "
                    "Preserve completed work and verify remaining requirements."
                ),
            })
            run = await self._commit_running(
                run, context, (EventDraft(
                    type="step.completed", turn_id=state.turn_id, step_id=step_id,
                    data=StepEventData(state="completed", attempt=completed_step),
                ), EventDraft(
                    type="step.retry_scheduled", turn_id=state.turn_id, step_id=step_id,
                    data=StepEventData(state="stage_scheduled", attempt=state.stage_number, retry_at=state.automatic_resume_at),
                ),), recovery_state=state,
            )
            if can_defer_run(run.run_id):
                return _DriveIteration(run, state, empty_response_retries, context_overflow_retries, stop=True)
            return _DriveIteration(run, state, empty_response_retries, context_overflow_retries)
        if decision.action == ContinuationAction.REQUEST_INTERACTION:
            return _DriveIteration(await self._suspend_for_continuation_interaction(run, state, decision, context, step_id), state, empty_response_retries, context_overflow_retries, stop=True)
        if decision.action in {
            ContinuationAction.COMPLETE_TURN,
            ContinuationAction.HANDOFF,
        }:
            return _DriveIteration(await self._complete(run, state, step_id, context), state, empty_response_retries, context_overflow_retries, stop=True)
        continuation_reason = None
        if (
            decision.action == ContinuationAction.CONTINUE_STEP
            and decision.reason
            and decision.reason_code
            in {
                "response.output_limit",
                "plan.explanation_required",
                "plan.required",
                "goal.explanation_required",
                "goal.incomplete",
                "judge.continue",
                "judge.explanation_required",
                "judge.v1_must_continue",
                "openui.validation_retry",
                "output.self_check_retry",
            }
        ):
            continuation_reason = self._normalized_continuation_reason(
                decision.reason,
                limit=6000
                if decision.reason_code
                in {"openui.validation_retry", "output.self_check_retry"}
                else 240,
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
        run = await self._commit_running(
            run,
            context,
            (
                EventDraft(
                    type="step.completed",
                    turn_id=state.turn_id,
                    step_id=step_id,
                    data=StepEventData(
                        state="completed", attempt=state.step_number - 1
                    ),
                ),
            ),
            recovery_state=state,
        )
        return _DriveIteration(run, state, empty_response_retries, context_overflow_retries)

    def _state_after_model_response(
        self, state, response, step_id, requirements, tools
    ) -> AgentLoopCheckpointState:
        messages = state.messages
        if response.text or response.tool_calls or response.provider_state:
            messages = (
                *messages,
                ModelMessage(
                    role="assistant",
                    content=(TextBlock(text=response.text),) if response.text else (),
                    tool_calls=response.tool_calls,
                    provider_state=response.provider_state,
                ),
            )
        return state.model_copy(
            update={
                "messages": messages,
                "total_input_tokens": state.total_input_tokens
                + response.usage.input_tokens,
                "total_output_tokens": state.total_output_tokens
                + response.usage.output_tokens,
                "response_fingerprints": (
                    *state.response_fingerprints,
                    self._response_fingerprint(response),
                )[-48:],
                "retry_model_step": False,
                "provider_retry_attempts": 0,
                "provider_retry_at": None,
                "force_tool_choice_required_next": False,
                "pending_continuation_reason": None,
                "pending_response_step_id": step_id,
                "pending_response_finish_reason": response.finish_reason,
                "pending_response_has_message": bool(
                    response.text or response.tool_calls or response.provider_state
                ),
                "pending_response_system_requirements": requirements,
                "pending_response_tool_names": tuple(tools),
            }
        )

    @staticmethod
    def _pending_response_results(
        state: AgentLoopCheckpointState,
    ) -> tuple[ModelMessage, ...]:
        """Results from this response only; call IDs may recur in older steps."""
        for index in range(len(state.messages) - 1, -1, -1):
            if state.messages[index].role == "assistant":
                return tuple(
                    message
                    for message in state.messages[index + 1 :]
                    if message.role == "tool"
                )
        return ()

    @staticmethod
    def _pending_response(state: AgentLoopCheckpointState) -> ModelResponse:
        """Rebuild the unfinished batch without copying ledger text into checkpoints."""
        message = (
            next(
                (
                    message
                    for message in reversed(state.messages)
                    if message.role == "assistant"
                ),
                None,
            )
            if state.pending_response_has_message
            else None
        )
        return ModelResponse(
            response_id=state.pending_response_step_id or "recovered-response",
            text=""
            if message is None
            else "\n".join(
                block.text for block in message.content if isinstance(block, TextBlock)
            ),
            tool_calls=() if message is None else message.tool_calls,
            finish_reason=state.pending_response_finish_reason,
            provider_state={} if message is None else message.provider_state,
        )

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
    def _normalized_continuation_reason(reason: str, *, limit: int = 240) -> str | None:
        value = " ".join(str(reason or "").split()).strip()
        if not value:
            return None
        return value[:limit].replace("<", "[").replace(">", "]").strip()

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

    @staticmethod
    def _validated_questionnaire_result(
        call: ToolCall, result: ToolExecutionResult
    ) -> bool:
        if call.tool_name != "questionnaire_async" or result.error is not None:
            return False
        payload = None
        for block in result.content:
            if isinstance(block, JsonBlock) and isinstance(block.value, dict):
                payload = block.value
                break
            if not isinstance(block, TextBlock) or not block.text.strip():
                continue
            try:
                value = json.loads(block.text)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                payload = value
                break
        if not isinstance(payload, dict):
            return False
        questions = payload.get("questions")
        return (
            payload.get("success") is True
            and payload.get("validation_passed") is True
            and isinstance(questions, list)
            and bool(questions)
            and payload.get("should_end") is True
        )

    async def _recover_model_arguments(
        self, run, state, step_id, error, command, context
    ) -> tuple[RunSnapshot, AgentLoopCheckpointState]:
        """Checkpoint a bounded inference repair; never retry a Tool execution."""
        run = await self.runtime.get_run(run.run_id)
        if run.state in TERMINAL_RUN_STATES:
            return run, state
        usage = UsageSummary.model_validate(error.metadata.get("usage") or {})
        state = state.model_copy(
            update={
                "total_input_tokens": state.total_input_tokens + usage.input_tokens,
                "total_output_tokens": state.total_output_tokens + usage.output_tokens,
            }
        )
        usage_draft = EventDraft(
            type="usage.recorded",
            turn_id=state.turn_id,
            step_id=step_id,
            data=UsageEventData(usage=usage),
        )
        max_tokens = command.config.max_total_tokens or command.config.metadata.get(
            "max_total_tokens"
        )
        budget_error = None
        if (
            max_tokens
            and state.total_input_tokens + state.total_output_tokens >= max_tokens
        ):
            budget_error = "budget.max_tokens"
        elif (
            command.config.deadline_seconds is not None
            and (self.clock() - run.created_at).total_seconds()
            >= command.config.deadline_seconds
        ):
            budget_error = "budget.deadline"
        exhausted = (
            state.model_argument_recovery_attempts
            >= self._MAX_MODEL_ARGUMENT_RECOVERIES
        )
        if (
            budget_error
            or exhausted
            or state.step_number >= (command.config.max_steps or 24)
        ):
            run = await self._commit_running(
                run, context, (usage_draft,), expected_states={run.state}
            )
            if budget_error:
                error = RuntimeErrorInfo(
                    code=budget_error,
                    category=ErrorCategory.VALIDATION,
                    message=tr("error." + budget_error, context.language),
                    safe_to_resume=True,
                    metadata={"model_error_code": error.code},
                )
            else:
                error = error.model_copy(
                    update={
                        "message_key": "error.model.argument_recovery_exhausted"
                        if exhausted
                        else "recovery.max_steps",
                        "metadata": {
                            **error.metadata,
                            "transparent_retries_exhausted": True,
                            "transparent_retry_limit": self._MAX_MODEL_ARGUMENT_RECOVERIES,
                        },
                    }
                )
            return await self._fail(run, state, step_id, error, context), state
        attempt = state.model_argument_recovery_attempts + 1
        state = state.model_copy(
            update={
                "model_argument_recovery_attempts": attempt,
                "pending_continuation_reason": argument_recovery_guidance(error),
                "retry_model_step": True,
                "step_number": state.step_number + 1,
            }
        )
        if run.state == RunState.SUSPEND_REQUESTED:
            run = await self._commit_running(
                run,
                context,
                (usage_draft,),
                expected_states={RunState.SUSPEND_REQUESTED},
            )
            return await self._suspend_at_safe_point(run, state, context), state
        retry_error = error.model_copy(
            update={
                "metadata": {
                    **{
                        key: value
                        for key, value in error.metadata.items()
                        if key != "raw_arguments"
                    },
                    "transparent_retry_attempt": attempt,
                    "transparent_retry_limit": self._MAX_MODEL_ARGUMENT_RECOVERIES,
                }
            }
        )
        checkpoint, _ = await self._checkpoint_records(
            run, state, reason=SuspensionReason.MANUAL_PAUSE
        )
        checkpoint = checkpoint.model_copy(
            update={
                "state": {**checkpoint.state, "execution_checkpoint": True},
            }
        )
        committed = await self.runtime.session_store.commit_run(
            run_id=run.run_id,
            expected_revision=run.revision,
            expected_states={RunState.RUNNING},
            new_state=RunState.RUNNING,
            drafts=(
                usage_draft,
                EventDraft(
                    type="step.retry_scheduled",
                    turn_id=state.turn_id,
                    step_id=step_id,
                    data=StepEventData(
                        state="retry_scheduled",
                        attempt=attempt,
                        retry_at=self.clock(),
                        error=retry_error,
                    ),
                ),
            ),
            checkpoint=checkpoint,
            context=context,
            idempotency_key=f"model-argument-repair:{run.run_id}:{step_id}",
        )
        return committed.run, state

    async def _stream_model(self, run, request, context, state, step_id) -> tuple[RunSnapshot, ModelResponse | None, RunSnapshot | None]:
        return await self.stream_model_step(run, request, context, state, step_id)

    @staticmethod
    def _provider_retry_allowed(error, command, state) -> bool:
        limit = command.config.transient_retry_limit
        return (
            error.retryable
            and error.category in {ErrorCategory.PROVIDER_TRANSIENT, ErrorCategory.RATE_LIMITED}
            and error.code != "model.empty_semantic_response"
            and state.pending_tool_call is None
            and state.pending_response_step_id is None
            and (limit is None or state.provider_retry_attempts < limit)
        )

    async def _schedule_provider_retry(self, run, state, step_id, error, command, context) -> tuple[RunSnapshot, AgentLoopCheckpointState]:
        # Only uncommitted inference/preparation is retried. Never redispatch
        # completed tools or replay a tool whose remote outcome is unknown.
        attempt = state.provider_retry_attempts + 1
        delay = min(
            self._PROVIDER_RETRY_MAX_SECONDS,
            self._PROVIDER_RETRY_BASE_SECONDS * 2 ** min(attempt - 1, 16),
        )
        retry_at = self.clock() + timedelta(seconds=delay)
        if command.config.deadline_seconds is not None:
            retry_at = min(retry_at, run.created_at + timedelta(seconds=command.config.deadline_seconds))
        state = state.model_copy(update={
            "provider_retry_attempts": attempt,
            "provider_retry_at": retry_at,
            "retry_model_step": True,
            "automatic_resume_at": retry_at,
            "automatic_resume_reason": "provider.retry",
        })
        error = localize_error(error, context.language)
        error = error.model_copy(update={
            "metadata": {
                **error.metadata,
                "transparent_retry_attempt": attempt,
                "transparent_retry_limit": command.config.transient_retry_limit,
                "retry_delay_seconds": delay,
                "automatic_recovery": True,
            },
        })
        run = await self._commit_running(
            run, context,
            (EventDraft(
                type="step.retry_scheduled", turn_id=state.turn_id, step_id=step_id,
                data=StepEventData(
                    state="retry_scheduled", attempt=attempt, retry_at=retry_at, error=error,
                ),
            ),),
            recovery_state=state,
        )
        return run, state

    async def _wait_for_model_retry(self, run_id, delay) -> None:
        until = asyncio.get_running_loop().time() + delay
        while (remaining := until - asyncio.get_running_loop().time()) > 0:
            await asyncio.sleep(min(0.1, remaining))
            if (await self.runtime.get_run(run_id)).state != RunState.RUNNING:
                return

    async def _control_aware_model_events(self, stream, run, command) -> AsyncGenerator[tuple[ModelStreamEvent | None, RunSnapshot | None], None]:
        """Poll durable control/deadline state without cancelling socket reads."""

        from sagents.v2.runtime.execution.budgets import evaluate_run_budget

        budget = await evaluate_run_budget(self.runtime.session_store, run, self.clock(), check_tokens=False)
        iterator = stream.__aiter__()
        pending = None
        poll_seconds = 0.1
        try:
            while True:
                if pending is None:
                    pending = asyncio.create_task(anext(iterator))
                timeout = poll_seconds
                deadline_expired = False
                if budget.deadline is not None:
                    remaining = (budget.deadline - self.clock()).total_seconds()
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
                    expired = await evaluate_run_budget(self.runtime.session_store, run, self.clock(), check_tokens=False)
                    if expired.error is not None:
                        raise SageV2Error(expired.error)
                current = await self.runtime.get_run(run.run_id)
                if current.state != RunState.RUNNING:
                    yield None, current
                    return
        finally:
            if pending is not None and not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)

    async def stream_model_step(self, run, request, context, state, step_id) -> tuple[RunSnapshot, ModelResponse | None, RunSnapshot | None]:
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
        command = with_session_context(command, run.session_id)
        controlled_events = self._control_aware_model_events(stream, run, command)

        async def commit_delta_batch(batch_run, drafts):
            return await self.runtime.session_store.commit_model_stream_batch(
                run=batch_run,
                drafts=drafts,
                context=context,
                idempotency_key=new_id("loop_commit"),
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
            if response is None:
                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="model.stream_incomplete",
                        category=ErrorCategory.PROVIDER_TRANSIENT,
                        message="model stream ended without a completed response",
                        retryable=True,
                        safe_to_resume=True,
                        metadata={
                            "response_started": text_started or reasoning_started
                        },
                    )
                )
        except SageV2Error as exc:
            if (
                can_repair_model_arguments(exc.info)
                or (
                    exc.info.category
                    in {ErrorCategory.PROVIDER_TRANSIENT, ErrorCategory.RATE_LIMITED}
                    and exc.info.retryable
                )
                or (
                    exc.info.code == "model.context_window_exceeded"
                    and exc.info.retryable
                )
            ):
                run = await batcher.flush()
                current = await self.runtime.get_run(run.run_id)
                if current.state == RunState.RUNNING:
                    cancelled_drafts = tuple(
                        self._partial_item_draft(
                            run.run_id,
                            state.turn_id,
                            step_id,
                            item_id,
                            content,
                            reasoning=is_reasoning,
                            status=ItemStatus.CANCELLED,
                        )
                        for item_id, content, is_reasoning, started in (
                            (text_item_id, text, False, text_started),
                            (reasoning_item_id, reasoning, True, reasoning_started),
                        )
                        if started
                    )
                    if cancelled_drafts:
                        run = await self._commit_running(current, context, cancelled_drafts)
                        await batcher.observe_run(run)
            if text_started or reasoning_started:
                raise SageV2Error(
                    exc.info.model_copy(
                        update={
                            "metadata": {**exc.info.metadata, "response_started": True},
                        }
                    )
                ) from exc
            raise
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
        assert response is not None
        # Some providers leave the final text empty and deliver it only as
        # deltas. The response checkpoint must describe the exact committed Item.
        if text and not response.text:
            response = response.model_copy(update={"text": text})
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
        recovery_state = self._state_after_model_response(
            state, response, step_id, self._system_requirements(request.messages),
            tuple(tool.name for tool in request.tools),
        )
        run = await self._commit_running(
            run, context, tuple(drafts), recovery_state=recovery_state
        )
        return run, response, None

    async def _record_tool_proposal(self, run, call, context, turn_id, step_id) -> RunSnapshot:
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

    async def _record_policy(self, run, call, policy, context, turn_id, step_id) -> RunSnapshot:
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

    async def _consult_approval_memory(self, run, policy) -> ToolPolicyDecision:
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

    async def _remember_tool_approval(self, run, state, resolution, context) -> RunSnapshot:
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
            scope=cast(ApprovalScope, scope),
            remembered_at=self.clock(),
            remembered_by=context.actor.principal_id,
        )
        await self.approval_memory.remember(
            session_id=run.session_id, approval=approval
        )
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
    ) -> tuple[RunSnapshot, ToolExecutionResult | None]:
        return await self.dispatch_tool_call(
            run, call, context, turn_id, step_id=step_id, state=state
        )

    async def _execute_tool_with_control(self, run, call, context) -> tuple[RunSnapshot, ToolExecutionResult | None]:
        """Interrupt only when both Tool metadata and Executor permit it."""

        from sagents.v2.runtime.execution.budgets import evaluate_run_budget

        budget = await evaluate_run_budget(self.runtime.session_store, run, self.clock(), check_tokens=False)
        definition = await self.tool_catalog.get_tool(call.tool_name, run_id=run.run_id)
        command = await self.runtime.session_store.get_start_command(run.run_id)
        command = with_session_context(command, run.session_id)
        execution = asyncio.create_task(self.tool_executor.execute(call, context))
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
                    budget.deadline is not None and self.clock() >= budget.deadline
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
                cancellation = await cast(Callable[..., Awaitable[ToolCancellationResult]], cancel)(call.operation_id, context)
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

    @staticmethod
    def _log_tool_exception(exc, run, call, turn_id, step_id) -> None:
        """Optional observer hook; execution never depends on logging."""

    def _apply_tool_expansion(self, call, result) -> None:
        if result.error is None and call.tool_name == "tool_expand_tools":
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

    async def _crossed_tool_calls(self, run, step_id) -> dict[str, ToolCall]:
        """Original calls that crossed the durable barrier, never safe to replay."""
        events = await self.runtime.session_store.read_events(run.run_id)
        command = await self.runtime.session_store.get_start_command(run.run_id)
        proposals = {
            event.data.operation_id: event.data
            for event in events
            if event.type == "tool.call.proposed"
            and event.step_id == step_id
            and isinstance(event.data, ToolEventData)
        }
        calls = {}
        for event in events:
            if event.type != "tool.call.started" or event.step_id != step_id or not isinstance(event.data, ToolEventData):
                continue
            data = event.data
            assert data.operation_id is not None and data.idempotency_key is not None
            proposal = proposals.get(data.operation_id)
            calls[data.tool_call_id] = ToolCall(
                tool_call_id=data.tool_call_id,
                tool_name=data.tool_name,
                arguments=proposal.arguments
                if proposal and proposal.arguments is not None
                else {},
                operation_id=data.operation_id,
                idempotency_key=data.idempotency_key,
                owner_run_id=run.run_id,
                owner_agent_id=command.agent_id,
                owner_session_id=run.session_id,
            )
        return calls

    async def _tool_execution_receipt(self, run, call) -> ToolExecutionResult | None:
        events = await self.runtime.session_store.read_events(run.run_id)
        for event in reversed(events):
            if (
                event.type == "tool.call.received"
                and isinstance(event.data, ToolEventData)
                and event.data.operation_id == call.operation_id
            ):
                result = ToolExecutionResult.model_validate(event.data.execution_result)
                if not result.metadata.get("delegation_deferred_until"):
                    return result
        return None

    async def _execute_tool_batch(self, run, calls, crossed, context, state, step_id) -> tuple[RunSnapshot, AgentLoopCheckpointState, dict[str, ToolExecutionResult]]:
        """Execute siblings concurrently; one owner serializes durable receipts.

        All receipts are durable before any result can suspend the whole Run.
        Recovery consumes receipts or reconciles started operations, never
        repeats a side effect merely because a sibling needed user input.
        """
        turn_id = state.turn_id
        results = {}
        fresh = [call for call in calls if call.tool_call_id not in crossed]
        if len(calls) <= 1:
            return run, state, results
        for call in fresh:
            run = await self._start_tool_execution(run, call, context, turn_id, step_id)

        async def execute(call):
            _, result = await self._capture_tool_execution(
                run, call, context, turn_id, step_id
            )
            return call, result

        tasks = [asyncio.create_task(execute(call)) for call in fresh]
        try:
            for future in asyncio.as_completed(tasks):
                call, result = await future
                run = await self.runtime.get_run(run.run_id)
                if result is None or run.state in TERMINAL_RUN_STATES:
                    continue
                # Publish ordinary successes immediately, without waiting for a
                # slow sibling. Decisions that can suspend the Run wait until
                # every execution has drained and its receipt is durable.
                if (
                    result.error is None
                    and not result.metadata.get("delegation_interactions")
                    and not result.metadata.get("delegation_deferred_until")
                    and not result.metadata.get("followup_user_message")
                ):
                    self._apply_tool_expansion(call, result)
                    run, result = await self._commit_tool_result(
                        run,
                        call,
                        result,
                        context,
                        turn_id,
                        step_id=step_id,
                        expected_states={RunState.RUNNING, RunState.SUSPEND_REQUESTED},
                    )
                    results[call.tool_call_id] = result
                    state = state.model_copy(
                        update={
                            "messages": (
                                *state.messages,
                                self._tool_result_message(result),
                            ),
                            "pending_questionnaire_completed": (
                                state.pending_questionnaire_completed
                                or self._validated_questionnaire_result(call, result)
                            ),
                            "expanded_tool_names": self.tool_selection_policy.expanded_tools(
                                run.run_id
                            ),
                        }
                    )
                else:
                    run = await self._commit_running(
                        run,
                        context,
                        (
                            EventDraft(
                                type="tool.call.received",
                                turn_id=turn_id,
                                step_id=step_id,
                                data=ToolEventData(
                                    tool_call_id=call.tool_call_id,
                                    tool_name=call.tool_name,
                                    operation_id=call.operation_id,
                                    idempotency_key=call.idempotency_key,
                                    state="received",
                                    execution_result=result.model_dump(mode="json"),
                                ),
                            ),
                        ),
                        expected_states={RunState.RUNNING, RunState.SUSPEND_REQUESTED},
                    )
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            run = await self.runtime.get_run(run.run_id)
            if run.state in TERMINAL_RUN_STATES:
                await self._release_run_resources(run.run_id)
            elif run.state in {RunState.RUNNING, RunState.SUSPEND_REQUESTED}:
                for call, task in zip(fresh, tasks, strict=True):
                    if task.cancelled():
                        run = await self._record_cancelled_execution(
                            run, call, context, turn_id, step_id
                        )
        return await self.runtime.get_run(run.run_id), state, results

    async def _start_tool_execution(self, run, call, context, turn_id, step_id) -> RunSnapshot:
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
        return run

    async def _record_cancelled_execution(self, run, call, context, turn_id, step_id) -> RunSnapshot:
        return await self._record_tool_unknown(
            run,
            call,
            RuntimeErrorInfo(
                code="tool.cancelled_before_result",
                category=ErrorCategory.UNCERTAIN_SIDE_EFFECT,
                message="tool execution was cancelled before a result was received",
                safe_to_resume=True,
                metadata={
                    "tool_name": call.tool_name,
                    "operation_id": call.operation_id,
                    "tool_result_received": False,
                },
            ),
            context,
            turn_id,
            step_id,
        )

    async def _capture_tool_execution(
        self, run, call, context, turn_id, step_id=None, state=None
    ) -> tuple[RunSnapshot, ToolExecutionResult | None]:
        try:
            run, result = await self._execute_tool_with_control(run, call, context)
            if result is None:
                # The owner releases run resources after all siblings drain.
                return run, None
        except asyncio.CancelledError:
            # The durable started barrier is sufficient for crash recovery.
            # The batch owner drains every sibling before releasing resources.
            raise
        except SageV2Error as exc:
            self._log_tool_exception(exc, run, call, turn_id, step_id)
            localized = localize_error(exc.info, context.language)
            result = ToolExecutionResult(
                tool_call_id=call.tool_call_id,
                operation_id=call.operation_id,
                content=(TextBlock(text=error_diagnostic_message(localized)),),
                error=localized,
            )
        except Exception as exc:
            self._log_tool_exception(exc, run, call, turn_id, step_id)
            localized = localize_error(
                RuntimeErrorInfo(
                    code="tool.provider_error",
                    category=ErrorCategory.PROVIDER_PERMANENT,
                    message=exception_diagnostic_message(exc),
                    safe_to_resume=True,
                ),
                context.language,
            )
            result = ToolExecutionResult(
                tool_call_id=call.tool_call_id,
                operation_id=call.operation_id,
                content=(TextBlock(text=error_diagnostic_message(localized)),),
                error=localized,
            )
        return run, result

    async def dispatch_tool_call(
        self, run, call, context, turn_id, step_id=None, state=None
    ) -> tuple[RunSnapshot, ToolExecutionResult | None]:
        """Cross the tool side-effect barrier and settle or reconcile its result.

        `dispatching` is committed before calling the provider. Once control
        crosses into ToolExecutor, a transport failure may mean the operation
        succeeded remotely; such failures become UNKNOWN, never an automatic
        retry.
        """

        previous = await self._crossed_tool_calls(run, step_id)
        if call.tool_call_id in previous:
            # Reuse the original operation identity, including after process loss.
            call = previous[call.tool_call_id]
            receipt = await self._tool_execution_receipt(run, call)
            if receipt is None:
                uncertainty = RuntimeErrorInfo(
                    code="tool.outcome_unknown_after_worker_restart",
                    category=ErrorCategory.UNCERTAIN_SIDE_EFFECT,
                    message="Tool dispatch was recorded without a result; reconcile before continuing",
                    safe_to_resume=True,
                )
                run = await self._record_tool_unknown(
                    run, call, uncertainty, context, turn_id, step_id
                )
                return await self._reconcile_or_suspend_tool(
                    run, call, context, turn_id, step_id, state, uncertainty
                )
            result = receipt
        else:
            run = await self._start_tool_execution(run, call, context, turn_id, step_id)
            try:
                run, result = await self._capture_tool_execution(
                    run, call, context, turn_id, step_id
                )
            except asyncio.CancelledError:
                current = await self.runtime.get_run(run.run_id)
                if current.state in TERMINAL_RUN_STATES:
                    await self._release_run_resources(run.run_id)
                elif current.state in {RunState.RUNNING, RunState.SUSPEND_REQUESTED}:
                    await asyncio.shield(
                        self._record_cancelled_execution(
                            current, call, context, turn_id, step_id
                        )
                    )
                raise
            if result is None:
                await self._release_run_resources(run.run_id)
                return run, None
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
            if self._unsafe_tool_runtime_error(localized):
                # An unsafe runtime/storage failure must never become ordinary
                # model feedback or be reclassified as a retryable Tool effect.
                result = result.model_copy(update={"error": localized})
                return await self._stop_for_unsafe_tool_error(
                    run, call, result, context, turn_id, step_id, state
                )
            # Content belongs to the Tool, including structured failure output.
            # Localization only owns the host/UI summary. The receipt marker
            # controls side-effect certainty, not whether content is retained.
            result = result.model_copy(update={"error": localized})
        self._apply_tool_expansion(call, result)
        if state is not None and result.metadata.get("delegation_deferred_until"):
            return await self._defer_delegation(run, state, result, context, step_id), None
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
            await self._release_run_resources(run.run_id)
            return current, None
        run = current
        if run.state == RunState.SUSPEND_REQUESTED:
            run, result = await self._commit_tool_result(
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
            run, followups = await self._persist_followup_user_messages(
                run, (result,), context, turn_id, step_id
            )
            paused_state = state.model_copy(
                update={
                    "messages": (
                        *state.messages,
                        self._tool_result_message(result),
                        *followups,
                    ),
                    "pending_tool_call": None,
                    "pending_tool_policy": None,
                    "pending_tool_phase": None,
                    "pending_tool_step_id": None,
                    "pending_tool_error": None,
                    "pending_tool_result": None,
                    "pending_child_interactions": (),
                    "pending_questionnaire_completed": (
                        state.pending_questionnaire_completed
                        or self._validated_questionnaire_result(call, result)
                    ),
                }
            )
            return await self._suspend_at_safe_point(run, paused_state, context), None
        run, result = await self._commit_tool_result(
            run, call, result, context, turn_id, step_id=step_id
        )
        return run, result

    async def _stop_for_unsafe_tool_error(
        self, run, call, result, context, turn_id, step_id, state
    ) -> tuple[RunSnapshot, ToolExecutionResult | None]:
        current = await self.runtime.get_run(run.run_id)
        if current.state in TERMINAL_RUN_STATES:
            await self._release_run_resources(run.run_id)
            return current, None
        run, _ = await self._commit_tool_result(
            current,
            call,
            result,
            context,
            turn_id,
            step_id=step_id,
            expected_states={RunState.RUNNING, RunState.SUSPEND_REQUESTED},
        )
        if state is None:
            raise SageV2Error(result.error)
        return await self._fail(
            run, state, step_id, result.error, context, allow_recovery=False
        ), None

    @staticmethod
    def _unsafe_tool_runtime_error(error: RuntimeErrorInfo) -> bool:
        """Only unrecoverable framework failures terminate a tool-owning Run."""
        return not error.safe_to_resume and error.category in {
            ErrorCategory.INTERNAL,
            ErrorCategory.CORRUPT_STATE,
            ErrorCategory.UNSUPPORTED_SCHEMA,
            ErrorCategory.CONFLICT,
            ErrorCategory.RESOURCE_LOST,
        }

    async def _tool_failure_is_uncertain(self, run, call, error) -> bool:
        """Classify post-dispatch failures without assuming a write was rolled back."""

        # A protocol-level tool error is an authoritative response, not a lost
        # response. The remote side confirmed that the operation failed, so a
        # write must not be escalated to an unknown-side-effect suspension.
        if error.metadata.get("tool_result_received") is True:
            return False
        # A local supervisor confirms the process was reaped. Its partial files
        # remain inspectable; report the interruption instead of replaying it or
        # suspending the entire Agent for an unknown execution outcome.
        if (error.category == ErrorCategory.RESOURCE_LOST
                and error.metadata.get("process_settled") is True):
            return False
        if error.category == ErrorCategory.UNCERTAIN_SIDE_EFFECT:
            return True
        if self._unsafe_tool_runtime_error(error):
            return False
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

    async def _resume_delegated_tool(self, run, state, decision, payload, context) -> tuple[RunSnapshot, ToolExecutionResult | None]:
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
        run, tool_result = await self._commit_tool_result(
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
    ) -> RunSnapshot:
        raw = pending.get("interaction") if isinstance(pending, dict) else None
        child = InteractionRequest.model_validate(raw)
        interaction_id = new_id("interaction")
        checkpoint, suspension = await self._checkpoint_records(
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

    async def _record_tool_unknown(self, run, call, error, context, turn_id, step_id) -> RunSnapshot:
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
            expected_states={RunState.RUNNING, RunState.SUSPEND_REQUESTED},
        )

    async def _reconcile_or_suspend_tool(
        self, run, call, context, turn_id, step_id, state, uncertainty
    ) -> tuple[RunSnapshot, ToolExecutionResult | None]:
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
                    await cast(Callable[..., Awaitable[ReconcileResult]], reconcile_call)(call, context)
                    if callable(reconcile_call)
                    else await self.tool_executor.reconcile(call.operation_id, context)
                )
            except Exception as exc:
                if isinstance(exc, SageV2Error) and self._unsafe_tool_runtime_error(
                    exc.info
                ):
                    return await self._stop_for_unsafe_tool_error(
                        run,
                        call,
                        ToolExecutionResult(
                            tool_call_id=call.tool_call_id,
                            operation_id=call.operation_id,
                            error=exc.info,
                        ),
                        context,
                        turn_id,
                        step_id,
                        state,
                    )
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
            fatal_error = (
                reconciled.result.error
                if reconciled.result and reconciled.result.error
                else reconciled.error
            )
            if fatal_error is not None and self._unsafe_tool_runtime_error(fatal_error):
                return await self._stop_for_unsafe_tool_error(
                    run,
                    call,
                    ToolExecutionResult(
                        tool_call_id=call.tool_call_id,
                        operation_id=call.operation_id,
                        error=fatal_error,
                    ),
                    context,
                    turn_id,
                    step_id,
                    state,
                )
            if reconciled.state == ReconcileState.SUCCEEDED and reconciled.result:
                if state is not None and reconciled.result.metadata.get("delegation_deferred_until"):
                    return await self._defer_delegation(
                        await self.runtime.get_run(run.run_id), state, reconciled.result, context, step_id
                    ), None
                pending = reconciled.result.metadata.get("delegation_interactions")
                if state is not None and isinstance(pending, list) and pending:
                    pending_state = state.model_copy(
                        update={
                            "pending_tool_call": call,
                            "pending_tool_phase": "delegation_interaction",
                            "pending_tool_step_id": step_id,
                            "pending_tool_result": reconciled.result.model_dump(
                                mode="json"
                            ),
                            "pending_child_interactions": tuple(pending),
                        }
                    )
                    return (
                        await self._suspend_for_delegated_interaction(
                            await self.runtime.get_run(run.run_id),
                            pending_state,
                            call,
                            pending[0],
                            context,
                            step_id,
                        ),
                        None,
                    )
                run, result = await self._commit_tool_result(
                    await self.runtime.get_run(run.run_id),
                    call,
                    reconciled.result,
                    context,
                    turn_id,
                    step_id=step_id,
                    event_type_override="tool.call.reconciled",
                )
                return run, result
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
                run, result = await self._commit_tool_result(
                    run,
                    call,
                    result,
                    context,
                    turn_id,
                    step_id=step_id,
                    event_type_override="tool.call.reconciled",
                )
                return run, result
        if definition.resume_strategy == ResumeStrategy.AGENT_RECOVERY:
            # A missing response is a failed invocation, not evidence that the
            # remote operation failed. Preserve that distinction in the durable
            # result and model-visible text; never replay the write here.
            guidance = (
                "Tool invocation failed; the remote execution outcome is unknown. "
                "Continue recovery autonomously. Before retrying this operation, "
                "use available status/query tools or inspect existing outputs to "
                "determine whether it already completed. Reuse completed outputs; "
                "wait for pending work. Retry only after confirming it did not "
                "apply, or that repetition is safe/idempotent. If status cannot be "
                "determined, use another safe recovery approach; do not blindly "
                "repeat a write or claim success. A transport error alone does "
                "not require user confirmation."
            )
            error = uncertainty.model_copy(update={
                "safe_to_resume": True,
                "retryable": False,
                "metadata": {
                    **uncertainty.metadata,
                    "execution_outcome": "unknown",
                    "recovery_action": "check_status_before_retry",
                    "tool_name": call.tool_name,
                    "operation_id": call.operation_id,
                    "idempotency_key": call.idempotency_key,
                    "arguments": call.arguments,
                },
            })
            result = ToolExecutionResult(
                tool_call_id=call.tool_call_id,
                operation_id=call.operation_id,
                error=error,
                content=(TextBlock(text=(
                    f"{error_diagnostic_message(error)}\n\n{guidance}\n"
                    "Recovery context: " + json.dumps(error.metadata, ensure_ascii=False, default=str)
                )),),
                metadata={"execution_outcome": "unknown", "recovery_action": "check_status_before_retry"},
            )
            return await self._commit_tool_result(
                await self.runtime.get_run(run.run_id), call, result, context,
                turn_id, step_id=step_id,
            )
        if state is None:
            raise SageV2Error(uncertainty)
        return (
            await self._suspend_for_tool_uncertainty(
                run, state, call, uncertainty, context, step_id, definition
            ),
            None,
        )

    async def _defer_delegation(self, run, state, result, context, step_id) -> RunSnapshot:
        from datetime import datetime

        due = datetime.fromisoformat(result.metadata["delegation_deferred_until"])
        state = state.model_copy(update={
            "automatic_resume_at": due, "automatic_resume_reason": "delegation.wait",
        })
        return await self._commit_running(
            run, context, (EventDraft(
                type="step.retry_scheduled", turn_id=state.turn_id, step_id=step_id,
                data=StepEventData(state="delegation_wait", retry_at=due),
            ),), recovery_state=state,
        )

    async def _resume_uncertain_tool(self, run, state, decision, payload, context) -> tuple[RunSnapshot, ToolExecutionResult | None]:
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
            run, result = await self._commit_tool_result(
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
        run, result = await self._commit_tool_result(
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
    ) -> tuple[RunSnapshot, ToolExecutionResult]:
        """Commit and return the same normalized result used by the model ledger."""

        if result.error is not None:
            localized = localize_error(result.error, context.language)
            content = result.content
            if not content:
                content = (TextBlock(text=error_diagnostic_message(localized)),)
            elif (
                result.metadata.get("tool_result_received") is not True
                and isinstance(content[0], TextBlock)
                and content[0].text == result.error.message
            ):
                # Recover details from generated summaries (also on resume),
                # preserving additional provider/user feedback blocks.
                content = (
                    content[0].model_copy(
                        update={"text": error_diagnostic_message(localized)}
                    ),
                    *content[1:],
                )
            result = result.model_copy(
                update={
                    "error": localized,
                    "content": content,
                }
            )

        if self.tool_result_processor is not None:
            result = await self.tool_result_processor.process(
                result, call=call, context=context, runtime=self.tool_result_runtime,
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
                metadata={
                    key: value
                    for key, value in result.metadata.items()
                    if key != "followup_user_message"
                },
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
        run = await self._commit_running(
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
                *self._followup_user_message_drafts(run, (result,), turn_id, step_id),
            ),
            expected_states=expected_states,
        )
        return run, result

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
    ) -> RunSnapshot:
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
        checkpoint, suspension = await self._checkpoint_records(
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

    async def _suspend_for_tool_approval(self, run, state, policy, context, step_id) -> RunSnapshot:
        """Checkpoint before dispatch so approval cannot race the side effect."""

        interaction_id = new_id("interaction")
        checkpoint, suspension = await self._checkpoint_records(
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
    ) -> RunSnapshot:
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
        checkpoint, suspension = await self._checkpoint_records(
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

    async def _suspend_at_safe_point(self, run, state, context) -> RunSnapshot:
        return await self.commit_safe_point_suspension(run, state, context)

    async def commit_safe_point_suspension(self, run, state, context) -> RunSnapshot:
        """Commit a manual-pause checkpoint between externally visible actions."""

        checkpoint, suspension = await self._checkpoint_records(
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

    async def _checkpoint_records(self, run, state, *, reason, interaction_id=None) -> tuple[Checkpoint, Suspension]:
        """Build matching Checkpoint/Suspension records for one atomic commit."""

        if self.preload_skills and self.skill_loader is not None:
            state = state.model_copy(
                update={
                    "skill_state": await self.skill_loader.snapshot_run(run.run_id),
                }
            )
        checkpoint_id = new_id("checkpoint")
        checkpoint_state = AgentLoopCheckpointCodec.encode(
            state.model_copy(update={"execution_checkpoint": False}),
            ledger_digest=self._ledger_digest(state.messages),
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

    async def _record_continuation(self, run, decision, context, turn_id, step_id) -> RunSnapshot:
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
        # Keep UI/Tool localization separate from the bilingual prompt policy.
        language = normalize_language(
            str(command.config.metadata.get("response_language") or "en")
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
    ) -> RunSnapshot:
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

    async def _complete(self, run, state, step_id, context) -> RunSnapshot:
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

    async def _fail(self, run, state, step_id, error, context, *, allow_recovery=True) -> RunSnapshot:
        require_execution_ownership()
        if is_lease_loss(error):
            raise SageV2Error(error)
        error = localize_error(error, context.language)
        current = await self.runtime.get_run(run.run_id)
        if current.state in TERMINAL_RUN_STATES:
            await self._release_run_resources(run.run_id)
            return current
        resumable = allow_recovery and (error.safe_to_resume or error.retryable)
        if error.metadata.get("budget_scope") == "run_tree":
            from sagents.v2.runtime.execution.budgets import stop_budget_descendants
            await stop_budget_descendants(self.runtime, current, context)
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

        self._prepared_tool_selection_runs.discard(run_id)
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
        self, run, context, drafts, *, expected_states=None, recovery_state=None
    ) -> RunSnapshot:
        snapshot = None
        if self.preload_skills and self.skill_loader is not None:
            from sagents.v2.contracts.events import SkillStateEventData

            snapshot = await self.skill_loader.snapshot_run(run.run_id)
            if snapshot != self._last_skill_states.get(run.run_id):
                drafts = (
                    *drafts,
                    EventDraft(
                        type="skill.state", data=SkillStateEventData(state=snapshot)
                    ),
                )
        checkpoint = None
        if recovery_state is not None:
            if snapshot is not None:
                recovery_state = recovery_state.model_copy(
                    update={"skill_state": snapshot}
                )
            checkpoint = Checkpoint(
                checkpoint_id=new_id("checkpoint"),
                checkpoint_codec_version=AgentLoopCheckpointCodec.version,
                session_id=run.session_id,
                run_id=run.run_id,
                run_sequence=run.last_run_sequence + len(drafts) + 1,
                session_revision=run.accepted_session_revision,
                state=AgentLoopCheckpointCodec.encode(
                    recovery_state.model_copy(update={"execution_checkpoint": True}),
                    ledger_digest=self._ledger_digest(recovery_state.messages),
                ),
                resolved_spec_hash=run.resolved_spec_hash,
                created_at=self.clock(),
            )
            drafts = (
                *drafts,
                EventDraft(
                    type="checkpoint.committed",
                    turn_id=recovery_state.turn_id,
                    data=CheckpointEventData(
                        checkpoint_id=checkpoint.checkpoint_id,
                        checkpoint_codec_version=checkpoint.checkpoint_codec_version,
                        run_sequence=checkpoint.run_sequence,
                        session_revision=checkpoint.session_revision,
                    ),
                ),
            )
        committed = await self.lifecycle.commit(
            run,
            expected_states=expected_states or {RunState.RUNNING},
            new_state=run.state,
            drafts=drafts,
            context=context,
            idempotency_key=new_id("loop_commit"),
            checkpoint=checkpoint,
        )
        if snapshot is not None:
            self._last_skill_states[run.run_id] = snapshot
        return committed

    def _item(
        self, item_id, run_id, turn_id, step_id, data, status=ItemStatus.COMPLETED
    ) -> ItemSnapshot:
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
        self,
        run_id,
        turn_id,
        step_id,
        item_id,
        content,
        *,
        reasoning,
        status=ItemStatus.SUSPENDED,
    ) -> EventDraft:
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
            status=status,
        )
        return EventDraft(
            type="item.completed",
            turn_id=turn_id,
            step_id=step_id,
            item_id=item_id,
            data=ItemEventData(operation="completed", item=item),
        )

    async def _persist_followup_user_messages(
        self, run, results, context, turn_id, step_id
    ) -> tuple[RunSnapshot, tuple[ModelMessage, ...]]:
        messages = tuple(
            message
            for result in results
            for message in self._followup_user_messages(result)
        )
        if not messages:
            return run, ()
        existing = {
            event.item_id
            for event in await self.runtime.session_store.read_events(run.run_id)
        }
        drafts = tuple(
            draft
            for draft in self._followup_user_message_drafts(
                run, results, turn_id, step_id
            )
            if draft.item_id not in existing
        )
        if drafts:
            run = await self._commit_running(
                run, context, drafts, expected_states={run.state}
            )
        return run, messages

    def _followup_user_message_drafts(self, run, results, turn_id, step_id) -> tuple[EventDraft, ...]:
        """Bind supplemental model context atomically to its tool result.

        Deterministic Item identities also make legacy deferred publication
        idempotent when recovery encounters an already-persisted follow-up.
        """
        drafts = []
        for result in results:
            for index, message in enumerate(self._followup_user_messages(result)):
                key = f"{run.run_id}:{result.operation_id}:{index}"
                item_id = "item_followup_" + hashlib.sha256(key.encode()).hexdigest()
                item = self._item(
                    item_id,
                    run.run_id,
                    turn_id,
                    step_id,
                    MessageItemData(
                        role="user",
                        content=message.content,
                        metadata=message.metadata,
                    ),
                )
                drafts.append(
                    EventDraft(
                        type="message.completed",
                        turn_id=turn_id,
                        step_id=step_id,
                        item_id=item_id,
                        data=ItemEventData(operation="completed", item=item),
                    )
                )
        return tuple(drafts)

    @classmethod
    def _ledger_messages_for_tool_result(cls, result) -> tuple[ModelMessage, ...]:
        return cls._ledger_messages_for_tool_batch((result,))

    @classmethod
    def _ledger_messages_for_tool_batch(cls, results) -> tuple[ModelMessage, ...]:
        return (
            *(cls._tool_result_message(result) for result in results),
            *(
                message
                for result in results
                for message in cls._followup_user_messages(result)
            ),
        )

    @staticmethod
    def _tool_result_message(result) -> ModelMessage:
        content = result.content
        if not content and result.error is not None:
            content = (TextBlock(text=error_diagnostic_message(result.error)),)
        metadata = dict(result.metadata)
        metadata.pop("followup_user_message", None)
        return ModelMessage(
            role="tool",
            tool_call_id=result.tool_call_id,
            content=content,
            metadata=metadata,
        )

    @staticmethod
    def _followup_user_messages(result) -> tuple[ModelMessage, ...]:
        raw = result.metadata.get("followup_user_message")
        if not isinstance(raw, dict):
            return ()
        blocks = []
        for block in raw.get("content") or ():
            if not isinstance(block, dict):
                continue
            kind = block.get("kind")
            if kind == "text":
                blocks.append(TextBlock(text=str(block.get("text") or "")))
            elif kind == "image":
                uri = block.get("uri")
                if not uri:
                    continue
                blocks.append(
                    ImageBlock(
                        uri=str(uri),
                        mime_type=str(block.get("mime_type") or "image/jpeg"),
                        alt=block.get("alt"),
                    )
                )
        if not blocks:
            return ()
        metadata = raw.get("metadata")
        return (
            ModelMessage(
                role="user",
                content=tuple(blocks),
                metadata=metadata if isinstance(metadata, dict) else {},
            ),
        )

    @staticmethod
    def _response_fingerprint(response) -> str:
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
    def _trailing_repeat_count(values) -> int:
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
    def _conflict(code, message) -> SageV2Error:
        return SageV2Error(
            RuntimeErrorInfo(
                code=code,
                category=ErrorCategory.CONFLICT,
                message=message,
                safe_to_resume=True,
            )
        )

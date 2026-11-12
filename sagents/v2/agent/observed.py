"""Observability adapter around the pure Agent Loop RunDriver."""

from __future__ import annotations

from typing import Any, cast
from sagents.v2.contracts.common import utc_now

from sagents.v2.agent.engine import AgentLoopEngine
from sagents.v2.agent.step_request import DefaultAgentStepRequestBuilder
from sagents.v2.runtime.observability.performance.recording import PerformanceRecorder, RunTimingStage
from sagents.v2.runtime.observability.run_output import capture_run_trace_output
from sagents.v2.runtime.observability.timing import log_duration
from sagents.v2.runtime.observability.content import trace_content
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.commands import StartRun
from sagents.v2.contracts.principals import RequestContext
from sagents.v2.contracts.run_state import RunSnapshot, RunState
from sagents.v2.runtime.observability.contracts import (
    LogSink,
    TraceKind,
    TraceSink,
    TraceStatus,
)
from sagents.v2.runtime.observability.logs import (
    StructuredLogger,
    structured_log_context,
)
from sagents.v2.runtime.observability.traces import (
    StructuredTracer,
    resolve_root_session_id,
    new_trace_id,
    current_trace_context,
)


def _run_outcome_observation(
    state: RunState,
) -> tuple[TraceStatus, str, str, str]:
    if state == RunState.COMPLETED:
        return TraceStatus.OK, "agent.run.completed", "agent run completed", "info"
    if state == RunState.FAILED:
        return TraceStatus.ERROR, "agent.run.failed", "agent run failed", "error"
    if state == RunState.CANCELLED:
        return (
            TraceStatus.UNSET,
            "agent.run.cancelled",
            "agent run cancelled",
            "warning",
        )
    if state == RunState.SUSPENDED:
        return TraceStatus.UNSET, "agent.run.suspended", "agent run suspended", "info"
    if state == RunState.RUNNING:
        return TraceStatus.UNSET, "agent.run.deferred", "agent run scheduled to continue", "info"
    return TraceStatus.UNSET, "agent.run.stopped", "agent run stopped", "warning"


class _ObservedContextAssembler:
    def __init__(self, assembler, logger):
        self.assembler, self.logger = assembler, logger

    def __getattr__(self, name: str) -> Any:
        return getattr(self.assembler, name)

    async def prepare_projection(self, command, ledger, **kwargs):
        return await self.assembler.prepare_projection(command, ledger, **kwargs)

    async def initial_ledger(self, command, *, run_id=None):
        with log_duration(self.logger, "agent.preparation.completed", "会话历史加载结束",
                          run_id=run_id, attributes={"phase": "history"}):
            return await self.assembler.initial_ledger(command, run_id=run_id)

    async def prepare_messages(self, command, ledger, **kwargs):
        with log_duration(self.logger, "agent.preparation.completed", "模型上下文构建结束",
                          run_id=kwargs.get("run_id"), attributes={"phase": "context_projection"}):
            return await self.assembler.prepare_messages(command, ledger, **kwargs)


class _ObservedStepRequestBuilder:
    def __init__(self, builder, logger):
        self.builder, self.logger = builder, logger

    def __getattr__(self, name: str) -> Any:
        return getattr(self.builder, name)

    async def prepare(self, **kwargs):
        with log_duration(self.logger, "agent.preparation.completed", "模型请求准备结束",
                          run_id=kwargs["run_id"], turn_id=kwargs["turn_id"], step_id=kwargs["step_id"],
                          attributes={"phase": "model_request"}):
            return await self.builder.prepare(**kwargs)


class ObservedRunDriver(AgentLoopEngine):
    """Project Agent Run and logical Tool-call lifecycles to host-owned sinks."""

    def __init__(
        self,
        *,
        trace_sink: TraceSink | None = None,
        log_sink: LogSink | None = None,
        performance: PerformanceRecorder | None = None,
        **engine_dependencies: Any,
    ) -> None:
        super().__init__(**engine_dependencies)
        self._observed_trace_sink = trace_sink
        self._observed_log_sink = log_sink
        self._performance = performance
        if log_sink is not None:
            self.context_assembler = _ObservedContextAssembler(
                self.context_assembler, self._structured_logger()
            )
            builder = self.step_request_builder
            if isinstance(builder, DefaultAgentStepRequestBuilder):
                cast(DefaultAgentStepRequestBuilder, builder).context_assembler = self.context_assembler
            self.step_request_builder = _ObservedStepRequestBuilder(
                builder, self._structured_logger()
            )

    def _structured_logger(self) -> StructuredLogger | None:
        if self._observed_log_sink is None:
            return None
        return StructuredLogger(self._observed_log_sink, "sagents.agent")

    def _record_stage(self, run, event, segment, **fields):
        if self._performance is not None and self._performance.sink is not None:
            self._performance.record_stage(RunTimingStage(
                run.session_id, run.run_id, event, segment, utc_now(), **fields,
            ))

    async def _prepare_self_configuration(self, run_id, context):
        if self.self_configuration is None:
            return await super()._prepare_self_configuration(run_id, context)
        with log_duration(self._structured_logger(), "agent.preparation.completed", "Agent 自配置准备结束",
                          run_id=run_id, attributes={"phase": "self_configuration"}):
            return await super()._prepare_self_configuration(run_id, context)

    async def _initialize_skills(self, run, command, context):
        if not self.preload_skills:
            return await super()._initialize_skills(run, command, context)
        with log_duration(self._structured_logger(), "agent.preparation.completed", "技能预加载结束",
                          run_id=run.run_id, session_id=run.session_id, attributes={"phase": "skill_preloads"}):
            return await super()._initialize_skills(run, command, context)

    async def _prepare_tool_selection(self, *, command, run_id, messages, language):
        if run_id in self._prepared_tool_selection_runs:
            return
        with log_duration(self._structured_logger(), "agent.preparation.completed", "工具目录与选择策略准备结束",
                          run_id=run_id, attributes={"phase": "tool_selection"}):
            return await super()._prepare_tool_selection(
                command=command, run_id=run_id, messages=messages, language=language
            )

    async def _commit_running(self, run, context, drafts, **kwargs):
        with log_duration(self._structured_logger(), "agent.state.commit", "Agent 状态提交结束",
                          run_id=run.run_id, session_id=run.session_id,
                          attributes={"event_types": [draft.type for draft in drafts], "revision": run.revision}):
            return await super()._commit_running(run, context, drafts, **kwargs)

    async def _root_session_id(self, session_id: str) -> str:
        return await resolve_root_session_id(
            self.runtime.session_store.get_session, session_id
        )

    @staticmethod
    def _user_input_preview(command: StartRun) -> str:
        latest = next(
            (
                item
                for item in reversed(command.input)
                if item.role == "user"
            ),
            None,
        )
        if latest is None:
            return ""
        return "\n".join(
            block.text for block in latest.content if isinstance(block, TextBlock)
        ).strip()

    async def execute(self, run_id: str, context: RequestContext) -> RunSnapshot:
        return await self._observe_run(
            run_id, context, resumed=False, body=super().execute
        )

    async def resume(self, run_id: str, context: RequestContext) -> RunSnapshot:
        return await self._observe_run(
            run_id, context, resumed=True, body=super().resume
        )

    async def _observe_run(self, run_id, context, *, resumed, body):
        try:
            run = await self.runtime.get_run(run_id)
            command = await self.runtime.session_store.get_start_command(run_id)
        except Exception:
            return await body(run_id, context)
        try:
            session = await self.runtime.session_store.get_session(run.session_id)
        except Exception:
            session = None
        root_session_id = await self._root_session_id(run.session_id)
        tracer = StructuredTracer(
            self._observed_trace_sink,
            "agent",
            trace_id=context.trace.trace_id or new_trace_id(),
            parent_span_id=(
                context.trace.span_id if current_trace_context() is None else None
            ),
        )
        attributes = {
            "agent_id": getattr(command, "agent_id", None),
            "invocation_mode": getattr(command, "invocation_mode", None) or "normal",
            "resumed": resumed,
            "user_input": trace_content(
                self._observed_trace_sink, self._user_input_preview(command)
            ),
            "input": trace_content(
                self._observed_trace_sink, getattr(command, "input", ())
            ),
            "user_id": context.actor.principal_id,
            "tenant_id": context.actor.tenant_id,
            "root_session_id": root_session_id,
        }
        parent_session_id = getattr(session, "parent_session_id", None)
        if parent_session_id:
            attributes["parent_session_id"] = parent_session_id
        logger = self._structured_logger()
        correlation_id = context.trace.correlation_id
        correlation = (
            {"correlation_id": correlation_id} if correlation_id is not None else {}
        )
        segment = str(run.revision)
        self._record_stage(run, "agent.run.started", segment, agent_id=command.agent_id)
        if logger is not None:
            logger.info(
                "agent.run.started",
                "agent run started",
                session_id=run.session_id,
                run_id=run.run_id,
                **correlation,
                attributes={
                    "agent_id": getattr(command, "agent_id", None),
                    "resumed": resumed,
                    "root_session_id": root_session_id,
                },
            )
        handle = tracer.start_span(
            "agent.run",
            kind=TraceKind.INTERNAL,
            session_id=run.session_id,
            run_id=run.run_id,
            correlation_id=correlation_id,
            attributes=attributes,
        )
        capture_output = (
            self._observed_trace_sink is not None
            and getattr(self._observed_trace_sink, "content_mode", "redacted") != "metadata"
        )
        try:
            with (
                structured_log_context(**correlation, run_id=run.run_id, session_id=run.session_id),
                capture_run_trace_output(run_id, enabled=capture_output) as output,
            ):
                snapshot = await body(
                    run_id,
                    context.model_copy(
                        update={
                            "trace": context.trace.model_copy(
                                update={
                                    "trace_id": handle.span.trace_id,
                                    "span_id": handle.span.span_id,
                                }
                            ),
                        }
                    ),
                )
        except BaseException as exc:
            self._record_stage(run, "agent.run.failed", segment)
            handle.end(TraceStatus.ERROR, error=exc)
            if logger is not None:
                logger.exception(
                    "agent.run.failed",
                    "agent run failed",
                    exc,
                    session_id=run.session_id,
                    run_id=run.run_id,
                    **correlation,
                )
            raise
        status, event, message, log_method = _run_outcome_observation(snapshot.state)
        self._record_stage(run, event, segment, state=snapshot.state.value)
        final_attributes = {"run_state": snapshot.state.value}
        try:
            if output is not None and snapshot.state in {RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED}:
                if output.items:
                    final_attributes["output"] = trace_content(
                        self._observed_trace_sink, tuple(output.items.values()),
                    )
                if output.error is not None:
                    final_attributes["status_message"] = trace_content(
                        self._observed_trace_sink, output.error.message,
                    )
        except Exception:
            pass
        finally:
            handle.end(status, attributes=final_attributes)
        if logger is not None:
            getattr(logger, log_method)(
                event,
                message,
                session_id=run.session_id,
                run_id=run.run_id,
                **correlation,
                attributes={"run_state": snapshot.state.value},
            )
        return snapshot

    def _log_tool_exception(self, exc, run, call, turn_id, step_id):
        # Keep private stacks out of the model-facing result and durable ledger.
        # Explicit scope also works when dispatch runs outside a request context.
        logger = self._structured_logger()
        if logger is None:
            return
        logger.exception(
            "tool.execution.exception",
            "Tool execution raised an exception.",
            exc,
            session_id=run.session_id,
            run_id=run.run_id,
            turn_id=turn_id,
            step_id=step_id,
            tool_call_id=call.tool_call_id,
            attributes={
                "tool_name": call.tool_name,
                "operation_id": call.operation_id,
            },
        )


    async def _capture_tool_execution(
        self, run, call, context, turn_id, step_id=None, state=None
    ):
        return await self._observe_tool_call(
            run,
            call,
            context,
            turn_id,
            step_id=step_id,
            state=state,
            body=super()._capture_tool_execution,
        )

    async def _observe_tool_call(
        self, run, call, context, turn_id, step_id=None, state=None, *, body
    ):
        handle = StructuredTracer(self._observed_trace_sink, "tool").start_span(
            "tool.call",
            kind=TraceKind.CLIENT,
            session_id=run.session_id,
            run_id=run.run_id,
            turn_id=turn_id,
            step_id=step_id,
            tool_call_id=call.tool_call_id,
            attributes={
                "tool_name": call.tool_name,
                "operation_id": call.operation_id,
                "arguments": trace_content(self._observed_trace_sink, call.arguments),
            },
        )
        logger = self._structured_logger()
        timing_scope = {"identity": call.tool_call_id, "turn_id": turn_id}
        self._record_stage(run, "tool.call.started", call.operation_id, **timing_scope)
        if logger is not None:
            logger.info(
                "tool.call.started",
                "tool call started",
                session_id=run.session_id,
                run_id=run.run_id,
                turn_id=turn_id,
                step_id=step_id,
                tool_call_id=call.tool_call_id,
                attributes={"tool_name": call.tool_name},
            )
        try:
            run, result = await body(
                run, call, context, turn_id, step_id=step_id, state=state
            )
        except BaseException as exc:
            self._record_stage(run, "tool.call.failed", call.operation_id, **timing_scope)
            handle.end(TraceStatus.ERROR, error=exc)
            if logger is not None:
                logger.exception(
                    "tool.call.failed",
                    "tool call failed",
                    exc,
                    session_id=run.session_id,
                    run_id=run.run_id,
                    turn_id=turn_id,
                    step_id=step_id,
                    tool_call_id=call.tool_call_id,
                    attributes={"tool_name": call.tool_name},
                )
            raise
        failed = result is not None and result.error is not None
        outcome = "interrupted" if result is None else "failed" if failed else "completed"
        self._record_stage(run, "tool.call." + outcome, call.operation_id, **timing_scope)
        handle.end(
            TraceStatus.ERROR
            if result is None or failed
            else TraceStatus.OK,
            attributes={
                "execution_result": trace_content(
                    self._observed_trace_sink,
                    result.model_dump(mode="json") if result is not None else None,
                ),
                "error": trace_content(
                    self._observed_trace_sink,
                    result.error.model_dump(mode="json") if result is not None and result.error is not None else None,
                ),
                "status_message": trace_content(self._observed_trace_sink, str(result.error))
                if result is not None and result.error is not None
                else None,
                "outcome": outcome,
            },
        )
        if logger is not None:
            fields = {
                "session_id": run.session_id,
                "run_id": run.run_id,
                "turn_id": turn_id,
                "step_id": step_id,
                "tool_call_id": call.tool_call_id,
                "attributes": {
                    "tool_name": call.tool_name,
                    **(
                        {"error_code": result.error.code}
                        if failed and result.error is not None
                        else {}
                    ),
                },
            }
            if result is None:
                logger.warning("tool.call.interrupted", "tool call stopped without a returned result", **fields)
            elif failed:
                logger.error("tool.call.failed", "tool call failed", **fields)
            else:
                logger.info("tool.call.completed", "tool call completed", **fields)
        return run, result


__all__ = ["ObservedRunDriver"]

"""Observability adapter around the pure Agent Loop RunDriver."""

from __future__ import annotations

from typing import Any

from sagents.v2.agent.engine import AgentLoopEngine
from sagents.v2.contracts.items import TextBlock
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
    preview_trace_value,
    resolve_root_session_id,
    session_trace_id,
)


class ObservedRunDriver(AgentLoopEngine):
    """Project Agent Run and logical Tool-call lifecycles to host-owned sinks."""

    def __init__(
        self,
        *,
        trace_sink: TraceSink | None = None,
        log_sink: LogSink | None = None,
        **engine_dependencies: Any,
    ) -> None:
        super().__init__(**engine_dependencies)
        self._observed_trace_sink = trace_sink
        self._observed_log_sink = log_sink

    def _structured_logger(self) -> StructuredLogger | None:
        if self._observed_log_sink is None:
            return None
        return StructuredLogger(self._observed_log_sink, "sagents.agent")

    async def _root_session_id(self, session_id: str) -> str:
        return await resolve_root_session_id(
            self.runtime.session_store.get_session, session_id
        )

    @staticmethod
    def _user_input_preview(command) -> str:
        latest = next(
            (
                item
                for item in reversed(getattr(command, "input", ()) or ())
                if getattr(item, "role", None) == "user"
            ),
            None,
        )
        if latest is None:
            return ""
        return "\n".join(
            block.text for block in latest.content if isinstance(block, TextBlock)
        ).strip()

    @staticmethod
    def _tool_result_preview(result) -> str:
        if result is None:
            return ""
        return "\n".join(
            block.text
            for block in getattr(result, "content", ()) or ()
            if isinstance(block, TextBlock)
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
            trace_id=session_trace_id(root_session_id),
        )
        attributes = {
            "agent_id": getattr(command, "agent_id", None),
            "invocation_mode": getattr(command, "invocation_mode", None) or "normal",
            "resumed": resumed,
            "user_input": preview_trace_value(self._user_input_preview(command)),
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
            attributes=attributes,
        )
        try:
            with structured_log_context(**correlation):
                snapshot = await body(run_id, context)
        except BaseException as exc:
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
        failed = snapshot.state == RunState.FAILED
        handle.end(
            TraceStatus.ERROR if failed else TraceStatus.OK,
            attributes={"run_state": snapshot.state.value},
        )
        if logger is not None:
            write = logger.error if failed else logger.info
            write(
                "agent.run.failed" if failed else "agent.run.completed",
                "agent run failed" if failed else "agent run completed",
                session_id=run.session_id,
                run_id=run.run_id,
                **correlation,
                attributes={"run_state": snapshot.state.value},
            )
        return snapshot

    async def _dispatch_tool(
        self, run, call, context, turn_id, step_id=None, state=None
    ):
        return await self._observe_tool_call(
            run,
            call,
            context,
            turn_id,
            step_id=step_id,
            state=state,
            body=super()._dispatch_tool,
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
                "arguments": preview_trace_value(call.arguments),
            },
        )
        logger = self._structured_logger()
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
        handle.end(
            TraceStatus.ERROR
            if getattr(result, "error", None) is not None
            else TraceStatus.OK,
            attributes={
                "result": preview_trace_value(self._tool_result_preview(result))
            },
        )
        failed = getattr(result, "error", None) is not None
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
            if failed:
                logger.error("tool.call.failed", "tool call failed", **fields)
            else:
                logger.info("tool.call.completed", "tool call completed", **fields)
        return run, result


__all__ = ["ObservedRunDriver"]

"""Unsafe Tool failures stop the Run after draining its parallel tool batch."""

import pytest

from sagents.v2.agent.policy.tool_policy import ApprovalStrategy, DefaultToolPolicy
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.run_state import RunState
from sagents.v2.testing.plugins.scripted_model import (
    ScriptedModelProvider,
    ScriptedModelStep,
)
from sagents.v2.tool.contracts import (
    ReconcileResult,
    ReconcileState,
    SideEffectLevel,
    ToolExecutionResult,
)
from tests.sagents.v2.test_agent_loop_matrix import (
    CONTEXT,
    READ_TOOL,
    completed,
    setup_loop,
    tool_call,
)


@pytest.mark.parametrize("raised", [True, False])
@pytest.mark.parametrize("retryable", [True, False])
@pytest.mark.parametrize("side_effect", [SideEffectLevel.READ, SideEffectLevel.WRITE])
async def test_unsafe_tool_error_stops_the_run(raised, retryable, side_effect):
    executed = []
    error = RuntimeErrorInfo(
        code="session_store.aggregate_corrupt",
        category=ErrorCategory.CORRUPT_STATE,
        message="untrusted session state",
        safe_to_resume=False,
        retryable=retryable,
    )

    async def handler(call, context):
        executed.append(call.tool_call_id)
        if raised:
            raise SageV2Error(error)
        return ToolExecutionResult(
            tool_call_id=call.tool_call_id, operation_id=call.operation_id, error=error
        )

    model = ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(
                    completed(
                        calls=(
                            tool_call().model_copy(update={"tool_call_id": "fatal"}),
                            tool_call().model_copy(
                                update={"tool_call_id": "parallel-sibling"}
                            ),
                        )
                    ),
                )
            ),
            ScriptedModelStep(
                events=(completed("must not request another model turn"),)
            ),
        )
    )
    runtime, handle, loop, _ = await setup_loop(
        model,
        tools=(READ_TOOL.model_copy(update={"side_effect_level": side_effect}),),
        handlers={"read_value": handler},
        tool_policy=DefaultToolPolicy(approval_strategy=ApprovalStrategy.AUTO_APPROVE),
    )
    result = await loop.execute(handle.run_id, CONTEXT)
    assert result.state == RunState.FAILED
    # Both siblings were authorized and dispatched before either result arrived.
    assert executed == ["fatal", "parallel-sibling"]
    assert len(model.requests) == 1
    events = await runtime.session_store.read_events(handle.run_id)
    assert any(e.type == "tool.call.failed" for e in events)
    failure = next(e for e in events if e.type == "run.failed")
    assert failure.data.error.code == error.code
    assert failure.data.error.safe_to_resume is False
    assert not any(e.type in {"run.suspended", "tool.call.unknown"} for e in events)


@pytest.mark.parametrize("failure", ["raised", "failed", "unknown", "result"])
async def test_unsafe_reconciliation_error_cannot_be_downgraded_to_retry(failure):
    error = RuntimeErrorInfo(
        code="session_store.aggregate_corrupt",
        category=ErrorCategory.CORRUPT_STATE,
        message="untrusted session state",
        safe_to_resume=False,
        retryable=True,
    )
    model = ScriptedModelProvider(
        (
            ScriptedModelStep(events=(completed(calls=(tool_call(),)),)),
            ScriptedModelStep(events=(completed("must not continue"),)),
        )
    )
    runtime, handle, loop, _ = await setup_loop(
        model,
        tools=(READ_TOOL.model_copy(update={"supports_reconciliation": True}),),
    )

    class Executor:
        async def execute(self, call, context):
            self.call = call
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="tool.response_lost",
                    category=ErrorCategory.UNCERTAIN_SIDE_EFFECT,
                    message="response lost",
                    safe_to_resume=True,
                )
            )

        async def reconcile(self, operation_id, context):
            if failure == "raised":
                raise SageV2Error(error)
            result = (
                ToolExecutionResult(
                    tool_call_id=self.call.tool_call_id,
                    operation_id=operation_id,
                    error=error,
                )
                if failure == "result"
                else None
            )
            return ReconcileResult(
                operation_id=operation_id,
                state=ReconcileState.UNKNOWN
                if failure == "unknown"
                else ReconcileState.FAILED,
                error=None if result else error,
                result=result,
            )

    loop.tool_executor = Executor()
    result = await loop.execute(handle.run_id, CONTEXT)
    assert result.state == RunState.FAILED
    assert len(model.requests) == 1
    events = await runtime.session_store.read_events(handle.run_id)
    failed = next(e for e in events if e.type == "run.failed")
    assert failed.data.error.code == error.code


@pytest.mark.parametrize("failure", ["raised", "unknown"])
async def test_unknown_reconciliation_error_pauses_and_can_be_checked_again(failure):
    from tests.sagents.v2.test_agent_loop_matrix import reply_pending_interaction

    uncertainty = RuntimeErrorInfo(
        code="mcp.result_not_received",
        category=ErrorCategory.UNCERTAIN_SIDE_EFFECT,
        message="remote result is not available yet",
        safe_to_resume=False,
    )

    class Executor:
        calls = 0
        checks = 0

        async def execute(self, call, context):
            self.calls += 1
            self.call = call
            raise SageV2Error(uncertainty)

        async def reconcile(self, operation_id, context):
            self.checks += 1
            if self.checks == 1:
                if failure == "raised":
                    raise SageV2Error(uncertainty)
                return ReconcileResult(
                    operation_id=operation_id,
                    state=ReconcileState.UNKNOWN,
                    error=uncertainty,
                )
            return ReconcileResult(
                operation_id=operation_id,
                state=ReconcileState.SUCCEEDED,
                result=ToolExecutionResult(
                    tool_call_id=self.call.tool_call_id, operation_id=operation_id
                ),
            )

    model = ScriptedModelProvider(
        (
            ScriptedModelStep(events=(completed(calls=(tool_call(),)),)),
            ScriptedModelStep(events=(completed("checked"),)),
        )
    )
    runtime, handle, loop, _ = await setup_loop(
        model, tools=(READ_TOOL.model_copy(update={"supports_reconciliation": True}),)
    )
    executor = Executor()
    loop.tool_executor = executor
    suspended = await loop.execute(handle.run_id, CONTEXT)
    assert suspended.state == RunState.SUSPENDED
    await reply_pending_interaction(
        runtime, handle, suspended, "reconcile", "check-again"
    )
    result = await loop.resume(handle.run_id, CONTEXT)
    assert result.state == RunState.COMPLETED
    assert executor.calls == 1
    assert executor.checks == 2
    assert not any(
        e.type == "run.failed"
        for e in await runtime.session_store.read_events(handle.run_id)
    )

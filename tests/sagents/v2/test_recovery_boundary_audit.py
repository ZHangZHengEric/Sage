"""Recover malformed tool receipts and legacy/network boundaries without a person."""

import asyncio

import httpx
import pytest

from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.items import TextBlock
from sagents.v2.model.recovery import collect_response
from sagents.v2.model.recovery_scope import RecoveryScope
from sagents.v2.tool.contracts import ToolExecutionResult, ReconcileState
from tests.sagents.v2.test_autonomous_tool_errors import (
    setup,
    step,
    call,
    assert_no_manual,
)
from tests.sagents.v2 import test_agent_loop_matrix as native
from tests.sagents.v2.test_builtin_model_protocols_matrix import request


@pytest.mark.parametrize(
    "malformed", ["none", "wrong_type", "wrong_call", "wrong_operation"]
)
async def test_bad_read_receipt_returns_feedback_and_agent_corrects(malformed):
    class Executor:
        calls = []

        async def execute(self, tool_call, context):
            self.calls.append(tool_call)
            result = ToolExecutionResult(
                tool_call_id=tool_call.tool_call_id,
                operation_id=tool_call.operation_id,
                content=(TextBlock(text="found"),),
            )
            if len(self.calls) > 1:
                return result
            if malformed == "none":
                return None
            if malformed == "wrong_type":
                return {"content": "not a receipt"}
            return result.model_copy(
                update={
                    "tool_call_id"
                    if malformed == "wrong_call"
                    else "operation_id": "unrelated"
                }
            )

    model = native.ScriptedModelProvider(
        (
            step(calls=(call(identifier="first"),)),
            step(calls=(call(identifier="fixed"),)),
            step("found"),
        )
    )
    runtime, handle, engine, _ = await setup(model)
    executor = Executor()
    engine.tool_executor = executor
    result = await asyncio.wait_for(engine.execute(handle.run_id, native.CONTEXT), 3)
    assert result.state == native.RunState.COMPLETED
    assert len(executor.calls) == 2
    feedback = [m for m in model.requests[1].messages if m.role == "tool"][-1]
    assert feedback.tool_call_id == "first"
    assert any(
        isinstance(b, TextBlock) and "tool.invalid_result" in b.text
        for b in feedback.content
    )
    await assert_no_manual(runtime, handle.run_id)


@pytest.mark.parametrize("reconciled", [False, True])
async def test_bad_write_receipt_is_reconciled_never_reexecuted(reconciled):
    class Executor(native.UncertainToolExecutor):
        async def execute(self, tool_call, context):
            self.calls.append(tool_call)
            return None

    definition = native.WRITE_TOOL.model_copy(
        update={"supports_reconciliation": reconciled}
    )
    model = native.ScriptedModelProvider(
        (step(calls=(call("write_value", key="x", value="1"),)), step("done"))
    )
    runtime, handle, engine, _ = await setup(model, tools=(definition,))
    executor = Executor((ReconcileState.SUCCEEDED,))
    engine.tool_executor = executor
    result = await engine.execute(handle.run_id, native.CONTEXT)
    assert result.state == (
        native.RunState.COMPLETED if reconciled else native.RunState.FAILED
    )
    assert len(executor.calls) == 1
    await assert_no_manual(runtime, handle.run_id)


@pytest.mark.parametrize("write", [False, True])
async def test_legacy_restart_without_checkpoint_does_not_request_manual_repair(write):
    dispatched = asyncio.Event()

    async def interrupted(tool_call, context):
        dispatched.set()
        await asyncio.Event().wait()

    definition = native.WRITE_TOOL if write else native.READ_TOOL
    first = call("write_value", key="x", value="1") if write else call()
    runtime, handle, engine, _ = await setup(
        native.ScriptedModelProvider((step(calls=(first,)),)),
        tools=(definition,),
        handlers={definition.name: interrupted},
    )
    task = asyncio.create_task(engine.execute(handle.run_id, native.CONTEXT))
    await asyncio.wait_for(dispatched.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    payload = await runtime.session_store.export_state()
    for row in payload["runs"]:
        row["checkpoint_id"] = (
            None  # Old records have the ledger but no execution checkpoint.
        )
    cold = native.ephemeral_runtime()
    await cold.session_store.load_state(payload)
    recovered = native.AgentLoopEngine(
        runtime=cold,
        model=native.ScriptedModelProvider((step("Outcome reported"),)),
        tool_catalog=engine.tool_catalog,
        tool_executor=engine.tool_executor,
    )
    result = await asyncio.wait_for(
        recovered.recover_interrupted(handle.run_id, native.CONTEXT), 3
    )
    assert result.state == (
        native.RunState.FAILED if write else native.RunState.COMPLETED
    )
    await assert_no_manual(cold, handle.run_id)


@pytest.mark.parametrize("phase", ["agent", "auxiliary"])
@pytest.mark.parametrize("partial", [False, True])
@pytest.mark.parametrize("failure", [ConnectionResetError, httpx.ReadError])
async def test_unwrapped_transport_failures_use_bounded_shared_recovery(
    monkeypatch, phase, partial, failure
):
    async def no_wait(self, seconds):
        await asyncio.sleep(0)

    monkeypatch.setattr(RecoveryScope, "wait", no_wait)
    monkeypatch.setattr(native.AgentLoopEngine, "_PROVIDER_RETRY_BASE_SECONDS", 0)

    class Model(native.ScriptedModelProvider):
        attempts = 0
        closed = 0

        async def _stream(self, request):
            self.attempts += 1
            try:
                if self.attempts == 1:
                    if partial:
                        yield native.ModelStreamEvent(
                            kind=native.ModelEventKind.TEXT_DELTA, delta="interrupted"
                        )
                    raise failure("connection reset")
                yield native.completed("done")
            finally:
                self.closed += 1

    model = Model(())
    if phase == "agent":
        runtime, handle, engine, _ = await setup(model)
        result = await engine.execute(handle.run_id, native.CONTEXT)
        assert result.state == native.RunState.COMPLETED
        events = await assert_no_manual(runtime, handle.run_id)
        assert len([e for e in events if e.type == "step.retry_scheduled"]) == 1
        if partial:
            assert any(
                e.type == "item.completed"
                and e.data.item.status == native.ItemStatus.CANCELLED
                for e in events
            )
    else:
        assert (await collect_response(model, request())).text == "done"
    assert model.attempts == model.closed == 2


@pytest.mark.parametrize("phase", ["agent", "auxiliary"])
async def test_programming_errors_are_not_retried_as_transport(phase):
    class Model(native.ScriptedModelProvider):
        attempts = 0

        async def _stream(self, request):
            self.attempts += 1
            raise ValueError("plugin programming error")
            yield

    model = Model(())
    if phase == "agent":
        runtime, handle, engine, _ = await setup(model)
        assert (
            await engine.execute(handle.run_id, native.CONTEXT)
        ).state == native.RunState.FAILED
        await assert_no_manual(runtime, handle.run_id)
    else:
        with pytest.raises(ValueError):
            await collect_response(model, request())
    assert model.attempts == 1


@pytest.mark.parametrize("phase", ["agent", "auxiliary"])
@pytest.mark.parametrize("status", [401, 429])
async def test_raw_http_error_respects_auth_and_retry_budgets(
    monkeypatch, phase, status
):
    async def no_wait(self, seconds):
        await asyncio.sleep(0)

    monkeypatch.setattr(RecoveryScope, "wait", no_wait)
    monkeypatch.setattr(native.AgentLoopEngine, "_PROVIDER_RETRY_BASE_SECONDS", 0)

    class Model(native.ScriptedModelProvider):
        attempts = 0

        async def _stream(self, request):
            self.attempts += 1
            response = httpx.Response(
                status, request=httpx.Request("POST", "https://invalid.test")
            )
            raise httpx.HTTPStatusError(
                "timeout", request=response.request, response=response
            )
            yield

    model = Model(())
    if phase == "agent":
        runtime, handle, engine, _ = await setup(model, transient_retry_limit=2)
        result = await engine.execute(handle.run_id, native.CONTEXT)
        assert result.state == native.RunState.FAILED
        events = await assert_no_manual(runtime, handle.run_id)
        error = [e.data.error for e in events if e.type == "run.failed"][-1]
    else:
        with pytest.raises(SageV2Error) as failure:
            await collect_response(model, request())
        error = failure.value.info
    assert model.attempts == (1 if status == 401 else 3)
    from sagents.v2.model.failures import failure_from_error
    from sagents.v2.contracts.model_recovery import ModelFailureKind

    assert failure_from_error(error).kind == (
        ModelFailureKind.AUTHENTICATION
        if status == 401
        else ModelFailureKind.RATE_LIMIT
    )


async def test_incomplete_legacy_write_ledger_stops_without_asking_user_to_guess():
    runtime, handle, engine, _ = await setup(native.ScriptedModelProvider(()))
    running = await runtime.start_execution(
        run_id=handle.run_id,
        expected_revision=handle.run_revision,
        context=native.CONTEXT,
        idempotency_key="legacy:start",
    )
    await runtime.session_store.commit_run(
        run_id=handle.run_id,
        expected_revision=running.revision,
        expected_states={native.RunState.RUNNING},
        new_state=native.RunState.RUNNING,
        drafts=(
            native.EventDraft(
                type="tool.call.started",
                turn_id="turn_old",
                step_id="step_old",
                data=native.ToolEventData(
                    tool_call_id="call_old",
                    tool_name="write_value",
                    state="started",
                    operation_id="operation_old",
                    idempotency_key="key_old",
                ),
            ),
        ),
        context=native.CONTEXT,
        idempotency_key="legacy:started",
    )
    result = await engine.recover_interrupted(handle.run_id, native.CONTEXT)
    assert result.state == native.RunState.FAILED
    events = await assert_no_manual(runtime, handle.run_id)
    assert [e.data.error.code for e in events if e.type == "run.failed"] == [
        "tool.recovery_ledger_incomplete"
    ]

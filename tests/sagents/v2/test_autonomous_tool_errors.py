"""Default autonomy retains approval and durable side-effect barriers."""

import pytest

from sagents.v2.contracts.commands import RunConfig
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.items import TextBlock, JsonBlock
from sagents.v2.tool.contracts import ToolExecutionResult, ReconcileState
from sagents.v2.agent.policy.continuation import (
    ContinuationDecision,
    ContinuationAction,
    InteractionDraft,
)
from sagents.v2.agent.policy.tool_policy import ApprovalStrategy
from sagents.v2.agent.policy.plugins.tool_policy import DefaultToolPolicy
from sagents.v2.testing.plugins.scripted_model import (
    ScriptedModelProvider,
    ScriptedModelStep,
)
from tests.sagents.v2 import test_agent_loop_matrix as native


def step(text="", calls=()):
    return ScriptedModelStep(events=(native.completed(text, calls=calls),))


def call(name="read_value", identifier="read", **arguments):
    return native.ModelToolCall(
        tool_call_id=identifier, name=name, arguments=arguments or {"key": "x"}
    )


async def setup(provider, **kwargs):
    kwargs.setdefault(
        "tool_policy",
        DefaultToolPolicy(approval_strategy=ApprovalStrategy.AUTO_APPROVE),
    )
    return await native.setup_loop(provider, autonomous_error_recovery=True, **kwargs)


async def assert_no_manual(runtime, run_id):
    events = await runtime.session_store.read_events(run_id)
    assert not [event for event in events if event.type == "interaction.requested"]
    for event in events:
        if event.type == "run.failed" and getattr(event.data, "error", None):
            payload = event.data.error.metadata.get("recovery_questionnaire", {})
            assert not payload.get("questions")
    return events


@pytest.mark.parametrize("received", [True, False])
async def test_partial_tool_output_keeps_error_visible_and_agent_repairs(received):
    calls = []

    async def handler(tool_call, context):
        calls.append(tool_call)
        if len(calls) == 1:
            return ToolExecutionResult(
                tool_call_id=tool_call.tool_call_id,
                operation_id=tool_call.operation_id,
                content=(JsonBlock(value={"partial": "kept"}),),
                error=RuntimeErrorInfo(
                    code="tool.invalid_path",
                    category=ErrorCategory.VALIDATION,
                    message="Choose an existing path",
                    metadata={"tool_result_received": received},
                ),
            )
        return ToolExecutionResult(
            tool_call_id=tool_call.tool_call_id,
            operation_id=tool_call.operation_id,
            content=(TextBlock(text="found"),),
        )

    def check_feedback(request):
        tool = [msg for msg in request.messages if msg.role == "tool"][-1]
        assert tool.content[0] == JsonBlock(value={"partial": "kept"})
        assert any(
            isinstance(block, TextBlock) and "tool.invalid_path" in block.text
            for block in tool.content
        )

    provider = ScriptedModelProvider(
        (
            step(calls=(call(identifier="bad"),)),
            ScriptedModelStep(
                events=(
                    native.completed("", calls=(call(identifier="fixed", key="good"),)),
                ),
                assertion=check_feedback,
            ),
            step("found"),
        )
    )
    runtime, handle, engine, _ = await setup(provider, handlers={"read_value": handler})
    result = await engine.execute(handle.run_id, native.CONTEXT)
    assert result.state == native.RunState.COMPLETED
    assert len(calls) == 2
    await assert_no_manual(runtime, handle.run_id)


async def test_read_only_unknown_result_needs_no_human_or_mutation_barrier():
    provider = ScriptedModelProvider(
        (step(calls=(call(),)), step("The read could not be completed."))
    )
    runtime, handle, engine, _ = await setup(provider, tools=(native.READ_TOOL,))
    engine.tool_executor = native.UncertainToolExecutor(())
    result = await engine.execute(handle.run_id, native.CONTEXT)
    assert result.state == native.RunState.COMPLETED
    await assert_no_manual(runtime, handle.run_id)


async def test_unknown_write_allows_investigation_but_blocks_duplicate_write():
    writes, reads = [], []

    async def write(tool_call, context):
        writes.append(tool_call)
        raise SageV2Error(
            RuntimeErrorInfo(
                code="tool.response_lost",
                category=ErrorCategory.UNCERTAIN_SIDE_EFFECT,
                message="Unknown outcome",
                metadata={"tool_result_received": True},
            )
        )

    async def read(tool_call, context):
        reads.append(tool_call)
        return ToolExecutionResult(
            tool_call_id=tool_call.tool_call_id,
            operation_id=tool_call.operation_id,
            content=(TextBlock(text="Status is still unknown"),),
        )

    provider = ScriptedModelProvider(
        (
            step(calls=(call("write_value", "first", key="x", value="1"),)),
            step(calls=(call(identifier="inspect"),)),
            step(calls=(call("write_value", "duplicate", key="x", value="1"),)),
            step("Outcome unverified"),
        )
    )
    runtime, handle, engine, _ = await setup(
        provider, handlers={"write_value": write, "read_value": read}
    )
    result = await engine.execute(handle.run_id, native.CONTEXT)
    assert result.state == native.RunState.FAILED
    assert len(writes) == 1 and len(reads) == 1
    events = await assert_no_manual(runtime, handle.run_id)
    assert any(
        getattr(e.data, "error", None)
        and e.data.error.code == "tool.unresolved_effect_barrier"
        for e in events
    )


@pytest.mark.parametrize("call_aware", [False, True])
async def test_same_write_reconciles_original_operation_without_redispatch(call_aware):
    definition = native.WRITE_TOOL.model_copy(update={"supports_reconciliation": True})
    provider = ScriptedModelProvider(
        (
            step(calls=(call("write_value", "first", key="x", value="1"),)),
            step(calls=(call("write_value", "poll", key="x", value="1"),)),
            step("Verified result"),
        )
    )
    runtime, handle, engine, _ = await setup(provider, tools=(definition,))
    executor = native.UncertainToolExecutor(
        (ReconcileState.UNKNOWN, ReconcileState.SUCCEEDED)
    )
    if call_aware:

        async def reconcile_call(original_call, context):
            assert original_call.tool_call_id == executor.calls[0].tool_call_id
            assert original_call.operation_id == executor.calls[0].operation_id
            return await executor.reconcile(original_call.operation_id, context)

        executor.reconcile_call = reconcile_call
    engine.tool_executor = executor
    result = await engine.execute(handle.run_id, native.CONTEXT)
    assert result.state == native.RunState.COMPLETED
    assert len(executor.calls) == 1
    assert len(executor.reconciliations) == 2
    assert len(set(executor.reconciliations)) == 1
    await assert_no_manual(runtime, handle.run_id)


async def test_postprocessing_failure_preserves_successful_write():
    class BrokenProcessor:
        async def process(self, *args, **kwargs):
            raise OSError("cannot format result")

    provider = ScriptedModelProvider(
        (step(calls=(call("write_value", key="x", value="1"),)), step("saved"))
    )
    runtime, handle, engine, executor = await setup(provider)
    engine.tool_result_processor = BrokenProcessor()
    result = await engine.execute(handle.run_id, native.CONTEXT)
    assert result.state == native.RunState.COMPLETED
    assert len(executor.calls) == 1
    tool = [msg for msg in provider.requests[-1].messages if msg.role == "tool"][-1]
    assert any(
        isinstance(block, TextBlock) and "do not repeat" in block.text
        for block in tool.content
    )
    await assert_no_manual(runtime, handle.run_id)


async def test_internal_recovery_prompt_is_corrected_without_a_new_user_turn():
    class Policy:
        calls = 0

        async def decide(self, context):
            self.calls += 1
            if self.calls == 1:
                return ContinuationDecision(
                    action=ContinuationAction.REQUEST_INTERACTION,
                    reason_code="status.invalid",
                    reason="invalid status",
                    interaction=InteractionDraft(
                        interaction_type="agent_recovery",
                        allowed_decisions=("submit", "cancel"),
                    ),
                )
            return ContinuationDecision(
                action=ContinuationAction.COMPLETE_RUN,
                reason_code="done",
                reason="done",
            )

    provider = ScriptedModelProvider((step("working"), step("done")))
    runtime, handle, engine, _ = await setup(provider, continuation_policy=Policy())
    result = await engine.execute(handle.run_id, native.CONTEXT)
    assert result.state == native.RunState.COMPLETED
    assert any(
        msg.metadata.get("inference_view_only")
        for msg in provider.requests[-1].messages
    )
    await assert_no_manual(runtime, handle.run_id)


def test_new_runs_default_to_autonomous_error_recovery():
    assert RunConfig().autonomous_error_recovery is True


async def test_repeated_tool_failures_remain_bounded_across_automatic_stages():
    async def broken(tool_call, context):
        raise FileNotFoundError("missing file")

    provider = ScriptedModelProvider(
        tuple(
            step(calls=(call(identifier=f"call-{n}", key=f"missing-{n}"),))
            for n in range(12)
        )
    )
    runtime, handle, engine, _ = await setup(
        provider,
        handlers={"read_value": broken},
        max_steps=1,
        automatic_stage_continuation=True,
    )
    result = await engine.execute(handle.run_id, native.CONTEXT)
    assert result.state == native.RunState.FAILED
    assert len(provider.requests) <= 7
    await assert_no_manual(runtime, handle.run_id)


async def test_tool_error_and_approval_keep_canonical_ledger_resumable():
    async def broken(tool_call, context):
        return ToolExecutionResult(
            tool_call_id=tool_call.tool_call_id,
            operation_id=tool_call.operation_id,
            content=(JsonBlock(value={"partial": "kept"}),),
            error=RuntimeErrorInfo(
                code="tool.read_failed",
                category=ErrorCategory.PROVIDER_PERMANENT,
                message="Read failed",
            ),
        )

    provider = ScriptedModelProvider(
        (
            step(
                calls=(
                    call(identifier="read"),
                    call("write_value", "write", key="x", value="1"),
                )
            ),
            step("done"),
        )
    )
    runtime, handle, engine, _ = await setup(
        provider,
        handlers={"read_value": broken, "write_value": native.tool_handler},
        tool_policy=DefaultToolPolicy(),
    )
    suspended = await engine.execute(handle.run_id, native.CONTEXT)
    assert suspended.state == native.RunState.SUSPENDED
    suspension, interaction = await native._pending_interaction(runtime, suspended)
    assert interaction.interaction_type.value == "approval"
    await runtime.reply_interaction(
        native._approval_reply(
            handle.run_id,
            suspended,
            suspension,
            interaction,
            "approve_once",
            "approve-write",
        ),
        native.CONTEXT,
    )
    result = await engine.resume(handle.run_id, native.CONTEXT)
    assert result.state == native.RunState.COMPLETED
    events = await runtime.session_store.read_events(handle.run_id)
    assert len([e for e in events if e.type == "interaction.requested"]) == 1


@pytest.mark.parametrize("changed_arguments", [False, True])
async def test_unknown_write_barrier_survives_worker_restart(changed_arguments):
    import asyncio

    dispatched = asyncio.Event()
    writes = []

    async def interrupted(tool_call, context):
        writes.append(tool_call)
        dispatched.set()
        await asyncio.Event().wait()

    provider = ScriptedModelProvider(
        (step(calls=(call("write_value", "first", key="x", value="1"),)),)
    )
    runtime, handle, engine, _ = await setup(
        provider, handlers={"write_value": interrupted}
    )
    task = asyncio.create_task(engine.execute(handle.run_id, native.CONTEXT))
    await asyncio.wait_for(dispatched.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    cold = native.ephemeral_runtime()
    await cold.session_store.load_state(await runtime.session_store.export_state())
    model = ScriptedModelProvider(
        (
            step(
                calls=(
                    call(
                        "write_value",
                        "again",
                        key="other" if changed_arguments else "x",
                        value="1",
                    ),
                )
            ),
            step("Cannot verify outcome"),
        )
    )
    recovered = native.AgentLoopEngine(
        runtime=cold,
        model=model,
        tool_catalog=engine.tool_catalog,
        tool_executor=engine.tool_executor,
        tool_policy=DefaultToolPolicy(approval_strategy=ApprovalStrategy.AUTO_APPROVE),
    )
    result = await recovered.recover_interrupted(handle.run_id, native.CONTEXT)
    assert result.state == native.RunState.FAILED
    assert len(writes) == 1
    await assert_no_manual(cold, handle.run_id)


@pytest.mark.parametrize(
    "invalid_result", ["wrong_type", "wrong_identity", "wrong_outcome"]
)
async def test_invalid_result_processor_cannot_change_committed_execution(
    invalid_result,
):
    class Processor:
        async def process(self, result, **kwargs):
            if invalid_result == "wrong_type":
                return None
            if invalid_result == "wrong_outcome":
                return result.model_copy(
                    update={
                        "error": RuntimeErrorInfo(
                            code="formatter.failed",
                            category=ErrorCategory.VALIDATION,
                            message="formatting is not an execution failure",
                        )
                    }
                )
            return result.model_copy(update={"operation_id": "unrelated"})

    model = ScriptedModelProvider(
        (step(calls=(call("write_value", key="x", value="1"),)), step("saved"))
    )
    runtime, handle, engine, executor = await setup(model)
    engine.tool_result_processor = Processor()
    result = await engine.execute(handle.run_id, native.CONTEXT)
    assert result.state == native.RunState.COMPLETED
    assert len(executor.calls) == 1
    events = await assert_no_manual(runtime, handle.run_id)
    completed = [e for e in events if e.type == "tool.call.succeeded"]
    assert completed[0].data.operation_id == executor.calls[0].operation_id


async def test_confirmed_failure_releases_barrier_for_agent_corrected_write():
    class Executor(native.UncertainToolExecutor):
        async def execute(self, tool_call, context):
            if not self.calls:
                return await super().execute(tool_call, context)
            self.calls.append(tool_call)
            return ToolExecutionResult(
                tool_call_id=tool_call.tool_call_id,
                operation_id=tool_call.operation_id,
                content=(TextBlock(text="saved"),),
            )

    definition = native.WRITE_TOOL.model_copy(update={"supports_reconciliation": True})
    model = ScriptedModelProvider(
        (
            step(calls=(call("write_value", "first", key="x", value="1"),)),
            step(calls=(call("write_value", "fixed", key="x", value="2"),)),
            step("saved"),
        )
    )
    runtime, handle, engine, _ = await setup(model, tools=(definition,))
    executor = Executor((ReconcileState.FAILED,))
    engine.tool_executor = executor
    result = await engine.execute(handle.run_id, native.CONTEXT)
    assert result.state == native.RunState.COMPLETED
    assert len(executor.calls) == 2
    assert executor.calls[0].operation_id != executor.calls[1].operation_id
    await assert_no_manual(runtime, handle.run_id)


async def test_unknown_sibling_does_not_replace_an_already_received_success():
    writes = []

    async def handler(tool_call, context):
        writes.append(tool_call.tool_call_id)
        if tool_call.tool_call_id == "unknown":
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="tool.response_lost",
                    category=ErrorCategory.UNCERTAIN_SIDE_EFFECT,
                    message="lost receipt",
                )
            )
        return ToolExecutionResult(
            tool_call_id=tool_call.tool_call_id,
            operation_id=tool_call.operation_id,
            content=(TextBlock(text="saved sibling"),),
        )

    model = ScriptedModelProvider(
        (
            step(
                calls=(
                    call("write_value", "unknown", key="x", value="1"),
                    call("write_value", "saved", key="y", value="2"),
                )
            ),
            step("Cannot verify the first operation"),
        )
    )
    runtime, handle, engine, _ = await setup(model, handlers={"write_value": handler})
    result = await engine.execute(handle.run_id, native.CONTEXT)
    assert result.state == native.RunState.FAILED
    assert sorted(writes) == ["saved", "unknown"]
    events = await assert_no_manual(runtime, handle.run_id)
    assert any(
        e.type == "tool.call.succeeded" and e.data.tool_call_id == "saved"
        for e in events
    )
    assert any(
        isinstance(block, TextBlock) and block.text == "saved sibling"
        for msg in model.requests[-1].messages
        if msg.role == "tool"
        for block in msg.content
    )


async def test_delegation_preserves_unknown_child_effect_and_successful_sibling():
    from types import SimpleNamespace
    from sagents.v2.agent.multi_agent import AgentMode
    from sagents.v2.agent.multi_agent.contracts import DelegationResult
    from sagents.v2.tool.plugins.delegation import _DelegationMethods
    from sagents.v2.tool.decorated import ToolInvocation
    from sagents.v2.tool.contracts import ToolCall

    runtime, handle, _, _ = await setup(ScriptedModelProvider(()))
    child_error = RuntimeErrorInfo(
        code="tool.outcome_unverified",
        category=ErrorCategory.VALIDATION,
        message="unknown remote write",
    )
    values = (
        DelegationResult(
            task_id="a",
            agent_id="child",
            child_run_id="child-a",
            outcome=native.RunState.FAILED,
            error=child_error,
        ),
        DelegationResult(
            task_id="b",
            agent_id="child",
            child_run_id="child-b",
            outcome=native.RunState.COMPLETED,
            content=(TextBlock(text="saved sibling"),),
        ),
    )

    async def delegate(*args, **kwargs):
        return values

    plugin = _DelegationMethods(
        SimpleNamespace(mode=AgentMode.TEAM, delegate=delegate), runtime
    )
    tool_call = ToolCall(
        tool_call_id="delegate",
        tool_name="sys_team_delegate_task",
        operation_id="original-operation",
        idempotency_key="original-key",
        owner_run_id=handle.run_id,
        arguments={"tasks": [{"agent_id": "child", "content": "work"}]},
    )
    result = await plugin._delegate(
        tool_call.arguments["tasks"], ToolInvocation(tool_call, native.CONTEXT)
    )
    assert result.error.category == ErrorCategory.UNCERTAIN_SIDE_EFFECT
    assert (
        result.content[0].value["results"][1]["content"][0]["text"] == "saved sibling"
    )
    reconciled = await plugin._reconcile_delegation(tool_call, native.CONTEXT)
    assert reconciled.state == ReconcileState.UNKNOWN


async def test_reconciliation_of_another_operation_cannot_clear_unknown_write():
    class Executor(native.UncertainToolExecutor):
        async def reconcile(self, operation_id, context):
            return native.ReconcileResult(
                operation_id="unrelated",
                state=ReconcileState.SUCCEEDED,
                result=ToolExecutionResult(
                    tool_call_id="other",
                    operation_id="unrelated",
                    content=(TextBlock(text="wrong receipt"),),
                ),
            )

    model = ScriptedModelProvider(
        (step(calls=(call("write_value", key="x", value="1"),)), step("done"))
    )
    definition = native.WRITE_TOOL.model_copy(update={"supports_reconciliation": True})
    runtime, handle, engine, _ = await setup(model, tools=(definition,))
    engine.tool_executor = Executor(())
    result = await engine.execute(handle.run_id, native.CONTEXT)
    assert result.state == native.RunState.FAILED
    assert len(engine.tool_executor.calls) == 1
    await assert_no_manual(runtime, handle.run_id)

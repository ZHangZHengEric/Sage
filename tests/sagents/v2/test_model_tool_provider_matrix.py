from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from sagents.v2.model.contracts import (
    ModelEventKind,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
)
from sagents.v2.testing.plugins.scripted_model import (
    ScriptedModelProvider,
    ScriptedModelStep,
)
from sagents.v2.tool.contracts import (
    ReconcileState,
    SideEffectLevel,
    ToolCall,
    ToolDefinition,
    ToolExecutionResult,
)
from sagents.v2.tool.plugins.ephemeral import (
    InMemoryToolCatalog,
    InMemoryToolExecutor,
)
from sagents.v2.tool import FilteredToolCatalog, InvocationGrantToolCatalog
from sagents.v2.tool.composite import CompositeToolExecutor, RoutedToolExecutor
from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import (
    ActorRef,
    PrincipalType,
    RequestContext,
)


CONTEXT = RequestContext(
    actor=ActorRef(principal_id="agent_1", principal_type=PrincipalType.AGENT)
)


def request(name="1"):
    return ModelRequest(
        request_id=f"request_{name}",
        run_id=f"run_{name}",
        model_binding="primary",
        messages=(ModelMessage(role="user", content=(TextBlock(text="hello"),)),),
    )


def complete(text="done", *, tool_calls=()):
    return ModelStreamEvent(
        kind=ModelEventKind.COMPLETED,
        response=ModelResponse(
            response_id="response_1",
            text=text,
            tool_calls=tool_calls,
            finish_reason="tool_calls" if tool_calls else "stop",
        ),
    )


@pytest.mark.parametrize(
    ("kind", "delta", "response", "valid"),
    [
        (ModelEventKind.TEXT_DELTA, "a", None, True),
        (ModelEventKind.REASONING_DELTA, "r", None, True),
        (
            ModelEventKind.COMPLETED,
            None,
            ModelResponse(response_id="r", finish_reason="stop"),
            True,
        ),
        (ModelEventKind.TEXT_DELTA, None, None, False),
        (
            ModelEventKind.TEXT_DELTA,
            "a",
            ModelResponse(response_id="r", finish_reason="stop"),
            False,
        ),
        (
            ModelEventKind.COMPLETED,
            "a",
            ModelResponse(response_id="r", finish_reason="stop"),
            False,
        ),
        (ModelEventKind.COMPLETED, None, None, False),
    ],
)
def test_model_stream_event_payload_matrix(kind, delta, response, valid):
    kwargs = {"kind": kind, "delta": delta, "response": response}
    if valid:
        assert ModelStreamEvent(**kwargs).kind == kind
    else:
        with pytest.raises(ValidationError):
            ModelStreamEvent(**kwargs)


@pytest.mark.asyncio
async def test_scripted_model_streams_in_order_and_records_exact_request():
    provider = ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(
                    ModelStreamEvent(
                        kind=ModelEventKind.REASONING_DELTA, delta="think"
                    ),
                    ModelStreamEvent(kind=ModelEventKind.TEXT_DELTA, delta="do"),
                    complete("done"),
                ),
                assertion=lambda value: (
                    value.messages[0].content[0].text == "hello"
                    or (_ for _ in ()).throw(AssertionError())
                ),
            ),
        )
    )
    events = [event async for event in provider.stream(request())]
    assert [event.kind.value for event in events] == [
        "reasoning_delta",
        "text_delta",
        "completed",
    ]
    assert provider.requests == [request()]


@pytest.mark.asyncio
async def test_scripted_model_concurrent_requests_claim_unique_steps():
    provider = ScriptedModelProvider(
        tuple(
            ScriptedModelStep(events=(complete(f"result_{index}"),), delay_yields=1)
            for index in range(20)
        )
    )

    async def consume(index):
        values = [value async for value in provider.stream(request(str(index)))]
        return values[-1].response.text

    results = await asyncio.gather(*(consume(index) for index in range(20)))
    assert len(set(results)) == 20
    assert len(provider.requests) == 20


@pytest.mark.asyncio
async def test_scripted_model_exhaustion_and_injected_error_are_typed():
    error = RuntimeErrorInfo(
        code="model.rate_limited",
        category=ErrorCategory.RATE_LIMITED,
        message="slow down",
        retryable=True,
    )
    provider = ScriptedModelProvider((ScriptedModelStep(events=(), error=error),))
    with pytest.raises(SageV2Error) as injected:
        _ = [value async for value in provider.stream(request("1"))]
    assert injected.value.info == error
    with pytest.raises(SageV2Error) as exhausted:
        _ = [value async for value in provider.stream(request("2"))]
    assert exhausted.value.info.code == "model.script_exhausted"


TOOL = ToolDefinition(
    name="sum",
    description="sum two integers",
    input_schema={
        "type": "object",
        "properties": {
            "a": {"type": "integer"},
            "b": {"type": "integer"},
        },
        "required": ["a", "b"],
        "additionalProperties": False,
    },
    side_effect_level=SideEffectLevel.NONE,
)


def call(key="key_1", *, arguments=None, operation="operation_1"):
    return ToolCall(
        tool_call_id="call_1",
        tool_name="sum",
        arguments=arguments or {"a": 1, "b": 2},
        operation_id=operation,
        idempotency_key=key,
        owner_run_id="run_1",
    )


async def sum_handler(tool_call, context):
    await asyncio.sleep(0)
    return ToolExecutionResult(
        tool_call_id=tool_call.tool_call_id,
        operation_id=tool_call.operation_id,
        content=(
            TextBlock(text=str(tool_call.arguments["a"] + tool_call.arguments["b"])),
        ),
    )


@pytest.mark.asyncio
async def test_tool_catalog_is_stable_and_unknown_is_typed():
    catalog = InMemoryToolCatalog((TOOL,))
    assert await catalog.list_tools(run_id="run_1") == (TOOL,)
    assert await catalog.get_tool("sum", run_id="run_1") == TOOL
    with pytest.raises(SageV2Error) as missing:
        await catalog.get_tool("missing", run_id="run_1")
    assert missing.value.info.code == "tool.not_found"


@pytest.mark.asyncio
async def test_filtered_catalog_hides_and_rejects_tools_outside_resolved_run_set():
    hidden = TOOL.model_copy(update={"name": "hidden"})
    catalog = FilteredToolCatalog(InMemoryToolCatalog((TOOL, hidden)), ("sum",))

    assert await catalog.list_tools(run_id="run_1") == (TOOL,)
    with pytest.raises(SageV2Error) as denied:
        await catalog.get_tool("hidden", run_id="run_1")
    assert denied.value.info.code == "tool.not_enabled"
    assert denied.value.info.category == ErrorCategory.POLICY_DENIED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("normal", {"sum"}),
        ("plan", {"sum", "goal_submit"}),
        ("goal", {"sum", "goal_submit", "goal_complete"}),
    ],
)
async def test_invocation_grant_catalog_enforces_goal_controls_for_list_and_lookup(
    mode, expected
):
    controls = (
        TOOL.model_copy(update={"name": "goal_submit"}),
        TOOL.model_copy(update={"name": "goal_complete"}),
    )

    async def command_reader(run_id):
        del run_id
        return type("Command", (), {"invocation_mode": mode})()

    catalog = InvocationGrantToolCatalog(
        InMemoryToolCatalog((TOOL, *controls)),
        ("sum", "goal_submit", "goal_complete"),
        command_reader,
    )
    assert {
        value.name for value in await catalog.list_tools(run_id="run_1")
    } == expected
    for control in {"goal_submit", "goal_complete"} - expected:
        with pytest.raises(SageV2Error) as denied:
            await catalog.get_tool(control, run_id="run_1")
        assert denied.value.info.code == "tool.not_enabled"


@pytest.mark.asyncio
async def test_invocation_grant_catalog_honors_explicit_per_run_tool_grant():
    hidden = TOOL.model_copy(update={"name": "hidden"})

    async def command_reader(run_id):
        del run_id
        return type(
            "Command",
            (),
            {
                "invocation_mode": "normal",
                "config": type("Config", (), {"enabled_tools": ("sum",)})(),
            },
        )()

    catalog = InvocationGrantToolCatalog(
        InMemoryToolCatalog((TOOL, hidden)),
        ("sum", "hidden"),
        command_reader,
    )

    assert await catalog.list_tools(run_id="run_1") == (TOOL,)
    with pytest.raises(SageV2Error) as denied:
        await catalog.get_tool("hidden", run_id="run_1")
    assert denied.value.info.code == "tool.not_enabled"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    [
        {"a": 1},
        {"a": "1", "b": 2},
        {"a": 1, "b": 2, "extra": True},
    ],
)
async def test_tool_executor_schema_validation_prevents_handler_dispatch(arguments):
    executor = InMemoryToolExecutor({"sum": TOOL}, {"sum": sum_handler})
    with pytest.raises(SageV2Error) as invalid:
        await executor.execute(call(arguments=arguments), CONTEXT)
    assert invalid.value.info.code == "tool.arguments_invalid"
    assert executor.calls == []


@pytest.mark.asyncio
async def test_tool_idempotency_coalesces_concurrent_calls_and_replays_result():
    dispatches = 0

    async def counting_handler(tool_call, context):
        nonlocal dispatches
        dispatches += 1
        await asyncio.sleep(0)
        return await sum_handler(tool_call, context)

    executor = InMemoryToolExecutor({"sum": TOOL}, {"sum": counting_handler})
    results = await asyncio.gather(
        *(executor.execute(call(), CONTEXT) for _ in range(20))
    )
    replay = await executor.execute(call(), CONTEXT)
    assert dispatches == 1
    assert len(executor.calls) == 1
    assert all(result == results[0] for result in (*results, replay))


@pytest.mark.asyncio
async def test_tool_executor_releases_terminal_run_idempotency_state():
    dispatches = 0

    async def counting_handler(tool_call, context):
        nonlocal dispatches
        dispatches += 1
        return await sum_handler(tool_call, context)

    executor = InMemoryToolExecutor({"sum": TOOL}, {"sum": counting_handler})
    await executor.execute(call(), CONTEXT)

    await executor.release_run("run_1")
    reconciled = await executor.reconcile("operation_1", CONTEXT)
    await executor.execute(
        call(arguments={"a": 2, "b": 3}, operation="operation_2"), CONTEXT
    )

    assert reconciled.state == ReconcileState.UNKNOWN
    assert dispatches == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("executor_kind", ["routed", "composite"])
async def test_composite_release_continues_after_one_plugin_cleanup_fails(
    executor_kind,
):
    class Releaser:
        def __init__(self, *, fail=False):
            self.fail = fail
            self.released = []

        async def release_run(self, run_id):
            self.released.append(run_id)
            if self.fail:
                raise OSError("cleanup unavailable")

    failing = Releaser(fail=True)
    healthy = Releaser()
    executor = (
        RoutedToolExecutor({"first": failing, "second": healthy})
        if executor_kind == "routed"
        else CompositeToolExecutor((failing, healthy))
    )
    executor._operation_routes["operation_1"] = failing
    executor._operation_run_ids["operation_1"] = "run_1"

    with pytest.raises(OSError, match="cleanup unavailable"):
        await executor.release_run("run_1")

    assert failing.released == ["run_1"]
    assert healthy.released == ["run_1"]
    assert executor._operation_routes == {}
    assert executor._operation_run_ids == {}


@pytest.mark.asyncio
async def test_tool_idempotency_rejects_key_reuse_for_a_different_call():
    executor = InMemoryToolExecutor({"sum": TOOL}, {"sum": sum_handler})

    await executor.execute(call(), CONTEXT)
    with pytest.raises(SageV2Error) as conflict:
        await executor.execute(
            call(arguments={"a": 2, "b": 3}, operation="operation_2"), CONTEXT
        )

    assert conflict.value.info.code == "tool.idempotency_conflict"
    assert len(executor.calls) == 1


@pytest.mark.asyncio
async def test_tool_result_identity_mismatch_is_provider_error_and_not_cached():
    async def bad_handler(tool_call, context):
        return ToolExecutionResult(
            tool_call_id="different_call",
            operation_id=tool_call.operation_id,
            content=(TextBlock(text="bad"),),
        )

    executor = InMemoryToolExecutor({"sum": TOOL}, {"sum": bad_handler})
    with pytest.raises(SageV2Error) as mismatch:
        await executor.execute(call(), CONTEXT)
    assert mismatch.value.info.code == "tool.result_identity_mismatch"
    assert (
        await executor.reconcile("operation_1", CONTEXT)
    ).state == ReconcileState.UNKNOWN


@pytest.mark.asyncio
async def test_reconcile_distinguishes_succeeded_pending_and_unknown():
    started = asyncio.Event()
    release = asyncio.Event()

    async def controlled_handler(tool_call, context):
        started.set()
        await release.wait()
        return await sum_handler(tool_call, context)

    executor = InMemoryToolExecutor({"sum": TOOL}, {"sum": controlled_handler})
    executing = asyncio.create_task(executor.execute(call(), CONTEXT))
    await started.wait()
    assert (
        await executor.reconcile("operation_1", CONTEXT)
    ).state == ReconcileState.PENDING
    assert (
        await executor.reconcile("missing_operation", CONTEXT)
    ).state == ReconcileState.UNKNOWN
    release.set()
    expected = await executing
    reconciled = await executor.reconcile("operation_1", CONTEXT)
    assert reconciled.state == ReconcileState.SUCCEEDED
    assert reconciled.result == expected

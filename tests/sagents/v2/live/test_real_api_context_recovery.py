"""Real upstream acceptance: no fabricated provider failures in this module."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path

import pytest
import pytest_asyncio

from tests.sagents.v2.live.test_gpt_5_6_luna_scenarios import _live_provider, CONTEXT
from sagents.v2.agent.engine import AgentLoopEngine
from sagents.v2.context import (
    ContextBudget,
    DefaultContextAssembler,
    InMemoryConversationSummaryStore,
    PersistentSummaryContextReducer,
)
from sagents.v2.context.plugins.summarizer_model import ModelConversationSummarizer
from sagents.v2.contracts.commands import InputItem, RunConfig, StartRun
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.run_state import RunState
from sagents.v2.model import ModelEventKind, ModelMessage, ModelResponse
from sagents.v2.testing.runtime import ephemeral_runtime
from sagents.v2.tool import (
    InMemoryToolCatalog,
    InMemoryToolExecutor,
    SideEffectLevel,
    ToolDefinition,
    ToolExecutionResult,
)

pytestmark = [pytest.mark.live, pytest.mark.timeout(600)]
_MODELS = []


def real_provider():
    provider = _live_provider()
    _MODELS.append(provider)
    return provider


@pytest_asyncio.fixture(autouse=True)
async def close_real_clients():
    _MODELS.clear()
    yield
    for provider in reversed(_MODELS):
        await provider.close()
    _MODELS.clear()


class ObservedAPI:
    """Record real requests, usage and rejections, without changing responses."""

    def __init__(self, provider, *, fast_limit=None):
        self.provider = provider
        self.fast_limit = fast_limit
        self.calls = []
        self.failures = []
        self.responses = []
        self.closed = 0

    async def capabilities(self, binding):
        caps = await self.provider.capabilities(binding)
        if binding == "fast" and self.fast_limit:
            return caps.model_copy(update={"max_input_tokens": self.fast_limit})
        return caps

    async def stream(self, request):
        purpose = request.metadata.get("purpose", "main")
        record = {
            "run_id": request.run_id,
            "image_count": sum(
                b.kind == "image" for m in request.messages for b in m.content
            ),
            "purpose": purpose,
            "request_id": request.request_id,
            "binding": request.model_binding,
            "characters": sum(len(m.model_dump_json()) for m in request.messages),
        }
        self.calls.append(record)
        stream = self.provider.stream(request)
        try:
            async for event in stream:
                if event.kind == ModelEventKind.COMPLETED:
                    self.responses.append((purpose, event.response))
                    record["usage"] = event.response.usage.model_dump(mode="json")
                    record["finish_reason"] = event.response.finish_reason
                    record["tool_names"] = [c.name for c in event.response.tool_calls]
                    if purpose == "conversation_summary":
                        record["summary_markers"] = {
                            code: code in event.response.text
                            for code in ["ORION-731", "LIME-409"]
                        }
                yield event
        except SageV2Error as exc:
            failure = {
                **record,
                "code": exc.info.code,
                "provider_code": exc.info.provider_code,
            }
            self.failures.append(failure)
            record.update(code=exc.info.code, provider_code=exc.info.provider_code)
            raise
        finally:
            await stream.aclose()
            self.closed += 1
            output = os.environ.get("SAGE_V2_LIVE_REPORT")
            if output:
                with Path(output).open("a") as log:
                    log.write(json.dumps(record, ensure_ascii=False) + "\n")


def text(value, role="user"):
    return ModelMessage(role=role, content=(TextBlock(text=value),))


def calculator():
    return ToolDefinition(
        name="add_numbers",
        description="Add two integers.",
        input_schema={
            "type": "object",
            "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
            "required": ["a", "b"],
            "additionalProperties": False,
        },
        side_effect_level=SideEffectLevel.NONE,
    )


@pytest.mark.asyncio
async def test_real_upstream_overflow_splits_summary_preserves_edge_facts_and_tool_once():
    api = ObservedAPI(real_provider())
    repetitions = int(os.environ.get("SAGE_V2_LIVE_OVERFLOW_REPETITIONS", "1200000"))
    source = (
        "必须保留的验收码为 ORION-731。以下是无关重复填充。\n"
        + (" x" * repetitions)
        + "\n必须保留的交付码为 LIME-409。"
    )
    historical = (text(source), text("记录已保存。", "assistant"))
    original_digest = hashlib.sha256(
        historical[0].model_dump_json().encode()
    ).hexdigest()
    current = "从历史取出验收码与交付码；必须只调用一次 add_numbers 计算19+23。最终只输出验收码|交付码|工具计算结果，不要其他内容。"

    class History(DefaultContextAssembler):
        async def initial_ledger(self, command, *, run_id=None):
            return (
                *historical,
                *(await super().initial_ledger(command, run_id=run_id)),
            )

    store = InMemoryConversationSummaryStore()
    assembler = History(
        budget=ContextBudget(max_input_tokens=128000, reserve_output_tokens=512),
        reducer=PersistentSummaryContextReducer(
            store,
            summarizer=ModelConversationSummarizer(api, timeout_seconds=180),
            summary_target_tokens=256,
            max_summary_calls=64,
        ),
    )
    runtime = ephemeral_runtime()
    handle = await runtime.start_run(
        StartRun(
            agent_id="real_overflow",
            input=(InputItem(role="user", content=(TextBlock(text=current),)),),
            config=RunConfig(max_steps=6, max_output_tokens=512),
            resolved_spec_hash="sha256:real-overflow",
            idempotency_key="real-overflow",
        ),
        CONTEXT,
    )
    tool = calculator()
    executions = []

    async def add(call, context):
        executions.append(call.tool_call_id)
        return ToolExecutionResult(
            tool_call_id=call.tool_call_id,
            operation_id=call.operation_id,
            content=(TextBlock(text=str(call.arguments["a"] + call.arguments["b"])),),
        )

    engine = AgentLoopEngine(
        runtime=runtime,
        model=api,
        context_assembler=assembler,
        tool_catalog=InMemoryToolCatalog((tool,)),
        tool_executor=InMemoryToolExecutor({tool.name: tool}, {tool.name: add}),
    )
    run = await engine.execute(handle.run_id, CONTEXT)
    result = await runtime.get_run_result(handle.run_id)
    assert run.state == RunState.COMPLETED, result
    assert len(executions) == 1
    assert {
        f["purpose"]
        for f in api.failures
        if f["code"] == "model.context_window_exceeded"
    } >= {"main", "conversation_summary"}
    assert all(
        f["provider_code"] in {"400", "413", "422"}
        for f in api.failures
        if f["code"] == "model.context_window_exceeded"
    )
    assert any(p == "conversation_summary" for p, _ in api.responses)
    final = [
        i
        for i in result.final_items
        if i.data.kind == "message" and i.status.value == "completed"
    ][-1]
    assert final.data.content[0].text.strip() == "ORION-731|LIME-409|42"
    assert (
        hashlib.sha256(historical[0].model_dump_json().encode()).hexdigest()
        == original_digest
    )
    saved = await store.get(
        assembler._summary_context_key(handle.run_id), session_id=handle.run_id
    )
    assert saved is not None
    assert "ORION-731" in saved.text and "LIME-409" in saved.text
    assert len(api.calls) <= 75


@pytest.mark.asyncio
@pytest.mark.parametrize("pressure", [False, True])
async def test_real_memory_query_retains_search_identity_after_compression(pressure):
    from sagents.v2.memory.plugins.recall_llm import LLMMemoryRecallQueryGenerator

    api = ObservedAPI(real_provider(), fast_limit=2000 if pressure else None)
    source = "请找出 ORION-731 项目上次约定的交付日期。\n" + (
        "背景说明：本项目需要查找交付日期，项目代号必须保留。" * 350 if pressure else ""
    )
    query = await LLMMemoryRecallQueryGenerator(
        api, language="zh", timeout_seconds=180
    ).generate(source, run_id="live_memory")
    assert "ORION" in query.upper() and "731" in query
    purposes = [r["purpose"] for r in api.calls]
    assert ("conversation_summary" in purposes) == pressure
    assert not api.failures


@pytest.mark.asyncio
@pytest.mark.parametrize("pressure", [False, True])
async def test_real_tool_selection_still_selects_required_tool_after_compression(
    pressure,
):
    from sagents.v2.tool.plugins.selection_llm import LLMToolSelectionPolicy
    from sagents.v2.tool.selection import (
        ToolSelectionConfig,
        ToolSelectionPrepareContext,
        ToolSelectionRequest,
    )

    api = ObservedAPI(real_provider(), fast_limit=2000 if pressure else None)
    tools = (
        calculator(),
        *(
            ToolDefinition(
                name=f"weather_{i}",
                description="只用于天气查询，不适合算数。" * (90 if pressure else 1),
                input_schema={"type": "object", "properties": {}},
            )
            for i in range(12)
        ),
    )
    messages = (text("只需要使用 add_numbers 计算19+23；不需要任何天气工具。"),)
    policy = LLMToolSelectionPolicy(
        ToolSelectionConfig(max_visible_tools=1, model_timeout_seconds=120)
    )
    await policy.prepare(
        ToolSelectionPrepareContext(
            run_id="live_selection",
            tools=tools,
            messages=messages,
            model=api,
            language="zh",
        )
    )
    selection = policy.select(
        ToolSelectionRequest(run_id="live_selection", tools=tools, messages=messages)
    )
    assert tuple(t.name for t in selection.tools) == ("add_numbers",)
    assert ("conversation_summary" in [r["purpose"] for r in api.calls]) == pressure
    assert not api.failures


@pytest.mark.asyncio
@pytest.mark.parametrize("pressure", [False, True])
async def test_real_completion_judge_retains_decision_contract_after_compression(
    pressure,
):
    from sagents.v2.agent.policy.plugins.judge import LLMContinuationJudge
    from sagents.v2.agent.policy.continuation import (
        ContinuationContext,
        ContinuationAction,
    )

    api = ObservedAPI(real_provider(), fast_limit=4000 if pressure else None)
    requirements = "请检查是否已回答用户的算术问题，正确结果是42。" + (
        "这是已经完成的算术任务，正确结果42，不能要求额外执行工具。" * 350
        if pressure
        else ""
    )
    decision = await LLMContinuationJudge(api, timeout_seconds=180).decide(
        ContinuationContext(
            run_id="live_judge",
            step_number=1,
            max_steps=8,
            response=ModelResponse(response_id="done", text="42", finish_reason="stop"),
            ledger=(text("19+23是多少？"), text("42", "assistant")),
            agent_system_requirements=requirements,
            language="zh",
        )
    )
    assert decision.action in {
        ContinuationAction.COMPLETE_RUN,
        ContinuationAction.COMPLETE_TURN,
    }, decision
    assert ("conversation_summary" in [r["purpose"] for r in api.calls]) == pressure
    assert not api.failures


@pytest.mark.asyncio
async def test_real_summary_output_truncation_increases_allowance_and_recovers():
    from sagents.v2.context import ContextReductionScope
    from sagents.v2.context.summary import SummarizationRequest

    class OutputLimit(ObservedAPI):
        async def stream(self, request):
            if not self.calls:
                request = request.model_copy(update={"max_output_tokens": 24})
            stream = super().stream(request)
            try:
                async for event in stream:
                    yield event
            finally:
                await stream.aclose()

    api = OutputLimit(real_provider())
    source = (
        text(
            "必须保留项目代号 ORION-731、交付日期2030年5月6日、验收码 LIME-409。" * 40
        ),
    )
    result = await ModelConversationSummarizer(api).summarize(
        SummarizationRequest(
            scope=ContextReductionScope(
                context_key="truncate", session_id="truncate", run_id="truncate"
            ),
            messages=source,
            target_tokens=256,
        )
    )
    assert len(api.responses) >= 2
    assert api.responses[0][1].finish_reason in {
        "length",
        "max_output_tokens",
        "max_tokens",
    }
    assert api.responses[-1][1].finish_reason == "stop"
    assert "ORION-731" in result and "LIME-409" in result
    assert api.closed == len(api.calls)


@pytest.mark.asyncio
async def test_real_stream_cancellation_preserves_previous_complete_checkpoint():
    from sagents.v2.context import ContextReductionScope

    store = InMemoryConversationSummaryStore()
    original = ObservedAPI(real_provider())
    reducer = PersistentSummaryContextReducer(
        store,
        summarizer=ModelConversationSummarizer(original),
        summary_target_tokens=256,
    )
    scope = ContextReductionScope(
        context_key="cancel", session_id="cancel", run_id="cancel", force=True
    )
    seed = (text("项目代码 ORION-731，交付码 LIME-409。" * 200), text("first request"))
    await reducer.reduce(seed, scope=scope)
    previous = await store.get("cancel")
    started = asyncio.Event()
    pause = asyncio.Event()

    class Cancellable(ObservedAPI):
        async def stream(self, request):
            stream = super().stream(request)
            try:
                async for event in stream:
                    if event.kind == ModelEventKind.TEXT_DELTA:
                        started.set()
                        await pause.wait()
                    yield event
            finally:
                await stream.aclose()

    api = Cancellable(real_provider())
    reducer.summarizer = ModelConversationSummarizer(api)
    extended = (
        *seed,
        text("新增已确认项目事实。" * 200, "assistant"),
        text("second request"),
    )
    task = asyncio.create_task(
        reducer.reduce(
            extended,
            ContextBudget(max_input_tokens=128000, max_messages=2),
            scope=scope,
        )
    )
    try:
        await asyncio.wait_for(started.wait(), 60)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert await store.get("cancel") == previous
    assert api.closed == len(api.calls) == 1
    assert extended[: len(seed)] == seed


@pytest.mark.asyncio
async def test_real_too_small_mandatory_judge_limit_stops_finitely_without_api_schema_error():
    from sagents.v2.agent.policy.plugins.judge import LLMContinuationJudge
    from sagents.v2.agent.policy.continuation import ContinuationContext

    api = ObservedAPI(real_provider(), fast_limit=2000)
    with pytest.raises(SageV2Error) as exc:
        await LLMContinuationJudge(api, timeout_seconds=120).decide(
            ContinuationContext(
                run_id="irreducible_judge",
                step_number=1,
                max_steps=8,
                response=ModelResponse(
                    response_id="r", text="42", finish_reason="stop"
                ),
                ledger=(text("19+23？"), text("42", "assistant")),
                language="zh",
            )
        )
    assert exc.value.info.code in {
        "context.summary_no_progress",
        "model.context_irreducible",
    }
    assert not api.failures
    assert len(api.calls) <= 7
    assert api.closed == len(api.calls)


@pytest.mark.asyncio
async def test_real_parallel_tool_batch_compression_keeps_receipts_and_exact_results():
    api = ObservedAPI(real_provider())
    runtime = ephemeral_runtime()
    request = "严格执行三步：第一步，在同一个响应里并行调用 read_record_a 和 read_record_b，各一次；第二步，读取结果后调用 confirm_codes 一次进行核验；第三步，只输出两个记录的验证码，用竖线分隔。任何工具都不得重复调用。"
    handle = await runtime.start_run(
        StartRun(
            agent_id="parallel_live",
            input=(InputItem(role="user", content=(TextBlock(text=request),)),),
            config=RunConfig(max_steps=8, max_output_tokens=512),
            resolved_spec_hash="sha256:parallel-live",
            idempotency_key="parallel-live",
        ),
        CONTEXT,
    )
    tools = (
        ToolDefinition(
            name="read_record_a",
            description="Read record A and its verification code.",
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            side_effect_level=SideEffectLevel.NONE,
        ),
        ToolDefinition(
            name="read_record_b",
            description="Read record B and its verification code.",
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            side_effect_level=SideEffectLevel.NONE,
        ),
        ToolDefinition(
            name="confirm_codes",
            description="Verify the two codes after both records were read.",
            input_schema={
                "type": "object",
                "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
                "required": ["a", "b"],
                "additionalProperties": False,
            },
            side_effect_level=SideEffectLevel.NONE,
        ),
    )
    executions = []

    async def read(call, context):
        executions.append(call.tool_name)
        await asyncio.sleep(0.05)
        value = (
            ("A 的验证码为 ALPHA-917。\n" + "无关历史记录。" * 1000)
            if call.tool_name == "read_record_a"
            else ("无关历史记录。" * 1000 + "\nB 的验证码为 BETA-462。")
        )
        return ToolExecutionResult(
            tool_call_id=call.tool_call_id,
            operation_id=call.operation_id,
            content=(TextBlock(text=value),),
        )

    async def confirm(call, context):
        executions.append(call.tool_name)
        assert call.arguments == {"a": "ALPHA-917", "b": "BETA-462"}
        assert set(executions) >= {"read_record_a", "read_record_b"}
        return ToolExecutionResult(
            tool_call_id=call.tool_call_id,
            operation_id=call.operation_id,
            content=(
                TextBlock(
                    text="核验成功，两个验证码都准确，所有步骤已经完成，请直接交付最终结果。"
                ),
            ),
        )

    store = InMemoryConversationSummaryStore()
    assembler = DefaultContextAssembler(
        budget=ContextBudget(max_input_tokens=4000),
        reducer=PersistentSummaryContextReducer(
            store,
            summarizer=ModelConversationSummarizer(api),
            summary_target_tokens=512,
        ),
    )
    engine = AgentLoopEngine(
        runtime=runtime,
        model=api,
        context_assembler=assembler,
        tool_catalog=InMemoryToolCatalog(tools),
        tool_executor=InMemoryToolExecutor(
            {t.name: t for t in tools},
            {"read_record_a": read, "read_record_b": read, "confirm_codes": confirm},
        ),
    )
    run = await engine.execute(handle.run_id, CONTEXT)
    result = await runtime.get_run_result(handle.run_id)
    assert run.state == RunState.COMPLETED, result
    assert sorted(executions) == ["confirm_codes", "read_record_a", "read_record_b"]
    main = [response for purpose, response in api.responses if purpose == "main"]
    assert {c.name for c in main[0].tool_calls} == {"read_record_a", "read_record_b"}
    assert any(purpose == "conversation_summary" for purpose, _ in api.responses)
    final = [
        i
        for i in result.final_items
        if i.data.kind == "message" and i.status.value == "completed"
    ][-1]
    assert final.data.content[0].text.strip() == "ALPHA-917|BETA-462"
    events = await runtime.session_store.read_events(handle.run_id)
    assert sum(e.type == "tool.call.succeeded" for e in events) == 3


@pytest.mark.asyncio
async def test_real_summary_survives_filesystem_restart_and_retains_raw_history(
    tmp_path,
):
    from sagents.v2.runtime.kernel import HarnessRuntime
    from sagents.v2.runtime.session.plugins.filesystem import FilesystemSessionStore
    from sagents.v2.context import (
        ContextReductionScope,
        SessionDerivedConversationSummaryStore,
    )
    from tests.sagents.v2.live.test_gpt_5_6_luna_scenarios import _complete

    api = ObservedAPI(real_provider())
    source = (
        text(
            "已确认验收码 ORION-731，交付码 LIME-409，这两个标识必须保留。"
            + "历史记录。" * 500
        ),
        text("我已记录。", "assistant"),
        text("保存这些约定，稍后会询问。"),
    )
    command = StartRun(
        agent_id="persist_live",
        input=tuple(InputItem(role=m.role, content=m.content) for m in source),
        config=RunConfig(max_steps=4),
        resolved_spec_hash="sha256:persist-live",
        idempotency_key="persist-live",
    )
    first = FilesystemSessionStore(tmp_path)
    handle = await HarnessRuntime(first).start_run(command, CONTEXT)
    scope = ContextReductionScope(
        context_key="persist_summary",
        session_id=handle.session_id,
        run_id=handle.run_id,
        force=True,
    )
    first_summary = SessionDerivedConversationSummaryStore(first)
    before = await PersistentSummaryContextReducer(
        first_summary,
        summarizer=ModelConversationSummarizer(api),
        summary_target_tokens=256,
    ).reduce(source, scope=scope)
    saved = await first_summary.get(scope.context_key, session_id=handle.session_id)
    accepted_command = await first.get_start_command(handle.run_id)
    assert accepted_command.input == command.input
    await first.close()
    second = FilesystemSessionStore(tmp_path)
    try:
        restored = SessionDerivedConversationSummaryStore(second)
        assert (
            await restored.get(scope.context_key, session_id=handle.session_id) == saved
        )
        assert await second.get_start_command(handle.run_id) == accepted_command
        calls_before = len(api.calls)
        after = await PersistentSummaryContextReducer(
            restored, summarizer=ModelConversationSummarizer(api)
        ).reduce(source, scope=scope.model_copy(update={"force": False}))
        assert after.messages == before.messages
        assert len(api.calls) == calls_before
        response = await _complete(
            api,
            messages=(
                *after.messages,
                text("根据历史，仅输出验收码|交付码，不要解释。"),
            ),
        )
        assert response.text.strip() == "ORION-731|LIME-409"
        assert await second.get_start_command(handle.run_id) == accepted_command
    finally:
        await second.close()


@pytest.mark.asyncio
async def test_real_recursive_summary_merge_retains_first_and_last_facts():
    from sagents.v2.context import ContextReductionScope
    from sagents.v2.context.summary import SummarizationRequest

    class SmallSummaryWindow(ObservedAPI):
        async def capabilities(self, binding):
            caps = await super().capabilities(binding)
            return caps.model_copy(update={"max_input_tokens": 16000})

    api = SmallSummaryWindow(real_provider())
    source = (
        "验收码 ORION-731，必须保留该事实。\n"
        + (" x" * 40000)
        + "\n交付码 LIME-409，必须保留该事实。"
    )
    result = await ModelConversationSummarizer(api).summarize(
        SummarizationRequest(
            scope=ContextReductionScope(
                context_key="merge_edges",
                session_id="merge_edges",
                run_id="merge_edges",
            ),
            messages=(text(source),),
            target_tokens=256,
        )
    )
    assert "ORION-731" in result and "LIME-409" in result
    assert len(api.calls) >= 7
    assert api.closed == len(api.calls)
    assert api.responses[0][1].usage.input_tokens >= 16000


@pytest.mark.asyncio
async def test_real_api_authentication_error_is_permanent_and_not_retried():
    from pydantic import SecretStr
    from sagents.v2.model import OpenAICompatibleModelProvider, ModelRequest
    from sagents.v2.runtime.credentials import CredentialMaterial
    from sagents.v2.model.recovery import collect_response, model_call_budget

    valid = real_provider()
    invalid = OpenAICompatibleModelProvider(
        valid.config,
        CredentialMaterial(
            credential_id="deliberately-invalid-test-key",
            secret=SecretStr("invalid-sage-real-acceptance-key"),
            source="acceptance-test",
        ),
    )
    _MODELS.append(invalid)
    api = ObservedAPI(invalid)
    request = ModelRequest(
        request_id="invalid_auth",
        run_id="invalid_auth",
        model_binding="primary",
        messages=(text("只输出42"),),
        max_output_tokens=32,
    )
    try:
        with model_call_budget():
            await collect_response(api, request)
    except SageV2Error as exc:
        assert exc.info.provider_code in {"401", "403"}
        assert not exc.info.retryable
        assert len(api.calls) == api.closed == 1
    else:
        pytest.xfail(
            "The configured upstream accepts a deliberately invalid API key; a natural 401 cannot be exercised on this endpoint. The HTTP gateway separately verifies permanent authentication rejection."
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", [401, 429, 503, "partial_stream"])
async def test_http_fault_gateway_retries_real_model_after_tool_without_reexecution(
    fault,
):
    """Controlled HTTP failures; successful responses come from the real API.

    The gateway is explicitly fault injection at the transport boundary, not a
    claim that an external provider happened to fail during the test.
    """
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import httpx
    from openai import AsyncOpenAI
    from sagents.v2.model import OpenAICompatibleModelProvider

    actual = real_provider()
    state = {"calls": [], "failures": 0, "forwarded": 0}
    target = actual.config.base_url.rstrip("/")
    desired = 1 if fault in {401, "partial_stream"} else 2

    class Gateway(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            payload = json.loads(body)
            state["calls"].append(payload)
            should_fail = (
                any(m.get("role") == "tool" for m in payload.get("messages", []))
                and state["failures"] < desired
            )
            if should_fail:
                state.setdefault("failed_messages", payload["messages"])
                state["failure_call_index"] = len(state["calls"])
            if should_fail and fault != "partial_stream":
                state["failures"] += 1
                response = json.dumps(
                    {
                        "error": {
                            "message": "Controlled HTTP gateway fault",
                            "code": "invalid_api_key"
                            if fault == 401
                            else (
                                "rate_limit_exceeded"
                                if fault == 429
                                else "server_error"
                            ),
                        }
                    }
                ).encode()
                self.send_response(fault)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)
                return
            path = self.path.removeprefix("/v1")
            with httpx.Client(timeout=120) as client:
                response = client.post(
                    target + path,
                    content=body,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": self.headers.get("Authorization", ""),
                    },
                )
            state["forwarded"] += 1
            content = response.content
            if should_fail:
                state["failures"] += 1
                prefix = []
                for line in content.splitlines(keepends=True):
                    prefix.append(line)
                    if line.startswith(b"data: "):
                        try:
                            value = json.loads(line[6:])
                        except (ValueError, TypeError):
                            continue
                        if any(
                            choice.get("delta", {}).get("content")
                            for choice in value.get("choices", [])
                        ):
                            break
                content = b"".join(prefix) + b"\n\n"
            self.send_response(response.status_code)
            self.send_header(
                "Content-Type",
                response.headers.get("content-type", "text/event-stream"),
            )
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Gateway)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = AsyncOpenAI(
        api_key=os.environ["SAGE_V2_LIVE_API_KEY"],
        base_url=f"http://127.0.0.1:{server.server_port}/v1",
        max_retries=0,
        timeout=120,
    )
    provider = OpenAICompatibleModelProvider(
        actual.config.model_copy(
            update={"base_url": f"http://127.0.0.1:{server.server_port}/v1"}
        ),
        client=client,
    )
    runtime = ephemeral_runtime()
    handle = await runtime.start_run(
        StartRun(
            agent_id="http_recovery",
            input=(
                InputItem(
                    role="user",
                    content=(
                        TextBlock(
                            text="必须只调用一次 add_numbers 计算19+23，随后只输出工具返回的结果。"
                        ),
                    ),
                ),
            ),
            config=RunConfig(max_steps=6, max_output_tokens=128),
            resolved_spec_hash="sha256:http-recovery",
            idempotency_key="http-recovery",
        ),
        CONTEXT,
    )
    tool = calculator()
    executions = []

    async def add(call, context):
        executions.append(call.tool_call_id)
        return ToolExecutionResult(
            tool_call_id=call.tool_call_id,
            operation_id=call.operation_id,
            content=(TextBlock(text="42"),),
        )

    engine = AgentLoopEngine(
        runtime=runtime,
        model=provider,
        tool_catalog=InMemoryToolCatalog((tool,)),
        tool_executor=InMemoryToolExecutor({tool.name: tool}, {tool.name: add}),
    )
    try:
        run = await engine.execute(handle.run_id, CONTEXT)
        assert run.state == (RunState.SUSPENDED if fault == 401 else RunState.COMPLETED)
        assert len(executions) == 1
        assert state["failures"] == desired
        assert state["failed_messages"] == state["calls"][-1]["messages"]
        events = await runtime.session_store.read_events(handle.run_id)
        retries = [e for e in events if e.type == "step.retry_scheduled"]
        assert len(retries) <= 2 * (
            engine._MAX_TRANSPARENT_PROVIDER_RETRIES
            + engine._MAX_TRANSPARENT_EMPTY_RESPONSE_RETRIES
        )
        assert all(e.data.error.retryable for e in retries)
        allowed = {
            "model.provider_transient",
            "model.stream_incomplete",
            "model.empty_semantic_response",
        }
        assert all(e.data.error.code in allowed for e in retries)
        assert all(
            0
            < e.data.error.metadata["transparent_retry_attempt"]
            <= e.data.error.metadata["transparent_retry_limit"]
            for e in retries
        )
        if fault == "partial_stream":
            assert (
                sum(e.data.error.code == "model.stream_incomplete" for e in retries)
                >= desired
            )
        elif fault != 401:
            assert (
                sum(e.data.error.provider_code == str(fault) for e in retries)
                >= desired
            )
        else:
            assert not any(e.data.error.provider_code == "401" for e in retries)
        report = os.environ.get("SAGE_V2_LIVE_REPORT")
        if report:
            with Path(report).open("a") as log:
                log.write(
                    json.dumps(
                        {
                            "scenario": "http_fault_gateway",
                            "fault": fault,
                            "source": "controlled_http_gateway",
                            "injected_failures": state["failures"],
                            "tool_executions": len(executions),
                            "retry_errors": [
                                {
                                    "code": e.data.error.code,
                                    "provider_code": e.data.error.provider_code,
                                }
                                for e in retries
                            ],
                        }
                    )
                    + "\n"
                )
        if fault != 401:
            result = await runtime.get_run_result(handle.run_id)
            final = [
                i
                for i in result.final_items
                if i.data.kind == "message" and i.status.value == "completed"
            ][-1]
            assert final.data.content[0].text.strip() == "42"
        else:
            assert len(state["calls"]) == state["failure_call_index"]
            assert any(e.type == "interaction.requested" for e in events)
    finally:
        await client.close()
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        await asyncio.to_thread(thread.join, 5)


@pytest.mark.asyncio
@pytest.mark.parametrize("latest_image", [False, True])
async def test_real_multimodal_compression_preserves_current_image_and_verified_old_image_facts(
    latest_image,
):
    import base64
    import struct
    import zlib
    from sagents.v2.contracts.items import ImageBlock
    from tests.sagents.v2.live.test_gpt_5_6_luna_scenarios import _complete

    def chunk(kind, data):
        return (
            struct.pack("!I", len(data))
            + kind
            + data
            + struct.pack("!I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + b"\xff\x00\x00" * 64 for _ in range(64))
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack("!2I5B", 64, 64, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
    image = ImageBlock(
        uri="data:image/png;base64," + base64.b64encode(png).decode(),
        mime_type="image/png",
    )
    api = ObservedAPI(real_provider())
    facts = TextBlock(
        text="项目代号 ORION-731，必须保留。" + "背景：这是已验收项目的历史说明。" * 800
    )
    if latest_image:
        source = (
            ModelMessage(role="user", content=(facts,)),
            text("记录已保存。", "assistant"),
            ModelMessage(
                role="user",
                content=(
                    TextBlock(
                        text="读取图片主要颜色，并结合历史项目代号，只输出颜色中文名|项目代号。"
                    ),
                    image,
                ),
            ),
        )
        first = await _complete(api, messages=source)
        assert first.text.strip() == "红色|ORION-731"
        ledger = source
    else:
        original = ModelMessage(
            role="user",
            content=(
                facts,
                TextBlock(text="查看图片，只输出主要颜色中文名|项目代号。"),
                image,
            ),
        )
        first = await _complete(api, messages=(original,))
        assert first.text.strip() == "红色|ORION-731"
        ledger = (
            original,
            text(first.text, "assistant"),
            text("根据已验证的记录，再次只输出图片主要颜色中文名|项目代号。"),
        )
    frozen = tuple(m.model_dump_json() for m in ledger)
    assembler = DefaultContextAssembler(
        budget=ContextBudget(max_input_tokens=2000),
        reducer=PersistentSummaryContextReducer(
            InMemoryConversationSummaryStore(),
            summarizer=ModelConversationSummarizer(api),
            summary_target_tokens=512,
        ),
    )
    assert first.usage.reported and first.usage.input_tokens >= 2000
    assembler.observe_usage("image_live", first.usage.input_tokens)
    projection = await assembler.prepare_messages(
        StartRun(
            agent_id="image_live",
            input=(InputItem(role="user", content=(TextBlock(text="检查历史"),)),),
            resolved_spec_hash="sha256:image-live",
            idempotency_key="image-live",
        ),
        ledger,
        run_id="image_live",
    )
    second = await _complete(api, messages=projection)
    assert second.text.strip() == "红色|ORION-731"
    assert tuple(m.model_dump_json() for m in ledger) == frozen
    assert sum(isinstance(b, ImageBlock) for m in projection for b in m.content) == int(
        latest_image
    )
    assert all(
        r["image_count"] == 0
        for r in api.calls
        if r["purpose"] == "conversation_summary"
    )
    assert any(r["purpose"] == "conversation_summary" for r in api.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("shared_context", [False, True])
async def test_real_concurrent_summaries_preserve_session_isolation_and_cas_winner(
    shared_context,
):
    from sagents.v2.context import ContextReductionScope

    api = ObservedAPI(real_provider())
    store = InMemoryConversationSummaryStore()
    reducer = PersistentSummaryContextReducer(
        store, summarizer=ModelConversationSummarizer(api), summary_target_tokens=256
    )
    first_source = (
        text("本会话的唯一项目标识为 ORION-731。" + "项目历史说明。" * 300),
        text("保留标识以供后续查询。"),
    )
    second_source = (
        first_source
        if shared_context
        else (
            text("本会话的唯一项目标识为 LIME-409。" + "项目历史说明。" * 300),
            text("保留标识以供后续查询。"),
        )
    )
    scope_a = ContextReductionScope(
        context_key="concurrent_a",
        session_id="concurrent_a",
        run_id="concurrent_a",
        force=True,
    )
    scope_b = (
        scope_a
        if shared_context
        else scope_a.model_copy(
            update={
                "context_key": "concurrent_b",
                "session_id": "concurrent_b",
                "run_id": "concurrent_b",
            }
        )
    )
    first, second = await asyncio.gather(
        reducer.reduce(first_source, scope=scope_a),
        reducer.reduce(second_source, scope=scope_b),
    )
    saved_a = await store.get(scope_a.context_key)
    saved_b = await store.get(scope_b.context_key)
    assert saved_a.revision == saved_b.revision == 1
    assert "ORION-731" in saved_a.text
    if shared_context:
        assert first.messages == second.messages
        assert saved_a == saved_b
    else:
        assert "LIME-409" in saved_b.text
        assert "ORION-731" not in saved_b.text
        assert "LIME-409" not in saved_a.text
    assert first.messages[-1] == first_source[-1]
    assert second.messages[-1] == second_source[-1]
    assert len(api.calls) == api.closed == 2

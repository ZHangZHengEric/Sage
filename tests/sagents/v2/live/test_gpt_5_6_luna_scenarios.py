from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from sagents.v2.model.contracts import ModelResponse

from sagents.v2.contracts.items import MessageItemData
from sagents.v2.model.provider import ModelProvider

import json
import os

import pytest
from pydantic import SecretStr

from sagents.v2.agent.engine import AgentLoopEngine
from sagents.v2.runtime.credentials import CredentialMaterial
from sagents.v2.model import (
    ModelCapabilities,
    ModelEventKind,
    ModelMessage,
    ModelRequest,
    OpenAICompatibleConfig,
    OpenAICompatibleModelProvider,
)
from sagents.v2.tool import (
    InMemoryToolCatalog,
    InMemoryToolExecutor,
    SideEffectLevel,
    ToolDefinition,
    ToolExecutionResult,
)
from sagents.v2.contracts.commands import InputItem, RunConfig, StartRun
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.contracts.run_state import RunState
from sagents.v2.testing.runtime import ephemeral_runtime


pytestmark = [pytest.mark.live, pytest.mark.timeout(90)]

API_KEY_ENV = "SAGE_V2_LIVE_API_KEY"
BASE_URL_ENV = "SAGE_V2_LIVE_BASE_URL"
MODEL_ENV = "SAGE_V2_LIVE_MODEL"
DEFAULT_BASE_URL = "http://34.143.184.13:18084/openai/v1"
DEFAULT_MODEL = "gpt-5.6-luna"

CAPABILITIES = ModelCapabilities(
    supports_streaming=True,
    supports_tools=True,
    supports_parallel_tool_calls=True,
    supports_reasoning=True,
    supports_multimodal_input=True,
    supports_structured_output=True,
    max_input_tokens=128_000,
    max_output_tokens=8_192,
)
CONTEXT = RequestContext(
    actor=ActorRef(
        principal_id="live_test_user",
        principal_type=PrincipalType.USER,
        tenant_id="live_test",
    )
)


def _live_provider() -> OpenAICompatibleModelProvider:
    api_key = os.environ.get(API_KEY_ENV)
    if not api_key:
        pytest.skip(f"set {API_KEY_ENV} to run live model acceptance tests")
    return OpenAICompatibleModelProvider(
        OpenAICompatibleConfig(
            provider_id="screenshot-openai-compatible",
            base_url=os.environ.get(BASE_URL_ENV, DEFAULT_BASE_URL),
            model=os.environ.get(MODEL_ENV, DEFAULT_MODEL),
            capabilities=CAPABILITIES,
            default_max_output_tokens=512,
            max_output_tokens_field="max_completion_tokens",
            timeout_seconds=60,
        ),
        CredentialMaterial(
            credential_id="live_model",
            secret=SecretStr(api_key),
            source="test-environment",
        ),
    )


async def _complete(provider, *, messages, response_schema=None, tools=()):
    completed = None
    deltas: list[str] = []
    async for event in provider.stream(
        ModelRequest(
            request_id="live_request",
            run_id="live_run",
            model_binding="primary",
            messages=messages,
            tools=tools,
            response_schema=response_schema,
            max_output_tokens=512,
        )
    ):
        if event.kind == ModelEventKind.TEXT_DELTA:
            deltas.append(event.delta or "")
        elif event.kind == ModelEventKind.COMPLETED:
            completed = event.response
    assert completed is not None
    assert "".join(deltas) == completed.text
    return completed


@pytest.mark.asyncio
async def test_live_chinese_instruction_and_stream_integrity():
    response = await _complete(
        _live_provider(),
        messages=(
            ModelMessage(
                role="system",
                content=(TextBlock(text="严格按用户要求回答，不要增加解释。"),),
            ),
            ModelMessage(
                role="user",
                content=(TextBlock(text="只输出整数：19 加 23 等于多少？"),),
            ),
        ),
    )
    assert response.text.strip() == "42"
    assert response.finish_reason in {"stop", "end_turn"}


@pytest.mark.asyncio
async def test_live_strict_structured_output():
    schema = {
        "type": "object",
        "properties": {
            "sum": {"type": "integer"},
            "ok": {"type": "boolean"},
        },
        "required": ["sum", "ok"],
        "additionalProperties": False,
    }
    response = await _complete(
        _live_provider(),
        messages=(
            ModelMessage(
                role="user",
                content=(TextBlock(text="计算 17 + 25，并按给定结构返回。"),),
            ),
        ),
        response_schema=schema,
    )
    assert json.loads(response.text) == {"sum": 42, "ok": True}


@pytest.mark.asyncio
async def test_live_agent_loop_calls_tool_and_completes_canonical_run():
    provider = _live_provider()
    runtime = ephemeral_runtime()
    handle = await runtime.start_run(
        StartRun(
            agent_id="live_calculator",
            input=(
                InputItem(
                    role="user",
                    content=(
                        TextBlock(
                            text=(
                                "必须调用 add_numbers 工具计算 19+23，"
                                "然后只输出工具返回的结果。"
                            )
                        ),
                    ),
                ),
            ),
            config=RunConfig(
                model_bindings={"primary": DEFAULT_MODEL},
                max_steps=4,
                max_output_tokens=512,
            ),
            resolved_spec_hash="sha256:live-calculator",
            idempotency_key="live-calculator-start",
        ),
        CONTEXT,
    )
    definition = ToolDefinition(
        name="add_numbers",
        description="Add two integers and return the exact integer result.",
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

    async def add(call, context):
        return ToolExecutionResult(
            tool_call_id=call.tool_call_id,
            operation_id=call.operation_id,
            content=(TextBlock(text=str(call.arguments["a"] + call.arguments["b"])),),
        )

    loop = AgentLoopEngine(
        runtime=runtime,
        model=provider,
        tool_catalog=InMemoryToolCatalog((definition,)),
        tool_executor=InMemoryToolExecutor(
            {definition.name: definition}, {definition.name: add}
        ),
    )
    run = await loop.execute(handle.run_id, CONTEXT)
    events = await runtime.session_store.read_events(handle.run_id)
    result = await runtime.get_run_result(handle.run_id)

    assert run.state == RunState.COMPLETED
    assert any(event.type == "tool.call.succeeded" for event in events)
    assert result.outcome == RunState.COMPLETED
    completed_messages = [
        item
        for item in result.final_items
        if item.data.kind == "message" and item.status.value == "completed"
    ]
    assert completed_messages
    assert cast(TextBlock, cast(MessageItemData, completed_messages[-1].data).content[0]).text.strip() == "42"


@pytest.mark.asyncio
@pytest.mark.parametrize("trigger", ["reported_limit", "injected_overflow"])
async def test_live_compresses_then_completes_tool_flow_without_replay(trigger):
    """Real primary and summary calls; injected errors exercise rare API paths."""
    from sagents.v2.context import (
        ContextBudget,
        DefaultContextAssembler,
        InMemoryConversationSummaryStore,
        PersistentSummaryContextReducer,
    )
    from sagents.v2.context.plugins.summarizer_model import ModelConversationSummarizer
    from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error

    real = _live_provider()
    requests, usages = [], []
    rejected = set()

    class ObservedProvider:
        async def capabilities(self, binding):
            return await real.capabilities(binding)

        async def stream(self, request):
            purpose = request.metadata.get("purpose", "main")
            requests.append(request)
            if trigger == "injected_overflow" and purpose not in rejected:
                rejected.add(purpose)
                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="model.context_window_exceeded",
                        category=ErrorCategory.VALIDATION,
                        message="Injected API context rejection",
                        safe_to_resume=True,
                    )
                )
            stream = real.stream(request)
            try:
                async for event in stream:
                    if event.kind == ModelEventKind.COMPLETED:
                        usages.append((purpose, cast('ModelResponse', event.response).usage))
                    yield event
            finally:
                await getattr(stream, 'aclose')()

    provider = ObservedProvider()
    history = (
        ModelMessage(
            role="user",
            content=(
                TextBlock(text="历史记录：项目验收已经通过，保留结论即可。" * 1500),
            ),
        ),
        ModelMessage(
            role="assistant", content=(TextBlock(text="已经保存项目验收结论。"),)
        ),
    )
    frozen = tuple(m.model_dump_json() for m in history)

    class History(DefaultContextAssembler):
        async def initial_ledger(self, command, *, run_id=None):
            return (*history, *(await super().initial_ledger(command, run_id=run_id)))

    store = InMemoryConversationSummaryStore()
    assembler = History(
        budget=ContextBudget(max_input_tokens=2000, reserve_output_tokens=512),
        reducer=PersistentSummaryContextReducer(
            store,
            summarizer=ModelConversationSummarizer(cast(ModelProvider, provider)),
            summary_target_tokens=256,
        ),
    )
    runtime = ephemeral_runtime()
    handle = await runtime.start_run(
        StartRun(
            agent_id="live_compression",
            input=(
                InputItem(
                    role="user",
                    content=(
                        TextBlock(
                            text="必须只调用一次 add_numbers 工具计算19+23，然后只输出工具结果。"
                        ),
                    ),
                ),
            ),
            config=RunConfig(max_steps=8, max_output_tokens=512),
            resolved_spec_hash="sha256:live-compression",
            idempotency_key="live-compression",
        ),
        CONTEXT,
    )
    definition = ToolDefinition(
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
    executions = []

    async def add(call, context):
        executions.append(call.tool_call_id)
        return ToolExecutionResult(
            tool_call_id=call.tool_call_id,
            operation_id=call.operation_id,
            content=(TextBlock(text=str(call.arguments["a"] + call.arguments["b"])),),
        )

    loop = AgentLoopEngine(
        runtime=runtime,
        model=cast(ModelProvider, provider),
        context_assembler=assembler,
        tool_catalog=InMemoryToolCatalog((definition,)),
        tool_executor=InMemoryToolExecutor(
            {definition.name: definition}, {definition.name: add}
        ),
    )
    run = await loop.execute(handle.run_id, CONTEXT)
    assert run.state == RunState.COMPLETED
    assert len(executions) == 1
    assert any(r.metadata.get("purpose") == "conversation_summary" for r in requests)
    assert any(
        m.metadata.get("context_summary")
        for r in requests
        if not r.metadata.get("purpose")
        for m in r.messages
    )
    assert tuple(m.model_dump_json() for m in history) == frozen
    assert any(u.reported for _, u in usages)
    if trigger == "reported_limit":
        assert next(u for p, u in usages if p == "main").input_tokens >= 1488
    else:
        assert rejected == {"main", "conversation_summary"}
    result = await runtime.get_run_result(handle.run_id)
    messages = [
        i
        for i in result.final_items
        if i.data.kind == "message" and i.status.value == "completed"
    ]
    assert cast(TextBlock, cast(MessageItemData, messages[-1].data).content[0]).text.strip() == "42"
    assert len(requests) <= 16

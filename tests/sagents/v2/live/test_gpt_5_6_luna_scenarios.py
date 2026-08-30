from __future__ import annotations

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
    assert completed_messages[-1].data.content[0].text.strip() == "42"

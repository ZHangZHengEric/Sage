import asyncio

import pytest

from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.errors import ErrorCategory, SageV2Error
from sagents.v2.model.contracts import (
    ModelEventKind,
    ModelMessage,
    ModelResponse,
    ModelStreamEvent,
    ModelToolCall,
)
from sagents.v2.testing.plugins.scripted_model import (
    ScriptedModelProvider,
    ScriptedModelStep,
)
from sagents.v2.tool import (
    DirectToolSelectionPolicy,
    LLMToolSelectionPolicy,
    LexicalToolSelectionPolicy,
    RecentToolSelectionPolicy,
    ToolDefinition,
    ToolSelectionConfig,
    ToolSelectionPrepareContext,
    ToolSelectionRequest,
)


def definition(name: str, description: str) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=description,
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
        },
    )


TOOLS = (
    definition("file_read", "read text from a file"),
    definition("send_email", "send an email message"),
    definition("weather_lookup", "look up a weather forecast"),
    definition("calendar_search", "search calendar events"),
    definition("tool_expand_tools", "activate more tools"),
)


class SlowModel:
    def stream(self, request):
        async def events():
            await asyncio.sleep(60)
            if False:
                yield None

        return events()


class SlowCompletionModel:
    def stream(self, request):
        async def events():
            yield ModelStreamEvent(kind=ModelEventKind.TEXT_DELTA, delta="{")
            await asyncio.sleep(0.03)
            yield completed_json('{"tools":["weather_lookup"]}')

        return events()


def request(run_id="run_1", *, messages=()) -> ToolSelectionRequest:
    return ToolSelectionRequest(run_id=run_id, tools=TOOLS, messages=messages)


def user_message(value: str) -> tuple[ModelMessage, ...]:
    return (ModelMessage(role="user", content=(TextBlock(text=value),)),)


def completed_json(value: str) -> ModelStreamEvent:
    return ModelStreamEvent(
        kind=ModelEventKind.COMPLETED,
        response=ModelResponse(
            response_id="selection_response", text=value, finish_reason="stop"
        ),
    )


def test_direct_policy_ignores_the_count_limit_and_exposes_all_tools():
    policy = DirectToolSelectionPolicy({"max_visible_tools": 1})
    result = policy.select(request())
    assert result.strategy == "direct"
    assert result.tools == TOOLS
    assert result.catalog_count == result.selected_count == len(TOOLS)


def test_bm25_policy_ranks_tool_metadata_without_a_model():
    policy = LexicalToolSelectionPolicy({"max_visible_tools": 3})
    result = policy.select(request(messages=user_message("read file text")))
    names = tuple(tool.name for tool in result.tools)
    assert names[0] == "tool_expand_tools"
    assert "file_read" in names
    assert len(names) == 3
    assert result.strategy == "lexical.bm25"
    assert result.hidden_tool_index


def test_recent_policy_puts_recent_calls_first_then_fills_the_limit():
    policy = RecentToolSelectionPolicy({"max_visible_tools": 3})
    messages = (
        ModelMessage(
            role="assistant",
            tool_calls=(
                ModelToolCall(
                    tool_call_id="call_1", name="send_email", arguments={}
                ),
                ModelToolCall(
                    tool_call_id="call_2", name="weather_lookup", arguments={}
                ),
            ),
        ),
    )
    result = policy.select(request(messages=messages))
    assert [tool.name for tool in result.tools[:2]] == [
        "weather_lookup",
        "send_email",
    ]
    assert len(result.tools) == 3


@pytest.mark.asyncio
async def test_llm_policy_prepares_once_and_uses_exact_valid_names():
    model = ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(completed_json('{"tools":["weather_lookup","file_read"]}'),)
            ),
        )
    )
    policy = LLMToolSelectionPolicy({"max_visible_tools": 3})
    messages = user_message("What is the weather, then save it?")
    await policy.prepare(
        ToolSelectionPrepareContext(
            run_id="run_1", tools=TOOLS, messages=messages, model=model
        )
    )
    result = policy.select(request(messages=messages))
    assert result.strategy == "llm"
    assert "weather_lookup" in {tool.name for tool in result.tools}
    assert len(model.requests) == 1
    assert model.requests[0].max_output_tokens is None


@pytest.mark.asyncio
async def test_llm_policy_reports_invalid_model_output():
    model = ScriptedModelProvider(
        (ScriptedModelStep(events=(completed_json("not json"),)),)
    )
    policy = LLMToolSelectionPolicy({"max_visible_tools": 2})
    messages = user_message("send an email")
    with pytest.raises(SageV2Error) as caught:
        await policy.prepare(
            ToolSelectionPrepareContext(
                run_id="run_1", tools=TOOLS, messages=messages, model=model
            )
        )

    assert caught.value.info.code == "tool_selection.model_output_invalid"
    assert caught.value.info.category == ErrorCategory.PROVIDER_PERMANENT


@pytest.mark.asyncio
async def test_llm_policy_accepts_an_explicit_empty_tool_selection():
    model = ScriptedModelProvider(
        (ScriptedModelStep(events=(completed_json('{"tools":[]}'),)),)
    )
    policy = LLMToolSelectionPolicy({"max_visible_tools": 2})
    messages = user_message("answer without using a tool")

    await policy.prepare(
        ToolSelectionPrepareContext(
            run_id="run_1", tools=TOOLS, messages=messages, model=model
        )
    )

    result = policy.select(request(messages=messages))
    assert result.strategy == "llm"
    assert len(result.tools) == 2


@pytest.mark.asyncio
async def test_llm_policy_rejects_a_nonempty_list_of_unknown_tools():
    model = ScriptedModelProvider(
        (ScriptedModelStep(events=(completed_json('{"tools":["missing"]}'),)),)
    )
    policy = LLMToolSelectionPolicy({"max_visible_tools": 2})

    with pytest.raises(SageV2Error) as caught:
        await policy.prepare(
            ToolSelectionPrepareContext(
                run_id="run_1", tools=TOOLS, model=model
            )
        )

    assert caught.value.info.code == "tool_selection.model_output_invalid"


@pytest.mark.asyncio
async def test_llm_policy_reports_timeout_without_changing_strategy():
    policy = LLMToolSelectionPolicy(
        {"max_visible_tools": 2, "model_timeout_seconds": 0.01}
    )
    messages = user_message("send an email")

    with pytest.raises(SageV2Error) as caught:
        await policy.prepare(
            ToolSelectionPrepareContext(
                run_id="run_1", tools=TOOLS, messages=messages, model=SlowModel()
            )
        )

    assert caught.value.info.code == "tool_selection.model_timeout"
    assert caught.value.info.category == ErrorCategory.PROVIDER_TRANSIENT
    assert caught.value.info.metadata["plugin_id"] == "sage.tool-selection.llm"


@pytest.mark.asyncio
async def test_llm_policy_timeout_only_bounds_the_first_stream_event():
    policy = LLMToolSelectionPolicy(
        {"max_visible_tools": 2, "model_timeout_seconds": 0.01}
    )
    messages = user_message("look up the weather")

    await policy.prepare(
        ToolSelectionPrepareContext(
            run_id="run_1",
            tools=TOOLS,
            messages=messages,
            model=SlowCompletionModel(),
        )
    )

    result = policy.select(request(messages=messages))
    assert "weather_lookup" in {tool.name for tool in result.tools}


def test_legacy_expert_parameters_are_removed_during_migration():
    config = ToolSelectionConfig.model_validate(
        {
            "max_visible_tools": 7,
            "candidate_top_k": 3,
            "context_turns": 9,
            "max_tool_schema_tokens": 1234,
        }
    )
    assert config.model_dump() == {
        "max_visible_tools": 7,
        "model_timeout_seconds": 6.0,
    }


def test_expansion_is_bounded_and_restorable():
    policy = LexicalToolSelectionPolicy({"max_visible_tools": 3})
    policy.select(request())
    unknown = policy.expand_tools(run_id="run_1", names=("missing",))
    expanded = policy.expand_tools(run_id="run_1", names=("send_email",))
    selected = policy.select(request())
    assert unknown["code"] == "tool_selection.unknown_tools"
    assert expanded == {"status": "success", "expanded_tools": ["send_email"]}
    assert "send_email" in {tool.name for tool in selected.tools}

    restored = LexicalToolSelectionPolicy({"max_visible_tools": 3})
    restored.restore_expanded_tools("run_1", policy.expanded_tools("run_1"))
    after_restore = restored.select(request())
    assert "send_email" in {tool.name for tool in after_restore.tools}

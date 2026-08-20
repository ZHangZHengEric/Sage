import asyncio
from types import SimpleNamespace

import pytest

from sagents.agent.tool_suggestion_agent import ToolSuggestionAgent
from sagents.prompts.tool_suggestion_prompts import tool_suggestion_template


class _DummyModel:
    async def astream(self, *args, **kwargs):  # pragma: no cover
        yield None


def _get_suggestions(monkeypatch: pytest.MonkeyPatch, response_content: str):
    agent = ToolSuggestionAgent(model=_DummyModel(), model_config={})
    captured = {}

    async def _fake_streaming(**kwargs):
        captured.update(kwargs)
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(delta=SimpleNamespace(content=response_content))
            ]
        )

    monkeypatch.setattr(agent, "_call_aux_llm_streaming", _fake_streaming)
    suggestions = asyncio.run(agent._get_tool_suggestions([], "test-session"))
    return captured, suggestions


def test_tool_suggestion_uses_and_parses_json_object_contract(monkeypatch):
    captured, suggestions = _get_suggestions(
        monkeypatch, '{"tool_ids": [1, "3", "invalid"]}'
    )

    assert captured["model_config_override"]["response_format"] == {
        "type": "json_object"
    }
    assert suggestions == [1, 3]


@pytest.mark.parametrize(
    "response_content",
    [
        "[1, 3]",
        '{"tool_ids": "1"}',
        '{"unexpected": [1, 3]}',
    ],
)
def test_tool_suggestion_rejects_responses_outside_object_contract(
    monkeypatch, response_content
):
    _, suggestions = _get_suggestions(monkeypatch, response_content)

    assert suggestions == []


def test_tool_suggestion_prompts_request_the_json_object_contract():
    for prompt_template in tool_suggestion_template.values():
        prompt = prompt_template.format(messages="request", available_tools_str="tools")
        assert '"tool_ids"' in prompt
        assert '{\n    "tool_ids": [1, 3, 5]\n}' in prompt

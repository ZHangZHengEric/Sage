import asyncio
from types import SimpleNamespace

from sagents.agent.plan_agent import PlanAgent
from sagents.agent.tool_suggestion_agent import ToolSuggestionAgent
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType


class _DummyModel:
    async def astream(self, *args, **kwargs):  # pragma: no cover
        yield None


def _multimodal_messages(image_payload: str):
    return [
        MessageChunk(
            role=MessageRole.USER.value,
            content=[
                {"type": "text", "text": "please inspect this image"},
                {"type": "image_url", "image_url": {"url": image_payload}},
            ],
            message_type=MessageType.USER_INPUT.value,
        ),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="done",
            message_type=MessageType.ASSISTANT_TEXT.value,
        ),
    ]


def test_tool_suggestion_prompt_redacts_multimodal_image_payloads(monkeypatch):
    agent = ToolSuggestionAgent(model=_DummyModel(), model_config={})
    image_payload = "data:image/png;base64," + ("a" * 10000)
    captured = {}

    async def _fake_prepare_llm_request_messages(**kwargs):
        captured["prompt"] = kwargs["extra_messages"][0].content
        return kwargs["extra_messages"]

    async def _fake_get_tool_suggestions(*args, **kwargs):
        return ["1"]

    monkeypatch.setattr(
        agent, "prepare_llm_request_messages", _fake_prepare_llm_request_messages
    )
    monkeypatch.setattr(agent, "_get_tool_suggestions", _fake_get_tool_suggestions)

    tool_manager = SimpleNamespace(
        list_tools_simplified=lambda lang: [
            {"name": "file_read", "description": "read"}
        ]
    )
    session_context = SimpleNamespace(
        agent_config={},
        effective_skill_manager=None,
        session_id="s1",
        tool_manager=tool_manager,
        get_language=lambda: "en",
    )

    result = asyncio.run(
        agent._analyze_tool_suggestions(
            _multimodal_messages(image_payload),
            session_context,  # pyright: ignore[reportArgumentType]
        )
    )

    assert result == ["file_read"]
    assert image_payload not in captured["prompt"]
    assert "data:image/png;base64" not in captured["prompt"]
    assert "<redacted data URL; base64_len=10000>" in captured["prompt"]


def test_plan_status_judge_prompt_redacts_multimodal_image_payloads(monkeypatch):
    agent = PlanAgent(model=_DummyModel(), model_config={})
    image_payload = "data:image/png;base64," + ("a" * 10000)
    captured = {}

    async def _fake_system_text(**kwargs):
        return "system prompt"

    async def _fake_llm_streaming(*args, **kwargs):
        captured["prompt"] = kwargs["messages"][0]["content"]
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content='{"plan_status": "start_execution"}')
                )
            ]
        )

    monkeypatch.setattr(agent, "prepare_llm_system_prompt_text", _fake_system_text)
    monkeypatch.setattr(agent, "_call_llm_streaming", _fake_llm_streaming)

    session_context = SimpleNamespace(
        session_id="s1",
        message_manager=SimpleNamespace(
            context_budget_manager=SimpleNamespace(budget_info={"active_budget": 3000})
        ),
        get_language=lambda: "en",
    )

    result = asyncio.run(
        agent._judge_plan_status(
            working_messages=_multimodal_messages(image_payload),
            session_context=session_context,  # pyright: ignore[reportArgumentType]
            tool_manager=None,
        )
    )

    assert result == "start_execution"
    assert image_payload not in captured["prompt"]
    assert "data:image/png;base64" not in captured["prompt"]
    assert "<redacted data URL; base64_len=10000>" in captured["prompt"]

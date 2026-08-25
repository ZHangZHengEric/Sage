import httpx
import pytest
from openai import BadRequestError

from sagents.utils.llm_request_utils import (
    DEFAULT_TOOL_REASONING_CONTENT,
    create_chat_completion_with_fallback,
    downgrade_image_url_parts_for_text_only_model,
    get_multimodal_support,
    prepare_chat_completion_messages,
    redact_base64_data_urls_in_value,
    sanitize_deepseek_tool_history,
    sanitize_model_request_kwargs,
    uses_max_completion_tokens,
)


@pytest.mark.parametrize(
    "model,expected",
    [
        ("gpt-5.4-mini", True),
        ("GPT-5", True),
        ("o1-preview", True),
        ("o3-mini", True),
        ("o4-mini", True),
        ("gpt-4o", False),
        ("gpt-4.1-mini", False),
        ("", False),
    ],
)
def test_uses_max_completion_tokens(model: str, expected: bool) -> None:
    assert uses_max_completion_tokens(model) is expected


def test_sanitize_maps_max_tokens_for_gpt5_family() -> None:
    out = sanitize_model_request_kwargs(
        {"max_tokens": 4096, "temperature": 0.7},
        model="gpt-5.4-mini",
    )
    assert out["max_completion_tokens"] == 4096
    assert "max_tokens" not in out
    assert "temperature" not in out


def test_sanitize_keeps_max_tokens_for_gpt4() -> None:
    out = sanitize_model_request_kwargs(
        {"max_tokens": 4096},
        model="gpt-4o",
    )
    assert out["max_tokens"] == 4096
    assert "max_completion_tokens" not in out


def test_sanitize_respects_existing_max_completion_tokens() -> None:
    out = sanitize_model_request_kwargs(
        {"max_tokens": 999, "max_completion_tokens": 100},
        model="o1-mini",
    )
    assert out["max_completion_tokens"] == 100
    assert "max_tokens" not in out


def test_sanitize_drops_empty_sampling_params() -> None:
    out = sanitize_model_request_kwargs(
        {
            "temperature": None,
            "top_p": "",
            "presence_penalty": None,
            "frequency_penalty": "",
            "max_tokens": None,
            "max_model_len": None,
        },
        model="gpt-4o",
    )
    assert out == {}


def test_redact_base64_data_url_replaces_payload() -> None:
    raw = "data:image/jpeg;base64," + ("x" * 100)
    out = redact_base64_data_urls_in_value(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "hi"},
                    {
                        "type": "image_url",
                        "image_url": {"url": raw},
                    },
                ],
            }
        ]
    )
    assert "xxxx" not in str(out)
    assert "base64_len=100" in out[0]["content"][1]["image_url"]["url"]


def test_get_multimodal_support_prefers_model_config() -> None:
    class Client:
        supports_multimodal = True

    assert (
        get_multimodal_support(
            client=Client(),
            model_config={"supports_multimodal": False},
        )
        is False
    )


def test_downgrade_image_url_parts_removes_images_for_text_only_model() -> None:
    image_url = "https://example.com/uploads/photo.png"
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "看这个："},
                {"type": "image_url", "image_url": {"url": image_url}},
                {"type": "text", "text": f"![photo.png]({image_url})"},
            ],
        }
    ]

    out, count = downgrade_image_url_parts_for_text_only_model(messages)

    assert count == 1
    assert out[0]["content"] == [
        {"type": "text", "text": f"看这个：![photo.png]({image_url})"}
    ]
    assert messages[0]["content"][1]["type"] == "image_url"


def test_downgrade_image_url_parts_adds_markdown_for_orphan_image() -> None:
    image_url = "https://example.com/uploads/photo.png?token=1"
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": image_url}},
            ],
        }
    ]

    out, count = downgrade_image_url_parts_for_text_only_model(messages)

    assert count == 1
    assert out[0]["content"] == [{"type": "text", "text": f"![photo.png]({image_url})"}]
    assert "image_url" not in str(out)


def test_sanitize_keeps_zero_sampling_values() -> None:
    out = sanitize_model_request_kwargs(
        {"temperature": 0, "top_p": 0.0, "presence_penalty": 0},
        model="gpt-4o",
    )
    assert out == {"temperature": 0, "top_p": 0.0, "presence_penalty": 0}


def test_sanitize_promotes_reasoning_effort_when_tool_choice_required() -> None:
    out = sanitize_model_request_kwargs(
        {
            "tools": [
                {"type": "function", "function": {"name": "do_work"}},
            ],
            "tool_choice": "required",
            "extra_body": {
                "reasoning_effort": "low",
                "_step_name": "main",
            },
        },
        model="gpt-5.4",
    )
    assert out["tool_choice"] == "required"
    assert out["reasoning_effort"] == "low"
    assert "reasoning_effort" not in out["extra_body"]
    assert out["extra_body"]["_step_name"] == "main"


def test_sanitize_promotes_reasoning_effort_tool_choice_required_case_insensitive() -> (
    None
):
    out = sanitize_model_request_kwargs(
        {
            "tools": [
                {"type": "function", "function": {"name": "do_work"}},
            ],
            "tool_choice": "  Required ",
            "extra_body": {"reasoning_effort": "minimal"},
        },
        model="gpt-5.4",
    )
    assert out["reasoning_effort"] == "minimal"
    assert "extra_body" not in out


def test_sanitize_gpt56_luna_drops_reasoning_effort_with_tools() -> None:
    out = sanitize_model_request_kwargs(
        {
            "tools": [
                {"type": "function", "function": {"name": "do_work"}},
            ],
            "extra_body": {
                "reasoning_effort": "medium",
                "_step_name": "main",
            },
        },
        model="gpt-5.6-luna",
    )

    assert "reasoning_effort" not in out
    assert out["extra_body"] == {"_step_name": "main"}
    assert out["tools"]


def test_sanitize_gpt56_luna_snapshot_drops_reasoning_effort_with_tools() -> None:
    out = sanitize_model_request_kwargs(
        {
            "tools": [
                {"type": "function", "function": {"name": "do_work"}},
            ],
            "reasoning_effort": "high",
        },
        model="gpt-5.6-luna-2026-07-09",
    )

    assert "reasoning_effort" not in out


def test_sanitize_gpt56_luna_keeps_reasoning_effort_without_tools() -> None:
    out = sanitize_model_request_kwargs(
        {"extra_body": {"reasoning_effort": "medium"}},
        model="gpt-5.6-luna",
    )

    assert out["reasoning_effort"] == "medium"


def test_sanitize_gpt56_sol_keeps_reasoning_effort_with_tools() -> None:
    out = sanitize_model_request_kwargs(
        {
            "tools": [
                {"type": "function", "function": {"name": "do_work"}},
            ],
            "extra_body": {"reasoning_effort": "medium"},
        },
        model="gpt-5.6-sol",
    )

    assert out["reasoning_effort"] == "medium"


def test_sanitize_keeps_deepseek_reasoning_effort_when_tools_present() -> None:
    out = sanitize_model_request_kwargs(
        {
            "tools": [
                {"type": "function", "function": {"name": "do_work"}},
            ],
            "extra_body": {"reasoning_effort": "max"},
        },
        model_config={"base_url": "https://api.deepseek.com"},
        model="deepseek-v4-flash",
    )
    assert out["extra_body"]["reasoning_effort"] == "max"


def test_sanitize_drops_tool_choice_for_deepseek_thinking() -> None:
    out = sanitize_model_request_kwargs(
        {
            "tools": [{"type": "function", "function": {"name": "do_work"}}],
            "tool_choice": "required",
            "extra_body": {
                "thinking": {"type": "enabled"},
                "reasoning_effort": "high",
            },
        },
        model_config={"base_url": "https://api.deepseek.com"},
        model="deepseek-v4-flash",
    )
    assert "tool_choice" not in out
    assert out["extra_body"]["reasoning_effort"] == "high"


def test_sanitize_keeps_tool_choice_for_deepseek_non_thinking() -> None:
    out = sanitize_model_request_kwargs(
        {
            "tools": [{"type": "function", "function": {"name": "do_work"}}],
            "tool_choice": "required",
            "extra_body": {"thinking": {"type": "disabled"}},
        },
        model_config={"base_url": "https://api.deepseek.com"},
        model="deepseek-v4-flash",
    )
    assert out["tool_choice"] == "required"


def test_sanitize_keeps_tool_choice_for_third_party_deepseek_slug() -> None:
    out = sanitize_model_request_kwargs(
        {
            "tools": [{"type": "function", "function": {"name": "do_work"}}],
            "tool_choice": "required",
            "extra_body": {"thinking": {"type": "enabled"}},
        },
        model_config={
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"
        },
        model="deepseek-v4-flash",
    )
    assert out["tool_choice"] == "required"


def test_deepseek_history_sanitizer_fills_missing_reasoning_without_mutation() -> (
    None
):
    messages = [
        {"role": "user", "content": "weather"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "legacy-call",
                    "type": "function",
                    "function": {"name": "weather", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "legacy-call", "content": "sunny"},
        {"role": "user", "content": "tomorrow?"},
    ]

    out = sanitize_deepseek_tool_history(
        messages,
        request_kwargs={"extra_body": {"thinking": {"type": "enabled"}}},
        model="deepseek-v4-flash",
        model_config={"base_url": "https://api.deepseek.com"},
    )

    assert out[1]["reasoning_content"] == DEFAULT_TOOL_REASONING_CONTENT
    assert out[1]["content"] == ""
    assert out[2] == messages[2]
    assert len(messages) == 4
    assert messages[1]["content"] is None
    assert "reasoning_content" not in messages[1]


def test_deepseek_history_sanitizer_also_fills_when_thinking_off() -> (
    None
):
    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "non-thinking-call",
                    "type": "function",
                    "function": {"name": "weather", "arguments": "{}"},
                }
            ],
        }
    ]

    out = sanitize_deepseek_tool_history(
        messages,
        request_kwargs={"extra_body": {"thinking": {"type": "disabled"}}},
        model="deepseek-v4-flash",
        model_config={"base_url": "https://api.deepseek.com"},
    )

    assert out[0]["reasoning_content"] == DEFAULT_TOOL_REASONING_CONTENT
    assert "reasoning_content" not in messages[0]


def test_prepare_deepseek_view_keeps_reasoning_when_current_thinking_is_off() -> None:
    messages = [
        {"role": "assistant", "reasoning_content": "need weather"},
        {"role": "assistant", "content": "Checking."},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "weather", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call-1", "content": "sunny"},
    ]

    out = prepare_chat_completion_messages(
        messages,
        request_kwargs={"extra_body": {"thinking": {"type": "disabled"}}},
        model="deepseek-v4-flash",
        model_config={"base_url": "https://api.deepseek.com"},
    )

    assert len(out) == 2
    assert out[0]["content"] == "Checking."
    assert out[0]["reasoning_content"] == "need weather"
    assert out[0]["tool_calls"][0]["id"] == "call-1"


def test_prepare_generic_view_strips_reasoning_and_keeps_visible_tool_text_once() -> None:
    messages = [
        {
            "role": "assistant",
            "content": "Checking.",
            "reasoning_content": "need weather",
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "weather", "arguments": "{}"},
                }
            ],
        }
    ]

    out = prepare_chat_completion_messages(
        messages,
        request_kwargs={},
        model="gpt-5.4",
        model_config={"base_url": "https://api.openai.com/v1"},
    )

    assert out == [
        {"role": "assistant", "content": "Checking."},
        {"role": "assistant", "tool_calls": messages[0]["tool_calls"]},
    ]
    assert messages[0]["reasoning_content"] == "need weather"


def test_prepare_minimax_view_replays_structured_reasoning_with_tool_turn() -> None:
    reasoning_details = [
        {"type": "reasoning.text", "text": "need weather"}
    ]
    messages = [
        {
            "role": "assistant",
            "reasoning_content": "need weather",
            "reasoning_details": reasoning_details,
        },
        {"role": "assistant", "content": "Checking."},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "weather", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call-1", "content": "sunny"},
    ]

    out = prepare_chat_completion_messages(
        messages,
        request_kwargs={"extra_body": {"reasoning_split": True}},
        model="MiniMax-M2.7",
        model_config={"base_url": "https://api.minimaxi.com/v1"},
    )

    assert len(out) == 2
    assert out[0]["content"] == "Checking."
    assert out[0]["reasoning_content"] == "need weather"
    assert out[0]["reasoning_details"] == reasoning_details
    assert out[0]["tool_calls"][0]["id"] == "call-1"
    assert messages[0]["reasoning_details"] == reasoning_details


def test_sanitize_keeps_reasoning_effort_when_tool_choice_auto() -> None:
    out = sanitize_model_request_kwargs(
        {
            "tool_choice": "auto",
            "extra_body": {"reasoning_effort": "low"},
        },
    )
    assert out["extra_body"]["reasoning_effort"] == "low"


def test_sanitize_keeps_reasoning_effort_when_model_is_unknown() -> None:
    out = sanitize_model_request_kwargs(
        {"extra_body": {"reasoning_effort": "high"}},
    )
    assert out["extra_body"]["reasoning_effort"] == "high"


def test_sanitize_drops_temperature_when_reasoning_effort_active_gpt54() -> None:
    out = sanitize_model_request_kwargs(
        {
            "temperature": 0.7,
            "top_p": 0.9,
            "extra_body": {"reasoning_effort": "low", "_step_name": "tool_suggestion"},
        },
        model="gpt-5.4",
    )
    assert "temperature" not in out
    assert "top_p" not in out
    assert out["reasoning_effort"] == "low"
    assert out["extra_body"] == {"_step_name": "tool_suggestion"}


def test_sanitize_drops_temperature_for_reasoning_model_without_effort() -> None:
    """gpt-5* 即使未带 reasoning_effort，也不接受自定义 temperature。"""
    out = sanitize_model_request_kwargs(
        {"temperature": 0.3, "max_tokens": 2000},
        model="gpt-5.4",
    )
    assert "temperature" not in out
    assert out["max_completion_tokens"] == 2000
    assert "max_tokens" not in out


def test_sanitize_drops_temperature_when_reasoning_effort_none() -> None:
    out = sanitize_model_request_kwargs(
        {
            "temperature": 0.7,
            "extra_body": {"reasoning_effort": "none"},
        },
        model="gpt-5.4",
    )
    assert "temperature" not in out


def test_sanitize_drops_temperature_and_keeps_reasoning_with_tools() -> None:
    out = sanitize_model_request_kwargs(
        {
            "tools": [
                {"type": "function", "function": {"name": "do_work"}},
            ],
            "temperature": 0.7,
            "tool_choice": "required",
            "extra_body": {"reasoning_effort": "low"},
        },
        model="gpt-5.4",
    )
    assert "temperature" not in out
    assert out["reasoning_effort"] == "low"
    assert "extra_body" not in out


def test_sanitize_keeps_temperature_for_gpt4_with_reasoning_effort_in_body() -> None:
    """非 OpenAI reasoning slug 不因 extra_body 误带 reasoning_effort 而去温度。"""
    out = sanitize_model_request_kwargs(
        {
            "temperature": 0.7,
            "extra_body": {"reasoning_effort": "low"},
        },
        model="gpt-4o",
    )
    assert out["temperature"] == 0.7


def _unknown_parameter_error(param: str) -> BadRequestError:
    request = httpx.Request("POST", "https://example.test/v1/chat/completions")
    response = httpx.Response(400, request=request)
    return BadRequestError(
        f"Error code: 400 - Unknown parameter: '{param}'.",
        response=response,
        body={
            "error": {
                "message": f"Unknown parameter: '{param}'.",
                "type": "invalid_request_error",
                "param": param,
                "code": "unknown_parameter",
            }
        },
    )


class _FakeCompletions:
    def __init__(self) -> None:
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        extra_body = kwargs.get("extra_body") or {}
        if "chat_template_kwargs" in extra_body:
            raise _unknown_parameter_error("chat_template_kwargs")
        if "enable_thinking" in extra_body:
            raise _unknown_parameter_error("enable_thinking")
        return {"ok": True, "kwargs": kwargs}


class _FakeClient:
    def __init__(self) -> None:
        self.chat = type("Chat", (), {"completions": _FakeCompletions()})()


@pytest.mark.asyncio
async def test_create_chat_completion_drops_unknown_extra_body_params() -> None:
    client = _FakeClient()
    observed = []

    response = await create_chat_completion_with_fallback(
        client,
        model="gpt-4o",
        messages=[{"role": "user", "content": "hi"}],
        request_observer=observed.append,
        stream=True,
        extra_body={
            "_step_name": "compact",
            "chat_template_kwargs": {"enable_thinking": False},
            "enable_thinking": False,
            "thinking": {"type": "disabled"},
        },
    )

    assert response["ok"] is True
    assert len(client.chat.completions.calls) == 3
    assert observed == client.chat.completions.calls
    assert "chat_template_kwargs" in observed[0]["extra_body"]
    assert "chat_template_kwargs" not in observed[1]["extra_body"]
    assert "enable_thinking" not in observed[-1]["extra_body"]
    assert "chat_template_kwargs" not in response["kwargs"]["extra_body"]
    assert "enable_thinking" not in response["kwargs"]["extra_body"]
    assert response["kwargs"]["extra_body"]["thinking"] == {"type": "disabled"}


@pytest.mark.asyncio
async def test_create_chat_completion_does_not_drop_protected_output_limit() -> None:
    class RejectMaxTokensCompletions:
        def __init__(self) -> None:
            self.calls = []

        async def create(self, **kwargs):
            self.calls.append(kwargs)
            raise _unknown_parameter_error("max_tokens")

    completions = RejectMaxTokensCompletions()
    client = type(
        "Client",
        (),
        {"chat": type("Chat", (), {"completions": completions})()},
    )()

    with pytest.raises(BadRequestError):
        await create_chat_completion_with_fallback(
            client,
            model="gpt-4o",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=4096,
            protected_request_parameters=("max_tokens", "max_completion_tokens"),
        )

    assert len(completions.calls) == 1
    assert completions.calls[0]["max_tokens"] == 4096


@pytest.mark.asyncio
async def test_create_chat_completion_maps_retired_official_deepseek_alias() -> None:
    client = _FakeClient()

    response = await create_chat_completion_with_fallback(
        client,
        model="deepseek-chat",
        messages=[{"role": "user", "content": "hi"}],
        model_config={"base_url": "https://api.deepseek.com"},
    )

    assert response["kwargs"]["model"] == "deepseek-v4-flash"


@pytest.mark.asyncio
async def test_request_observer_sees_actual_deepseek_tool_history() -> None:
    client = _FakeClient()
    observed = []
    messages = [
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "inspect", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call-1", "content": "ok"},
    ]

    await create_chat_completion_with_fallback(
        client,
        model="deepseek-v4-flash",
        messages=messages,
        model_config={"base_url": "https://api.deepseek.com"},
        request_observer=observed.append,
        tools=[{"type": "function", "function": {"name": "inspect"}}],
        extra_body={"thinking": {"type": "enabled"}},
    )

    assert len(observed) == 1
    assert observed[0] == client.chat.completions.calls[0]
    assert observed[0]["messages"][0]["content"] == ""
    assert (
        observed[0]["messages"][0]["reasoning_content"]
        == DEFAULT_TOOL_REASONING_CONTENT
    )
    assert "reasoning_content" not in messages[0]


@pytest.mark.asyncio
async def test_create_chat_completion_keeps_third_party_deepseek_alias() -> None:
    client = _FakeClient()

    response = await create_chat_completion_with_fallback(
        client,
        model="deepseek-chat",
        messages=[{"role": "user", "content": "hi"}],
        model_config={"base_url": "https://openrouter.ai/api/v1"},
    )

    assert response["kwargs"]["model"] == "deepseek-chat"


@pytest.mark.asyncio
async def test_create_chat_completion_prepares_openai_messages_and_effort() -> None:
    client = _FakeClient()
    tool_calls = [
        {
            "id": "call-1",
            "type": "function",
            "function": {"name": "weather", "arguments": "{}"},
        }
    ]

    response = await create_chat_completion_with_fallback(
        client,
        model="gpt-5.4",
        messages=[
            {
                "role": "assistant",
                "content": "Checking.",
                "reasoning_content": "need weather",
                "tool_calls": tool_calls,
            }
        ],
        tools=[{"type": "function", "function": {"name": "weather"}}],
        extra_body={"reasoning_effort": "medium"},
    )

    assert response["kwargs"]["reasoning_effort"] == "medium"
    assert "extra_body" not in response["kwargs"]
    assert response["kwargs"]["messages"] == [
        {"role": "assistant", "content": "Checking."},
        {"role": "assistant", "tool_calls": tool_calls},
    ]


@pytest.mark.asyncio
async def test_create_chat_completion_removes_image_urls_when_model_is_text_only() -> (
    None
):
    client = _FakeClient()
    image_url = "https://example.com/uploads/photo.png"

    response = await create_chat_completion_with_fallback(
        client,
        model="text-only-model",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "看这个："},
                    {"type": "image_url", "image_url": {"url": image_url}},
                    {"type": "text", "text": f"![photo.png]({image_url})"},
                ],
            }
        ],
        model_config={"supports_multimodal": False},
        stream=True,
    )

    sent_messages = response["kwargs"]["messages"]
    assert sent_messages[0]["content"] == [
        {"type": "text", "text": f"看这个：![photo.png]({image_url})"}
    ]
    assert "image_url" not in str(sent_messages)


@pytest.mark.asyncio
async def test_create_chat_completion_keeps_image_urls_when_model_supports_images() -> (
    None
):
    client = _FakeClient()
    image_part = {
        "type": "image_url",
        "image_url": {"url": "https://example.com/uploads/photo.png"},
    }

    response = await create_chat_completion_with_fallback(
        client,
        model="vision-model",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "看这个："},
                    image_part,
                ],
            }
        ],
        model_config={"supports_multimodal": True},
        stream=True,
    )

    assert response["kwargs"]["messages"][0]["content"][1] == image_part

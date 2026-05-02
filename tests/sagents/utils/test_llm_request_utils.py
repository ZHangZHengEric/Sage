import pytest

from sagents.utils.llm_request_utils import (
    redact_base64_data_urls_in_value,
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
    assert out["temperature"] == 0.7


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


def test_sanitize_keeps_zero_sampling_values() -> None:
    out = sanitize_model_request_kwargs(
        {"temperature": 0, "top_p": 0.0, "presence_penalty": 0},
        model="gpt-4o",
    )
    assert out == {"temperature": 0, "top_p": 0.0, "presence_penalty": 0}


def test_sanitize_strips_reasoning_effort_when_tool_choice_required() -> None:
    out = sanitize_model_request_kwargs(
        {
            "tool_choice": "required",
            "extra_body": {
                "reasoning_effort": "low",
                "_step_name": "main",
            },
        },
        model="gpt-5.4",
    )
    assert out["tool_choice"] == "required"
    assert "reasoning_effort" not in out["extra_body"]
    assert out["extra_body"]["_step_name"] == "main"


def test_sanitize_strips_reasoning_effort_tool_choice_required_case_insensitive() -> None:
    out = sanitize_model_request_kwargs(
        {
            "tool_choice": "  Required ",
            "extra_body": {"reasoning_effort": "minimal"},
        },
    )
    assert "reasoning_effort" not in out["extra_body"]


def test_sanitize_keeps_reasoning_effort_when_tool_choice_auto() -> None:
    out = sanitize_model_request_kwargs(
        {
            "tool_choice": "auto",
            "extra_body": {"reasoning_effort": "low"},
        },
    )
    assert out["extra_body"]["reasoning_effort"] == "low"


def test_sanitize_keeps_reasoning_effort_when_no_tool_choice() -> None:
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
    assert out["extra_body"]["reasoning_effort"] == "low"


def test_sanitize_keeps_temperature_when_reasoning_effort_none() -> None:
    out = sanitize_model_request_kwargs(
        {
            "temperature": 0.7,
            "extra_body": {"reasoning_effort": "none"},
        },
        model="gpt-5.4",
    )
    assert out["temperature"] == 0.7


def test_sanitize_keeps_temperature_after_tool_choice_strips_reasoning() -> None:
    out = sanitize_model_request_kwargs(
        {
            "temperature": 0.7,
            "tool_choice": "required",
            "extra_body": {"reasoning_effort": "low"},
        },
        model="gpt-5.4",
    )
    assert out["temperature"] == 0.7
    assert "reasoning_effort" not in out["extra_body"]


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

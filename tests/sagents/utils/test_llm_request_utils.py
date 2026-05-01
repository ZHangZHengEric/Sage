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

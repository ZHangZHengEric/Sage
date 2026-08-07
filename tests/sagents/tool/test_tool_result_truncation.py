import pytest

from sagents.context.messages.message_manager import MessageManager
from sagents.tool.tool_manager import (
    MAX_TOOL_RESULT_TOKENS,
    MAX_TOOL_RESULT_TOKENS_ENV,
    _truncate_result,
    get_max_tool_result_tokens,
)


def test_tool_result_token_limit_defaults_to_12000(monkeypatch):
    monkeypatch.delenv(MAX_TOOL_RESULT_TOKENS_ENV, raising=False)

    assert get_max_tool_result_tokens() == MAX_TOOL_RESULT_TOKENS == 12000


def test_tool_result_token_limit_uses_environment(monkeypatch):
    monkeypatch.setenv(MAX_TOOL_RESULT_TOKENS_ENV, "24000")

    assert get_max_tool_result_tokens() == 24000


@pytest.mark.parametrize("value", ["", "invalid", "0", "-1"])
def test_tool_result_token_limit_falls_back_for_invalid_values(monkeypatch, value):
    monkeypatch.setenv(MAX_TOOL_RESULT_TOKENS_ENV, value)

    assert get_max_tool_result_tokens() == MAX_TOOL_RESULT_TOKENS


def test_truncate_result_uses_environment_limit(monkeypatch):
    monkeypatch.setenv(MAX_TOOL_RESULT_TOKENS_ENV, "4")
    monkeypatch.setattr(
        MessageManager,
        "calculate_str_token_length",
        staticmethod(lambda value: len(value)),
    )
    monkeypatch.setattr(
        MessageManager,
        "get_dynamic_token_ratio",
        staticmethod(lambda: 1.0),
    )

    result = _truncate_result("abcdefghij")

    assert result.startswith("abcd\n\n[Result truncated]")
    assert "exceeds the 4 token limit" in result

from sagents.utils.completion_mode import (
    TaskCompletionMode,
    get_task_completion_mode,
    is_llm_judge_mode,
    is_no_tool_call_mode,
    is_turn_status_mode,
)


def _clear_completion_env(monkeypatch):
    monkeypatch.delenv("SAGE_TASK_COMPLETION_MODE", raising=False)
    monkeypatch.delenv("SAGE_COMPLETE_ON_NO_TOOL_CALL", raising=False)
    monkeypatch.delenv("SAGE_AGENT_STATUS_PROTOCOL_ENABLED", raising=False)


def test_default_completion_mode_is_turn_status(monkeypatch):
    _clear_completion_env(monkeypatch)

    assert get_task_completion_mode() == TaskCompletionMode.TURN_STATUS
    assert is_turn_status_mode() is True


def test_enum_no_tool_call_mode(monkeypatch):
    _clear_completion_env(monkeypatch)
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "no_tool_call")

    assert get_task_completion_mode() == TaskCompletionMode.NO_TOOL_CALL
    assert is_no_tool_call_mode() is True


def test_enum_llm_judge_mode(monkeypatch):
    _clear_completion_env(monkeypatch)
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "llm_judge")

    assert get_task_completion_mode() == TaskCompletionMode.LLM_JUDGE
    assert is_llm_judge_mode() is True


def test_enum_wins_over_legacy_booleans(monkeypatch):
    _clear_completion_env(monkeypatch)
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "turn_status")
    monkeypatch.setenv("SAGE_COMPLETE_ON_NO_TOOL_CALL", "true")
    monkeypatch.setenv("SAGE_AGENT_STATUS_PROTOCOL_ENABLED", "false")

    assert get_task_completion_mode() == TaskCompletionMode.TURN_STATUS


def test_legacy_no_tool_call_fallback(monkeypatch):
    _clear_completion_env(monkeypatch)
    monkeypatch.setenv("SAGE_COMPLETE_ON_NO_TOOL_CALL", "true")

    assert get_task_completion_mode() == TaskCompletionMode.NO_TOOL_CALL


def test_legacy_status_protocol_disabled_fallback(monkeypatch):
    _clear_completion_env(monkeypatch)
    monkeypatch.setenv("SAGE_AGENT_STATUS_PROTOCOL_ENABLED", "false")

    assert get_task_completion_mode() == TaskCompletionMode.LLM_JUDGE

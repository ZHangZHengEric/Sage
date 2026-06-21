from sagents.utils.completion_mode import (
    TaskCompletionMode,
    get_task_completion_mode,
    is_llm_judge_mode,
    is_no_tool_call_mode,
    is_turn_status_mode,
)


def _clear_completion_env(monkeypatch):
    monkeypatch.delenv("SAGE_TASK_COMPLETION_MODE", raising=False)


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


def test_invalid_completion_mode_falls_back_to_turn_status(monkeypatch):
    _clear_completion_env(monkeypatch)
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "not-a-mode")

    assert get_task_completion_mode() == TaskCompletionMode.TURN_STATUS

from sagents.agent.tool_suggestion_agent import get_tool_suggestion_direct_threshold


def test_tool_suggestion_direct_threshold_defaults_to_15(monkeypatch):
    monkeypatch.delenv("SAGE_TOOL_SUGGESTION_DIRECT_THRESHOLD", raising=False)

    assert get_tool_suggestion_direct_threshold() == 15


def test_tool_suggestion_direct_threshold_uses_env(monkeypatch):
    monkeypatch.setenv("SAGE_TOOL_SUGGESTION_DIRECT_THRESHOLD", "8")

    assert get_tool_suggestion_direct_threshold() == 8


def test_tool_suggestion_direct_threshold_invalid_env_falls_back(monkeypatch):
    monkeypatch.setenv("SAGE_TOOL_SUGGESTION_DIRECT_THRESHOLD", "many")

    assert get_tool_suggestion_direct_threshold() == 15


def test_tool_suggestion_direct_threshold_negative_env_falls_back(monkeypatch):
    monkeypatch.setenv("SAGE_TOOL_SUGGESTION_DIRECT_THRESHOLD", "-1")

    assert get_tool_suggestion_direct_threshold() == 15

from types import SimpleNamespace

import pytest

from common.services import chat_service


@pytest.mark.parametrize("desktop_mode", [False, True])
def test_skill_tool_injection_only_adds_registered_execution_tool(
    monkeypatch, desktop_mode
):
    request = SimpleNamespace(
        available_skills=["example-skill"],
        available_tools=[],
    )
    monkeypatch.setattr(chat_service, "_is_desktop_mode", lambda: desktop_mode)

    chat_service._inject_skill_tools(request)

    assert "execute_shell_command" in request.available_tools
    assert "execute_python_code" not in request.available_tools
    assert "execute_javascript_code" not in request.available_tools

import json

from common.services.chat_service import _sandbox_approval_event_from_tool_result


def test_sandbox_approval_event_from_shell_tool_result():
    result = {
        "type": "tool_result",
        "session_id": "session-demo",
        "metadata": {"tool_name": "execute_shell_command"},
        "content": json.dumps(
            {
                "success": False,
                "error_code": "SAFETY_BLOCKED",
                "command": "git push origin main",
                "policy_action": "ask",
                "policy_category": "git_remote_write",
                "policy_reason": "git push changes remote state",
                "policy_approval_mode": "on-request",
                "approval_id": "shapproval_demo",
                "approval_expires_at": "2026-06-24T10:00:00Z",
                "hint": "Ask the user for confirmation before retrying.",
            }
        ),
    }

    event = _sandbox_approval_event_from_tool_result(
        result,
        session_id="session-fallback",
    )

    assert event == {
        "type": "sandbox_approval_requested",
        "role": "system",
        "content": "git push changes remote state",
        "session_id": "session-demo",
        "approval_id": "shapproval_demo",
        "command": "git push origin main",
        "category": "git_remote_write",
        "reason": "git push changes remote state",
        "approval_mode": "on-request",
        "expires_at": "2026-06-24T10:00:00Z",
        "hint": "Ask the user for confirmation before retrying.",
        "tool_name": "execute_shell_command",
    }

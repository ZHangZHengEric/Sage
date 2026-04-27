"""turn_status 工具的轻量单测：校验入参、返回结构与描述。"""
import asyncio

from sagents.tool.impl.turn_status_tool import TurnStatusTool


def test_turn_status_accepts_terminal_status():
    tool = TurnStatusTool()
    out = asyncio.run(tool.turn_status(status="task_done", note="ok", session_id="s1"))
    assert out["success"] is True
    assert out["status"] == "success"
    assert out["should_end"] is True


def test_turn_status_continue_work_does_not_end():
    tool = TurnStatusTool()
    out = asyncio.run(tool.turn_status(status="continue_work", note="more work", session_id="s1"))
    assert out["success"] is True
    assert out["status"] == "success"
    assert out["should_end"] is False


def test_turn_status_rejects_invalid_status():
    tool = TurnStatusTool()
    out = asyncio.run(tool.turn_status(status="done", session_id="s1"))
    assert out.get("success") is False
    assert out["error_code"] == "INVALID_ARGUMENT"


def test_turn_status_description_covers_user_questions():
    spec = TurnStatusTool.turn_status._tool_spec
    zh_desc = spec.description_i18n["zh"]
    en_desc = spec.description_i18n["en"]

    assert "向用户提问" in zh_desc
    assert "status=need_user_input" in zh_desc
    assert "continue_work" in zh_desc
    assert "requesting confirmation" in en_desc

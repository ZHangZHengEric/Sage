"""finish_turn 工具的轻量单测：仅校验入参与返回结构。"""
import asyncio

from sagents.tool.impl.finish_turn_tool import FinishTurnTool


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if not asyncio.iscoroutine(coro) else asyncio.run(coro)


def test_finish_turn_accepts_valid_reason():
    tool = FinishTurnTool()
    out = asyncio.run(tool.finish_turn(reason="task_done", note="ok", session_id="s1"))
    assert out["success"] is True
    assert out["reason"] == "task_done"
    assert out["note"] == "ok"


def test_finish_turn_rejects_invalid_reason():
    tool = FinishTurnTool()
    out = asyncio.run(tool.finish_turn(reason="done", session_id="s1"))
    assert out.get("success") is False
    assert out["error_code"] == "INVALID_ARGUMENT"

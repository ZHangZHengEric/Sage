"""turn_status 工具的轻量单测：校验入参、返回结构与描述。"""
import asyncio
from types import SimpleNamespace

from common.schemas.goal import GoalStatus, SessionGoal
from sagents.tool.impl import turn_status_tool
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


def test_turn_status_task_done_completes_active_goal(monkeypatch):
    goal = SessionGoal(
        objective="Ship the runtime goal contract",
        status=GoalStatus.ACTIVE,
        created_at=1.0,
        updated_at=1.0,
    )

    class _FakeSession:
        def get_goal(self):
            return goal

        def complete_goal(self):
            goal.status = GoalStatus.COMPLETED
            goal.completed_at = 2.0
            goal.updated_at = 2.0
            return goal

    monkeypatch.setattr(
        turn_status_tool,
        "get_global_session_manager",
        lambda: SimpleNamespace(get_live_session=lambda session_id: _FakeSession()),
    )

    tool = TurnStatusTool()
    out = asyncio.run(tool.turn_status(status="task_done", note="ok", session_id="s1"))
    assert out["should_end"] is True
    assert out["goal"]["status"] == "completed"
    assert out["goal"]["objective"] == "Ship the runtime goal contract"
    assert out["goal_outcome"]["action"] == "completed"
    assert out["goal_outcome"]["reason"] == "ok"


def test_turn_status_need_user_input_pauses_active_goal(monkeypatch):
    goal = SessionGoal(
        objective="Collect release confirmation",
        status=GoalStatus.ACTIVE,
        created_at=1.0,
        updated_at=1.0,
    )

    class _FakeSession:
        def get_goal(self):
            return goal

        def pause_goal(self, reason=None):
            goal.status = GoalStatus.PAUSED
            goal.paused_reason = reason
            goal.updated_at = 3.0
            return goal

    monkeypatch.setattr(
        turn_status_tool,
        "get_global_session_manager",
        lambda: SimpleNamespace(get_live_session=lambda session_id: _FakeSession()),
    )

    tool = TurnStatusTool()
    out = asyncio.run(
        tool.turn_status(
            status="need_user_input",
            note="waiting for deployment approval",
            session_id="s1",
        )
    )
    assert out["should_end"] is True
    assert out["goal"]["status"] == "paused"
    assert out["goal"]["paused_reason"] == "waiting for deployment approval"
    assert out["goal_outcome"]["action"] == "paused"
    assert out["goal_outcome"]["reason"] == "waiting for deployment approval"


def test_turn_status_continue_work_reactivates_paused_goal(monkeypatch):
    goal = SessionGoal(
        objective="Resume the rollout",
        status=GoalStatus.PAUSED,
        created_at=1.0,
        updated_at=1.0,
        paused_reason="waiting_for_user_input",
    )

    class _FakeSession:
        def get_goal(self):
            return goal

        def activate_goal(self):
            goal.status = GoalStatus.ACTIVE
            goal.paused_reason = None
            goal.updated_at = 4.0
            return goal

    monkeypatch.setattr(
        turn_status_tool,
        "get_global_session_manager",
        lambda: SimpleNamespace(get_live_session=lambda session_id: _FakeSession()),
    )

    tool = TurnStatusTool()
    out = asyncio.run(tool.turn_status(status="continue_work", note="resuming", session_id="s1"))
    assert out["should_end"] is False
    assert out["goal"]["status"] == "active"
    assert out["goal"]["paused_reason"] is None
    assert out["goal_outcome"]["action"] == "continued"
    assert out["goal_outcome"]["reason"] == "resuming"

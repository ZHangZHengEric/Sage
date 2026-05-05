import json
import time

from common.schemas.goal import GoalStatus
from sagents.context.messages.message import MessageChunk
from sagents.context.session_context import SessionContext
from sagents.session_runtime import Session


def _make_session(tmp_path):
    return SessionContext(
        session_id="sess_goal",
        user_id="u1",
        agent_id="a1",
        session_root_space=str(tmp_path),
    )


def test_goal_lifecycle_updates_status_and_audit_fields(tmp_path):
    ctx = _make_session(tmp_path)

    goal = ctx.set_goal("Ship the runtime goal contract")
    assert goal.objective == "Ship the runtime goal contract"
    assert goal.status == GoalStatus.ACTIVE
    assert ctx.audit_status["goal_status"] == "active"
    assert ctx.audit_status["goal_objective"] == "Ship the runtime goal contract"
    assert ctx.system_context["active_goal"]["objective"] == "Ship the runtime goal contract"
    assert ctx.system_context["active_goal"]["status"] == "active"

    paused = ctx.pause_goal("user interrupt")
    assert paused.status == GoalStatus.PAUSED
    assert paused.paused_reason == "user interrupt"
    assert ctx.system_context["active_goal"]["status"] == "paused"
    assert ctx.system_context["active_goal"]["paused_reason"] == "user interrupt"

    active = ctx.activate_goal()
    assert active.status == GoalStatus.ACTIVE
    assert active.paused_reason is None
    assert ctx.system_context["active_goal"]["status"] == "active"
    assert "goal_resume_hint" in ctx.audit_status
    assert "resume" in ctx.system_context["active_goal"]["resume_hint"].lower()
    assert ctx.system_context["goal_continuation_policy"]["mode"] == "resume_active_goal"

    completed = ctx.complete_goal()
    assert completed.status == GoalStatus.COMPLETED
    assert completed.completed_at is not None
    assert ctx.system_context["active_goal"]["status"] == "completed"
    assert ctx.system_context["goal_transition"]["type"] == "completed"
    assert "goal_resume_hint" not in ctx.system_context
    assert ctx.system_context["goal_continuation_policy"]["mode"] == "closed"


def test_clear_goal_removes_runtime_goal_context(tmp_path):
    ctx = _make_session(tmp_path)
    ctx.set_goal("Clear this objective")
    ctx.pause_goal("interrupt")
    ctx.activate_goal()

    ctx.clear_goal()

    assert ctx.goal is None
    assert "active_goal" not in ctx.system_context
    assert "goal_resume_hint" not in ctx.system_context
    assert "goal_continuation_policy" not in ctx.system_context
    assert ctx.system_context["goal_transition"]["type"] == "cleared"
    assert "goal_status" not in ctx.audit_status


def test_goal_continuation_policy_reflects_paused_goal(tmp_path):
    ctx = _make_session(tmp_path)
    ctx.set_goal("Wait for the user's approval")

    paused = ctx.pause_goal("waiting_for_user_input")

    assert paused.status == GoalStatus.PAUSED
    assert ctx.system_context["goal_continuation_policy"]["mode"] == "await_resume"
    assert "waiting_for_user_input" in ctx.system_context["goal_continuation_policy"]["instruction"]


def test_goal_is_persisted_into_session_context_snapshot(tmp_path):
    ctx = _make_session(tmp_path)
    ctx._resolve_workspace_paths(str(tmp_path))
    ctx.sandbox_agent_workspace = str(tmp_path)
    ctx.set_goal("Persist this objective")

    ctx.save()

    snapshot_path = tmp_path / "sess_goal" / "session_context.json"
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert payload["goal"]["objective"] == "Persist this objective"
    assert payload["goal"]["status"] == "active"


def test_goal_transition_is_consumed_after_assistant_message(tmp_path):
    ctx = _make_session(tmp_path)
    ctx.set_goal("Finish the release checklist")
    ctx.clear_goal()

    assert ctx.system_context["goal_transition"]["type"] == "cleared"

    ctx.add_messages(
        MessageChunk(
            role="assistant",
            content="The previous goal is closed, ready for the next instruction.",
            timestamp=time.time(),
        )
    )

    assert "goal_transition" not in ctx.system_context
    assert "goal_transition" not in ctx.audit_status


def test_session_delegates_goal_pause_and_activate(tmp_path):
    session = Session("sess_goal_runtime")
    ctx = SessionContext(
        session_id="sess_goal_runtime",
        user_id="u1",
        agent_id="a1",
        session_root_space=str(tmp_path),
    )
    ctx.set_goal("Keep the contract coherent")
    session.set_context(ctx)

    paused = session.pause_goal("waiting_for_user_input")
    assert paused is not None
    assert paused.status == GoalStatus.PAUSED
    assert paused.paused_reason == "waiting_for_user_input"

    active = session.activate_goal()
    assert active is not None
    assert active.status == GoalStatus.ACTIVE
    assert active.paused_reason is None

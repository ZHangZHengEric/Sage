from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from sagents.v2.contracts.common import utc_now
from sagents.v2.contracts.events import (
    ContinuationEventData,
    ItemEventData,
    ToolEventData,
)
from sagents.v2.contracts.items import ItemSnapshot, ItemStatus, ToolCallItemData
from sagents.v2.contracts.run_state import RunState
from sagents.v2.goal.state import GoalStateService
from sagents.v2.goal.context import GoalCompletionGatePolicy
from sagents.v2.agent.policy import ContinuationAction, ContinuationContext
from sagents.v2.model.contracts import ModelResponse, ModelToolCall
from sagents.v2.tool.official.planning import PlanningTools
from sagents.v2.i18n import tr


def tool_events(run_id, name, arguments, *, succeeded=True):
    call_id = f"{run_id}_{name}"
    item = ItemSnapshot(
        item_id=call_id,
        run_id=run_id,
        status=ItemStatus.COMPLETED,
        created_at=utc_now(),
        updated_at=utc_now(),
        data=ToolCallItemData(
            tool_call_id=call_id, tool_name=name, arguments=arguments
        ),
    )
    events = [
        SimpleNamespace(
            type="item.completed",
            data=ItemEventData(operation="completed", item=item),
        )
    ]
    if succeeded:
        events.append(
            SimpleNamespace(
                type="tool.call.succeeded",
                data=ToolEventData(
                    tool_call_id=call_id, tool_name=name, state="completed"
                ),
            )
        )
    return events


def questionnaire_boundary():
    return SimpleNamespace(
        type="continuation.decided",
        data=ContinuationEventData(
            action="complete_run",
            reason_code="tool.questionnaire_ready",
            reason="Awaiting an answer",
            decision_hash="test",
        ),
    )


class Journal:
    def __init__(self):
        self.runs = {}
        self.commands = {}
        self.events = {}
        self.sessions = {}

    def add(self, run_id, mode, events=(), *, state=RunState.COMPLETED, session="s"):
        history = self.sessions.setdefault(session, [])
        self.runs[run_id] = SimpleNamespace(
            session_id=session,
            base_session_sequence=len(history),
            state=state,
        )
        self.commands[run_id] = SimpleNamespace(
            invocation_mode=mode,
            config=SimpleNamespace(metadata={}),
        )
        self.events[run_id] = tuple(events)
        history.append(SimpleNamespace(run_id=run_id))

    async def get_run(self, run_id):
        return self.runs[run_id]

    async def get_start_command(self, run_id):
        return self.commands[run_id]

    async def read_events(self, run_id):
        return self.events[run_id]

    async def read_session_events(self, session_id, *, limit):
        return self.sessions[session_id][:limit]


@pytest.mark.asyncio
async def test_approved_plan_survives_questionnaire_chain_and_ignores_future_runs():
    journal = Journal()
    journal.add(
        "plan", "plan", tool_events("plan", "goal_submit", {"content": "Ship it"})
    )
    journal.add("question1", "goal", [questionnaire_boundary()])
    journal.add("question2", "goal", [questionnaire_boundary()])
    journal.add("answer", "goal")
    journal.add(
        "future",
        "goal",
        tool_events("future", "goal_submit", {"content": "Other task"}),
    )
    state = await GoalStateService(journal).get("answer")
    assert state is not None and state.content == "Ship it"
    assert state.source == "plan" and state.created_tool_call_id == "plan"
    assert not state.completed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "boundary",
    [
        "completed_goal",
        "cancelled",
        "failed",
        "normal_mode",
        "plan_mode",
        "different_session",
        "different_finish",
        "unsuccessful_submit",
    ],
)
async def test_goal_is_not_inherited_across_unrelated_boundaries(boundary):
    journal = Journal()
    events = tool_events(
        "first",
        "goal_submit",
        {"content": "Original task"},
        succeeded=boundary != "unsuccessful_submit",
    )
    if boundary == "completed_goal":
        events += tool_events("first", "goal_complete", {"summary": "Verified"})
    if boundary != "different_finish":
        events.append(questionnaire_boundary())
    journal.add(
        "first",
        "goal",
        events,
        state={"cancelled": RunState.CANCELLED, "failed": RunState.FAILED}.get(
            boundary,
            RunState.COMPLETED,
        ),
    )
    if boundary in {"normal_mode", "plan_mode"}:
        journal.add("intervening", boundary.removesuffix("_mode"))
    journal.add(
        "answer", "goal", session="other" if boundary == "different_session" else "s"
    )
    assert await GoalStateService(journal).get("answer") is None


@pytest.mark.asyncio
async def test_exiting_goal_mode_does_not_inherit_questionnaire_goal():
    journal = Journal()
    journal.add(
        "first",
        "goal",
        [
            *tool_events("first", "goal_submit", {"content": "Original task"}),
            questionnaire_boundary(),
        ],
    )
    journal.add("answer", "normal")
    journal.read_session_events = AsyncMock(
        side_effect=AssertionError("must not inherit")
    )
    assert await GoalStateService(journal).get("answer") is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_name,text,expected",
    [
        ("goal_complete", "调用 goal_complete。", ContinuationAction.CONTINUE_STEP),
        ("goal_complete", "", ContinuationAction.CONTINUE_STEP),
        ("file_read", "正在检查文件。", ContinuationAction.CONTINUE_STEP),
        (None, "", ContinuationAction.CONTINUE_STEP),
        (None, "已交付网页，完成代码检查。", ContinuationAction.COMPLETE_RUN),
        ("turn_status", "已交付网页，完成代码检查。", ContinuationAction.COMPLETE_RUN),
    ],
)
async def test_completed_goal_waits_for_post_tool_summary(tool_name, text, expected):
    goals = SimpleNamespace(
        is_goal_mode=AsyncMock(return_value=True),
        get=AsyncMock(return_value=SimpleNamespace(completed=True)),
    )
    base = SimpleNamespace(decide=AsyncMock())
    response = ModelResponse(
        response_id="completion",
        text=text,
        tool_calls=(ModelToolCall(tool_call_id="call", name=tool_name, arguments={}),)
        if tool_name
        else (),
        finish_reason="tool_calls" if tool_name else "stop",
    )
    decision = await GoalCompletionGatePolicy(base, goals).decide(
        ContinuationContext(
            run_id="run", step_number=2, max_steps=10, response=response
        )
    )
    assert decision.action == expected
    base.decide.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("completed", [False, True])
async def test_goal_complete_returns_summary_guidance_including_repeated_call(
    completed,
):
    state = SimpleNamespace(
        completed=completed,
        content="Deliver the page",
        completion_summary="Saved summary",
    )
    goals = SimpleNamespace(
        is_goal_mode=AsyncMock(return_value=True), get=AsyncMock(return_value=state)
    )
    invocation = SimpleNamespace(
        call=SimpleNamespace(owner_run_id="run"),
        request_context=SimpleNamespace(language="zh"),
    )
    result = await PlanningTools(
        SimpleNamespace(goal_state_service=goals)
    ).goal_complete("Verified summary", invocation)
    assert result["summary"] == ("Saved summary" if completed else "Verified summary")
    assert result["next_step"] == tr("goal.explanation_required", "zh")

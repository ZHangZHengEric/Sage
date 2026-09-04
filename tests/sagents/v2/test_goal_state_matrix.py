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

"""Rebuild goal-mode state from the canonical SessionStore journal."""

from __future__ import annotations

from typing import Protocol

from sagents.v2.contracts.commands import StartRun
from sagents.v2.contracts.events import (
    ContinuationEventData,
    ItemEventData,
    RuntimeEvent,
    ToolEventData,
)
from sagents.v2.contracts.items import ToolCallItemData
from sagents.v2.contracts.run_state import RunSnapshot, RunState
from sagents.v2.context.plan_execution import preceding_plan

from .contracts import GoalState


class GoalStateReader(Protocol):
    async def get_start_command(self, run_id: str) -> StartRun: ...

    async def read_events(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> tuple[RuntimeEvent, ...]: ...

    async def get_run(self, run_id: str) -> RunSnapshot: ...

    async def read_session_events(
        self,
        session_id: str,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> tuple[RuntimeEvent, ...]: ...


class GoalStateService:
    """Treat successful goal Tool calls as the durable source of truth."""

    def __init__(self, reader: GoalStateReader) -> None:
        self.reader = reader

    async def is_goal_mode(self, run_id: str) -> bool:
        command = await self.reader.get_start_command(run_id)
        return command.invocation_mode == "goal" or (
            command.config.metadata.get("goal_mode") is True
        )

    async def is_plan_mode(self, run_id: str) -> bool:
        command = await self.reader.get_start_command(run_id)
        return command.invocation_mode == "plan" or (
            command.config.metadata.get("plan_mode") is True
        )

    async def get(self, run_id: str) -> GoalState | None:
        # Questionnaire answers start a new Run. Replay only the contiguous
        # goal-mode questionnaire chain, bounded by each Run's session snapshot.
        # No process-local cache: the same state must survive application restart.
        chain = [run_id]
        while await self.is_goal_mode(chain[-1]):
            previous = await self._questionnaire_predecessor(chain[-1])
            if previous is None or previous in chain:
                break
            chain.append(previous)

        state: GoalState | None = None
        if await self.is_goal_mode(chain[-1]):
            plan = await preceding_plan(self.reader, chain[-1])
            if plan is not None:
                source_run_id, content = plan
                state = GoalState(
                    content=content,
                    created_tool_call_id=source_run_id,
                    source="plan",
                )
        for entry in reversed(chain):
            # A completed goal is never resurrected by a later user answer.
            if state is not None and state.completed:
                state = None
            state = await self._apply_run(entry, state)
        return state

    async def _questionnaire_predecessor(self, run_id: str) -> str | None:
        current = await self.reader.get_run(run_id)
        if current.base_session_sequence == 0:
            return None
        events = await self.reader.read_session_events(
            current.session_id, limit=current.base_session_sequence
        )
        previous_id = next(
            (event.run_id for event in reversed(events) if event.run_id != run_id),
            None,
        )
        if previous_id is None or not await self.is_goal_mode(previous_id):
            return None
        previous = await self.reader.get_run(previous_id)
        if previous.state != RunState.COMPLETED:
            return None
        decisions = [
            event.data
            for event in await self.reader.read_events(previous_id)
            if event.type == "continuation.decided"
            and isinstance(event.data, ContinuationEventData)
        ]
        if decisions and decisions[-1].reason_code == "tool.questionnaire_ready":
            return previous_id
        return None

    async def _apply_run(
        self, run_id: str, state: GoalState | None
    ) -> GoalState | None:
        events = await self.reader.read_events(run_id)
        calls: list[ToolCallItemData] = []
        succeeded: set[str] = set()
        for event in events:
            data = event.data
            if (
                event.type == "item.completed"
                and isinstance(data, ItemEventData)
                and data.item is not None
                and isinstance(data.item.data, ToolCallItemData)
                and data.item.data.tool_name
                in {"goal_submit", "goal_create", "plan_submit", "goal_complete"}
            ):
                calls.append(data.item.data)
            if (
                event.type in {"tool.call.succeeded", "tool.call.reconciled"}
                and isinstance(data, ToolEventData)
                and data.state == "completed"
            ):
                succeeded.add(data.tool_call_id)

        command = await self.reader.get_start_command(run_id)
        mode = command.invocation_mode or "normal"
        for call in calls:
            if call.tool_call_id not in succeeded:
                continue
            arguments = call.arguments or {}
            if call.tool_name in {"goal_submit", "goal_create", "plan_submit"}:
                content = str(arguments.get("content") or "").strip()
                if not content:
                    continue
                state = GoalState(
                    content=content,
                    created_tool_call_id=call.tool_call_id,
                    source=(
                        "plan"
                        if mode == "plan" or call.tool_name == "plan_submit"
                        else "direct"
                    ),
                )
            elif call.tool_name == "goal_complete" and state is not None:
                state = state.model_copy(
                    update={
                        "completed": True,
                        "completion_summary": str(
                            arguments.get("summary") or ""
                        ).strip()
                        or None,
                        "completed_tool_call_id": call.tool_call_id,
                    }
                )
        return state

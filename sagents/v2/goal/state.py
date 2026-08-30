"""Rebuild goal-mode state from the canonical SessionStore journal."""

from __future__ import annotations

from typing import Protocol

from sagents.v2.contracts.commands import StartRun
from sagents.v2.contracts.events import ItemEventData, RuntimeEvent, ToolEventData
from sagents.v2.contracts.items import ToolCallItemData
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

    async def get_run(self, run_id: str): ...

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
        state: GoalState | None = None
        if mode == "goal" or command.config.metadata.get("goal_mode") is True:
            plan = await preceding_plan(self.reader, run_id)
            if plan is not None:
                source_run_id, content = plan
                state = GoalState(
                    content=content,
                    created_tool_call_id=source_run_id,
                    source="plan",
                )
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

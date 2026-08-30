"""Recover the immediately preceding completed plan for goal confirmation."""

from __future__ import annotations

from typing import Protocol

from sagents.v2.contracts.commands import StartRun
from sagents.v2.contracts.events import ItemEventData, RuntimeEvent, ToolEventData
from sagents.v2.contracts.items import ToolCallItemData
from sagents.v2.contracts.run_state import RunSnapshot, RunState


class PlanExecutionReader(Protocol):
    async def get_run(self, run_id: str) -> RunSnapshot: ...

    async def get_start_command(self, run_id: str) -> StartRun: ...

    async def read_session_events(
        self,
        session_id: str,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> tuple[RuntimeEvent, ...]: ...

    async def read_events(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> tuple[RuntimeEvent, ...]: ...


async def preceding_plan(
    reader: PlanExecutionReader,
    run_id: str,
) -> tuple[str, str] | None:
    """Return the completed plan immediately preceding a goal-mode Run."""

    current = await reader.get_run(run_id)
    if current.base_session_sequence == 0:
        return None
    events = await reader.read_session_events(
        current.session_id, limit=current.base_session_sequence
    )
    previous_run_id = next(
        (event.run_id for event in reversed(events) if event.run_id != run_id),
        None,
    )
    if previous_run_id is None:
        return None
    previous = await reader.get_run(previous_run_id)
    previous_command = await reader.get_start_command(previous_run_id)
    if (
        previous.state != RunState.COMPLETED
        or previous_command.invocation_mode != "plan"
    ):
        return None
    calls: list[ToolCallItemData] = []
    succeeded: set[str] = set()
    for event in await reader.read_events(previous_run_id):
        data = event.data
        if (
            event.type == "item.completed"
            and isinstance(data, ItemEventData)
            and data.item is not None
            and isinstance(data.item.data, ToolCallItemData)
            and data.item.data.tool_name in {"goal_submit", "plan_submit"}
        ):
            calls.append(data.item.data)
        if (
            event.type in {"tool.call.succeeded", "tool.call.reconciled"}
            and isinstance(data, ToolEventData)
            and data.state == "completed"
        ):
            succeeded.add(data.tool_call_id)
    for call in reversed(calls):
        if call.tool_call_id not in succeeded:
            continue
        content = str((call.arguments or {}).get("content") or "").strip()
        if content:
            return previous_run_id, content
    return None

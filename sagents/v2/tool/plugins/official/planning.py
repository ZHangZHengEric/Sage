"""Decorator-backed V2 planning and turn-control tools."""

from __future__ import annotations

from typing import Any, Literal

from sagents.v2.tool import SideEffectLevel, ToolInvocation, tool
from sagents.v2.tool.plugins.official.runtime import OfficialToolRuntime


_TODO_STATUSES = {"pending", "in_progress", "completed"}

_TODO_WRITE_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "tasks": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "minLength": 1},
                    "content": {"type": "string", "minLength": 1},
                    "status": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "completed"],
                    },
                    "conclusion": {"type": "string"},
                },
                "required": ["id"],
                "additionalProperties": False,
            },
        },
        "session_id": {"type": "string"},
    },
    "required": ["tasks", "session_id"],
    "additionalProperties": False,
}


class PlanningTools:
    def __init__(self, runtime: OfficialToolRuntime) -> None:
        self.runtime = runtime

    @tool(
        description="Replace the current structured task list.",
        input_schema=_TODO_WRITE_INPUT_SCHEMA,
        side_effect_level=SideEffectLevel.WRITE,
        plan_safe=True,
    )
    async def todo_write(
        self,
        tasks: list[dict[str, Any]],
        session_id: str,
        invocation: ToolInvocation,
    ) -> dict[str, Any]:
        del session_id
        current = await self.runtime.load_todos(invocation)
        task_map = {str(value.get("id")): dict(value) for value in current}
        added = 0
        updated = 0
        for index, task in enumerate(tasks):
            if not isinstance(task, dict):
                raise ValueError(f"task {index} must be an object")
            identifier = str(task.get("id") or "").strip()
            if not identifier:
                raise ValueError(f"task {index} requires id")
            existing = task_map.get(identifier)
            if existing is None:
                content = task.get("content")
                if not isinstance(content, str) or not content.strip():
                    raise ValueError(f"new task {identifier} requires content")
                existing = {
                    "id": identifier,
                    "content": content,
                    "status": "pending",
                }
                added += 1
            else:
                updated += 1
            for field in ("content", "status", "conclusion"):
                if field in task:
                    existing[field] = task[field]
            status = str(existing.get("status") or "pending").lower()
            if status not in _TODO_STATUSES:
                raise ValueError(f"task {identifier} has invalid status {status!r}")
            existing["status"] = status
            task_map[identifier] = existing
        normalized = list(task_map.values())
        active = sum(value.get("status") == "in_progress" for value in normalized)
        if active > 1:
            raise ValueError("only one task may be in_progress")
        path = await self.runtime.save_todos(normalized, invocation)
        return {
            "status": "success",
            "tasks": normalized,
            "path": path,
            "added": added,
            "updated": updated,
        }

    @tool(
        description="Read the current structured task list.",
        side_effect_level=SideEffectLevel.READ,
    )
    async def todo_read(
        self,
        session_id: str,
        invocation: ToolInvocation,
    ) -> dict[str, Any]:
        del session_id
        return {
            "status": "success",
            "tasks": await self.runtime.load_todos(invocation),
        }

    @tool(
        description=(
            "Submit the single free-form goal for this Run. In Plan mode, put the "
            "complete proposed Plan in content for user approval. In Goal mode, put "
            "the complete direct goal in content before substantive execution."
        ),
        input_schema={
            "type": "object",
            "properties": {"content": {"type": "string", "minLength": 1}},
            "required": ["content"],
            "additionalProperties": False,
        },
        strict=True,
        plan_safe=True,
    )
    async def goal_submit(
        self,
        content: str,
        invocation: ToolInvocation,
    ) -> dict[str, Any]:
        goals = self.runtime.goal_state_service
        if goals is None:
            raise RuntimeError("goal state service is unavailable")
        run_id = invocation.call.owner_run_id
        is_plan = await goals.is_plan_mode(run_id)
        is_goal = await goals.is_goal_mode(run_id)
        if not (is_plan or is_goal):
            raise ValueError("goal_submit is available only in plan or goal mode")
        existing = await goals.get(invocation.call.owner_run_id)
        if existing is not None:
            raise ValueError("this Run already has a goal")
        normalized = content.strip()
        if not normalized:
            raise ValueError("goal content must not be empty")
        return {
            "status": "approved" if is_plan else "active",
            "content": normalized,
            "source": "plan" if is_plan else "direct",
        }

    @tool(
        description=(
            "Complete the active goal after independently verifying every acceptance "
            "criterion. A goal-mode Run cannot finish successfully until this Tool "
            "succeeds."
        ),
        input_schema={
            "type": "object",
            "properties": {"summary": {"type": "string", "minLength": 1}},
            "required": ["summary"],
            "additionalProperties": False,
        },
        strict=True,
    )
    async def goal_complete(
        self,
        summary: str,
        invocation: ToolInvocation,
    ) -> dict[str, Any]:
        goals = self.runtime.goal_state_service
        if goals is None:
            raise RuntimeError("goal state service is unavailable")
        if not await goals.is_goal_mode(invocation.call.owner_run_id):
            raise ValueError("goal_complete is available only in goal mode")
        state = await goals.get(invocation.call.owner_run_id)
        if state is None:
            raise ValueError("call goal_submit before goal_complete")
        if state.completed:
            return {
                "status": "completed",
                "content": state.content,
                "summary": state.completion_summary,
                "already_completed": True,
            }
        normalized = summary.strip()
        if not normalized:
            raise ValueError("completion summary must not be empty")
        return {
            "status": "completed",
            "content": state.content,
            "summary": normalized,
            "already_completed": False,
        }

    @tool(
        description=(
            "Control what happens after the current model response. First write "
            "the user-facing result, question, or blocker explanation, then call "
            "this tool in the same response. task_done completes the Run; "
            "need_user_input and blocked suspend it for a user reply; "
            "continue_work starts another Agent step; failed ends the Run as "
            "failed."
        ),
    )
    async def turn_status(
        self,
        status: Literal[
            "task_done",
            "need_user_input",
            "blocked",
            "continue_work",
            "failed",
        ],
        note: str | None = None,
        session_id: str | None = None,
        invocation: ToolInvocation | None = None,
    ) -> dict[str, Any]:
        del session_id
        run_id = invocation.call.owner_run_id if invocation is not None else "unknown"
        value = {"status": status, "note": note}
        self.runtime.set_turn_status(run_id, value)
        return value

    @tool(description="Activate exact Tool names for the current Run.")
    async def tool_expand_tools(
        self,
        tool_names: list[str],
        session_id: str | None = None,
        invocation: ToolInvocation | None = None,
    ) -> dict[str, Any]:
        del session_id
        run_id = invocation.call.owner_run_id if invocation is not None else "unknown"
        return await self.runtime.expand_tools(run_id, tool_names)

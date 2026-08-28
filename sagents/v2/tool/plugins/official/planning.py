"""Decorator-backed V2 planning and turn-control tools."""

from __future__ import annotations

from typing import Any, Literal

from sagents.v2.tool import SideEffectLevel, ToolInvocation, tool
from sagents.v2.tool.plugins.official.runtime import OfficialToolRuntime


_TODO_STATUSES = {"pending", "in_progress", "completed"}


class PlanningTools:
    def __init__(self, runtime: OfficialToolRuntime) -> None:
        self.runtime = runtime

    @tool(description="Replace the current structured task list.", side_effect_level=SideEffectLevel.WRITE)
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

    @tool(description="Read the current structured task list.", side_effect_level=SideEffectLevel.READ)
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

    @tool(description="Publish the current turn status.")
    async def turn_status(
        self,
        status: Literal["task_done", "need_user_input", "blocked", "continue_work"],
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

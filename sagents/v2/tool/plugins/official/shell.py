"""Decorator-backed V2 shell tools."""

from __future__ import annotations

import json
from typing import Any

from sagents.v2.tool import SideEffectLevel, ToolInvocation, tool
from sagents.v2.tool.plugins.official.runtime import OfficialToolRuntime


class ShellTools:
    def __init__(self, runtime: OfficialToolRuntime) -> None:
        self.runtime = runtime

    @tool(
        description=(
            "Execute a shell command in the workspace. block_until_ms=0 runs "
            "in the background and returns a task_id."
        ),
        side_effect_level=SideEffectLevel.WRITE,
        requires_approval=True,
    )
    async def execute_shell_command(
        self,
        command: str,
        invocation: ToolInvocation,
        workdir: str | None = None,
        block_until_ms: int = 30000,
        env_vars: str | None = None,
        approval_id: str | None = None,
        sandbox_approval_mode: str | None = None,
        command_policy: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        del approval_id, sandbox_approval_mode, command_policy, session_id
        environment: dict[str, str] = {}
        if env_vars:
            parsed = json.loads(env_vars)
            if not isinstance(parsed, dict) or not all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in parsed.items()
            ):
                raise ValueError("env_vars must be a JSON object of string values")
            environment = parsed
        return await self.runtime.shell(
            command,
            invocation,
            workdir=workdir,
            env_vars=environment,
            block_until_ms=max(0, block_until_ms),
        )

    @tool(description="Wait for a background shell task and read its output.")
    async def await_shell(
        self,
        task_id: str,
        block_until_ms: int = 600000,
        pattern: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        del session_id
        return await self.runtime.await_shell(
            task_id,
            block_until_ms=max(0, block_until_ms),
            pattern=pattern,
        )

    @tool(
        description="Terminate a background shell task.",
        side_effect_level=SideEffectLevel.WRITE,
        requires_approval=True,
    )
    async def kill_shell(
        self,
        task_id: str,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        del session_id
        return await self.runtime.kill_shell(task_id)

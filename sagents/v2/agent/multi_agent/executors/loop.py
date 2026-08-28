"""Execute delegated Agents by creating ordinary v2 child Runs."""

from __future__ import annotations

from collections.abc import Callable

from sagents.v2.agent import AgentLoopEngine
from sagents.v2.contracts.commands import InputItem, RunConfig, StartRun
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo
from sagents.v2.contracts.items import ContentBlock, MessageItemData, TextBlock
from sagents.v2.contracts.principals import RequestContext
from sagents.v2.contracts.run_state import RunState, SessionConcurrencyMode
from sagents.v2.runtime import HarnessRuntime
from sagents.v2.agent.multi_agent.contracts import (
    AgentDescriptor,
    DelegationResult,
    DelegationTask,
    WorkspaceSharingPolicy,
)


LoopFactory = Callable[[AgentDescriptor, str], AgentLoopEngine]


class LoopChildRunExecutor:
    """Executes every sub-agent as a real resumable Native Run."""

    def __init__(
        self,
        *,
        runtime: HarnessRuntime,
        loop_factory: LoopFactory,
        resolved_spec_hash: str,
    ) -> None:
        self.runtime = runtime
        self.loop_factory = loop_factory
        self.resolved_spec_hash = resolved_spec_hash

    async def run_child(
        self,
        descriptor: AgentDescriptor,
        task: DelegationTask,
        *,
        parent_run_id: str,
        workspace_policy: WorkspaceSharingPolicy,
        context: RequestContext,
    ) -> DelegationResult:
        """Create a fork for new work or continue the Agent's existing child Session.

        A new task forks the parent Session to isolate canonical history. A
        follow-up task with `child_session_id` starts a serial Run in that child
        Session, preserving the child Agent's own conversation.
        """

        parent = await self.runtime.get_run(parent_run_id)
        continuing = task.child_session_id is not None
        command = StartRun(
            session_id=task.child_session_id if continuing else parent.session_id,
            agent_id=descriptor.agent_id,
            input=(InputItem(role="user", content=(TextBlock(text=task.content),)),),
            config=RunConfig(
                metadata={
                    "task_name": task.task_name,
                    "original_task": task.original_task,
                    "workspace_policy": workspace_policy.value,
                    "agent_mode": descriptor.mode.value,
                }
            ),
            session_concurrency_mode=(
                SessionConcurrencyMode.SERIAL
                if continuing
                else SessionConcurrencyMode.FORK
            ),
            resolved_spec_hash=self.resolved_spec_hash,
            idempotency_key=f"delegate:{parent_run_id}:{task.task_id}",
            parent_run_id=parent_run_id,
            invocation_mode="delegation",
        )
        handle = await self.runtime.start_run(command, context)
        current = await self.runtime.get_run(handle.run_id)
        loop = self.loop_factory(descriptor, handle.run_id)
        if current.state == RunState.RESUMING:
            run = await loop.resume(handle.run_id, context)
        elif current.state in {RunState.QUEUED, RunState.RUNNING}:
            run = await loop.execute(handle.run_id, context)
        else:
            run = current
        content: tuple[ContentBlock, ...] = ()
        error = None
        if run.state in {RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED}:
            result = await self.runtime.get_run_result(run.run_id)
            content = tuple(
                block
                for item in result.final_items
                if isinstance(item.data, MessageItemData)
                and item.data.role == "assistant"
                for block in item.data.content
            )
            error = result.error
        elif run.state == RunState.SUSPENDED:
            error = RuntimeErrorInfo(
                code="agent.child_suspended",
                category=ErrorCategory.CONFLICT,
                message="child run requires an interaction before delegation can finish",
                safe_to_resume=True,
            )
        return DelegationResult(
            task_id=task.task_id,
            agent_id=task.agent_id,
            child_session_id=handle.session_id,
            child_run_id=handle.run_id,
            outcome=run.state,
            content=content,
            error=error,
        )

"""Execute delegated Agents by creating ordinary v2 child Runs."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from copy import deepcopy

from sagents.v2.agent import AgentLoopEngine
from sagents.v2.contracts.commands import (
    InputItem,
    ReplyInteraction,
    RunConfig,
    StartRun,
)
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.items import ContentBlock, MessageItemData, TextBlock
from sagents.v2.contracts.principals import RequestContext
from sagents.v2.contracts.run_state import (
    RunState,
    SessionConcurrencyMode,
    TERMINAL_RUN_STATES,
)
from sagents.v2.runtime.contracts import RuntimePort
from sagents.v2.agent.multi_agent.contracts import (
    AgentDescriptor,
    AgentInvocationMode,
    DelegationResult,
    DelegationTask,
    WorkspaceSharingPolicy,
)


LoopFactory = Callable[
    ...,
    AgentLoopEngine
    | tuple[AgentLoopEngine, object]
    | Awaitable[AgentLoopEngine | tuple[AgentLoopEngine, object]],
]
DescriptorResolver = Callable[[str], Awaitable[AgentDescriptor]]


_INHERITED_RUNTIME_METADATA = (
    "current_time",
    "system_context",
    "identity_documents",
    "approval_mode",
)
_SHARED_WORKSPACE_METADATA = (
    "working_directory",
    "workspace_files",
    "external_paths",
)


class LoopChildRunExecutor:
    """Executes every sub-agent as a real resumable Native Run."""

    def __init__(
        self,
        *,
        runtime: RuntimePort,
        loop_factory: LoopFactory,
        resolved_spec_hash: str,
        descriptor_resolver: DescriptorResolver | None = None,
    ) -> None:
        self.runtime = runtime
        self.loop_factory = loop_factory
        self.resolved_spec_hash = resolved_spec_hash
        self.descriptor_resolver = descriptor_resolver
        self._descriptors_by_run: dict[str, AgentDescriptor] = {}
        self._tasks_by_run: dict[str, DelegationTask] = {}
        self._loops_by_run: dict[str, AgentLoopEngine] = {}
        self._resources_by_run: dict[str, object] = {}

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

        if task.invocation_mode == AgentInvocationMode.DELEGATION:
            # Existing Fibre/Team members retain their declared identity and
            # capabilities but execute this delegated invocation as a leaf.
            descriptor = descriptor.model_copy(update={"allow_delegation": False})

        parent = await self.runtime.get_run(parent_run_id)
        parent_command = await self.runtime.session_store.get_start_command(
            parent_run_id
        )
        parent_metadata = parent_command.config.metadata
        inherited_keys = list(_INHERITED_RUNTIME_METADATA)
        if workspace_policy == WorkspaceSharingPolicy.SHARED_PARENT:
            inherited_keys.extend(_SHARED_WORKSPACE_METADATA)
        metadata = {
            key: deepcopy(parent_metadata[key])
            for key in inherited_keys
            if key in parent_metadata
        }
        metadata.update(
            {
                "task_name": task.task_name,
                "original_task": task.original_task,
                "parent_tool_call_id": task.parent_tool_call_id or "",
                "workspace_policy": workspace_policy.value,
                "agent_mode": descriptor.mode.value,
                "response_language": str(
                    parent_metadata.get("response_language") or context.language
                ),
            }
        )
        input_metadata = {}
        current_time = metadata.get("current_time")
        if current_time not in (None, ""):
            input_metadata["frozen_current_time_context"] = (
                f"<current_time>{current_time}</current_time>"
            )
        continuing = task.child_session_id is not None
        command = StartRun(
            session_id=task.child_session_id if continuing else parent.session_id,
            agent_id=descriptor.agent_id,
            input=(
                InputItem(
                    role="user",
                    content=(TextBlock(text=task.content),),
                    metadata=input_metadata,
                ),
            ),
            config=RunConfig(
                enabled_tools=descriptor.tools,
                enabled_skills=descriptor.skills,
                flow_boundary=task.flow_boundary,
                metadata=metadata,
            ),
            session_concurrency_mode=(
                SessionConcurrencyMode.SERIAL
                if continuing
                else SessionConcurrencyMode.FORK
            ),
            resolved_spec_hash=self.resolved_spec_hash,
            idempotency_key=f"delegate:{parent_run_id}:{task.task_id}",
            parent_run_id=parent_run_id,
            invocation_mode=task.invocation_mode.value,
        )
        handle = await self.runtime.start_run(command, context)
        self._descriptors_by_run[handle.run_id] = descriptor
        self._tasks_by_run[handle.run_id] = task
        current = await self.runtime.get_run(handle.run_id)
        try:
            loop = await self._loop_for(descriptor, handle.run_id, context)
            if current.state == RunState.RESUMING:
                run = await loop.resume(handle.run_id, context)
            elif current.state in {RunState.QUEUED, RunState.RUNNING}:
                run = await loop.execute(handle.run_id, context)
            else:
                run = current
        except asyncio.CancelledError:
            await self._settle_crashed_child(
                handle.run_id, context, "cancelled locally"
            )
            raise
        except Exception as exc:
            run = await self._settle_crashed_child(handle.run_id, context, str(exc))
        result = await self._result(task, handle.session_id, run)
        if run.state in TERMINAL_RUN_STATES:
            await self._release_run(handle.run_id)
        return result

    async def _loop_for(self, descriptor, run_id, context):
        loop = self._loops_by_run.get(run_id)
        if loop is not None:
            return loop
        parameters = tuple(inspect.signature(self.loop_factory).parameters.values())
        accepts_context = any(
            value.kind
            in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}
            for value in parameters
        ) or len(parameters) >= 3
        built = (
            self.loop_factory(descriptor, run_id, context)
            if accepts_context
            else self.loop_factory(descriptor, run_id)
        )
        if inspect.isawaitable(built):
            built = await built
        resource = None
        if isinstance(built, tuple) and len(built) == 2:
            loop, resource = built
        else:
            loop = built
        self._loops_by_run[run_id] = loop
        if resource is not None:
            self._resources_by_run[run_id] = resource
        return loop

    async def _release_run(self, run_id):
        self._loops_by_run.pop(run_id, None)
        resource = self._resources_by_run.pop(run_id, None)
        closer = getattr(resource, "close", None)
        if closer is not None:
            closed = closer()
            if inspect.isawaitable(closed):
                await closed

    async def close(self) -> None:
        for run_id in tuple(self._resources_by_run):
            await self._release_run(run_id)

    async def _settle_crashed_child(self, run_id, context, message):
        """Ensure a created child Run never remains active after its driver exits."""

        error = RuntimeErrorInfo(
            code="agent.child_driver_crashed",
            category=ErrorCategory.INTERNAL,
            message=message,
            safe_to_resume=True,
        )
        current = await self.runtime.get_run(run_id)
        if current.state in TERMINAL_RUN_STATES or current.state in {
            RunState.SUSPENDED,
            RunState.SUSPEND_REQUESTED,
        }:
            return current
        try:
            return await self.runtime.fail_run(
                run_id=run_id,
                expected_revision=current.revision,
                error=error,
                context=context,
                idempotency_key=f"child-driver-crashed:{run_id}:{current.revision}",
            )
        except SageV2Error:
            latest = await self.runtime.get_run(run_id)
            if latest.state in TERMINAL_RUN_STATES or latest.state in {
                RunState.SUSPENDED,
                RunState.SUSPEND_REQUESTED,
            }:
                return latest
            return await self.runtime.fail_run(
                run_id=run_id,
                expected_revision=latest.revision,
                error=error,
                context=context,
                idempotency_key=f"child-driver-crashed:{run_id}:{latest.revision}",
            )

    async def pending_interaction(self, run_id: str) -> dict | None:
        run = await self.runtime.get_run(run_id)
        if run.state != RunState.SUSPENDED or run.suspension_id is None:
            return None
        suspension = await self.runtime.session_store.get_suspension(run.suspension_id)
        if suspension.interaction_id is None:
            return None
        interaction = await self.runtime.session_store.get_interaction(
            suspension.interaction_id
        )
        return interaction.model_dump(mode="json")

    async def resolve_interaction(
        self,
        run_id: str,
        *,
        decision: str,
        payload: dict,
        context: RequestContext,
    ) -> DelegationResult:
        run = await self.runtime.get_run(run_id)
        command = await self.runtime.session_store.get_start_command(run_id)
        descriptor = self._descriptors_by_run.get(run_id)
        if descriptor is None and self.descriptor_resolver is not None:
            descriptor = await self.descriptor_resolver(command.agent_id)
        if (
            descriptor is not None
            and command.invocation_mode == AgentInvocationMode.DELEGATION.value
        ):
            # Reapply the durable leaf boundary after process restart.
            descriptor = descriptor.model_copy(update={"allow_delegation": False})
        if descriptor is not None:
            self._descriptors_by_run[run_id] = descriptor
        if descriptor is None or run.suspension_id is None:
            raise RuntimeError("delegated run cannot be resumed by this executor")
        suspension = await self.runtime.session_store.get_suspension(run.suspension_id)
        if suspension.interaction_id is None:
            raise RuntimeError("delegated run suspension has no interaction")
        interaction = await self.runtime.session_store.get_interaction(
            suspension.interaction_id
        )
        receipt = await self.runtime.reply_interaction(
            ReplyInteraction(
                run_id=run_id,
                suspension_id=suspension.suspension_id,
                interaction_id=interaction.interaction_id,
                expected_revision=run.revision,
                expected_suspension_revision=suspension.expected_revision,
                expected_interaction_revision=interaction.expected_revision,
                decision=decision,
                payload=payload,
                idempotency_key=(
                    f"delegated-interaction:{run_id}:"
                    f"{interaction.interaction_id}:{interaction.expected_revision}"
                ),
            ),
            context,
        )
        if receipt.decision.value == "rejected":
            raise RuntimeError(
                receipt.error.message
                if receipt.error
                else "delegated reply was rejected"
            )
        resumed = await (await self._loop_for(descriptor, run_id, context)).resume(
            run_id, context
        )
        task = self._tasks_by_run.get(run_id)
        if task is None:
            task = DelegationTask(
                task_id=run_id,
                agent_id=descriptor.agent_id,
                task_name=str(
                    command.config.metadata.get("task_name") or descriptor.name
                ),
                original_task=str(command.config.metadata.get("original_task") or ""),
                content=self._input_text(command.input),
                parent_tool_call_id=(
                    str(command.config.metadata.get("parent_tool_call_id") or "")
                    or None
                ),
                child_session_id=run.session_id,
                flow_boundary=command.config.flow_boundary,
                invocation_mode=AgentInvocationMode(
                    command.invocation_mode or AgentInvocationMode.DELEGATION.value
                ),
            )
            self._tasks_by_run[run_id] = task
        result = await self._result(task, run.session_id, resumed)
        if resumed.state in TERMINAL_RUN_STATES:
            await self._release_run(run_id)
        return result

    async def child_session_owner(
        self, child_session_id: str, *, parent_session_id: str
    ) -> str:
        """Return the durable Agent owner after validating Session ancestry."""

        child = await self.runtime.session_store.get_session(child_session_id)
        current = child
        seen = {child_session_id}
        while current.parent_session_id != parent_session_id:
            parent_id = current.parent_session_id
            if parent_id is None or parent_id in seen:
                raise RuntimeError(
                    "child session does not belong to the active parent session"
                )
            seen.add(parent_id)
            current = await self.runtime.session_store.get_session(parent_id)
        runs = await self.runtime.session_store.list_session_runs(child_session_id)
        if not runs:
            raise RuntimeError("child session has no runs")
        first = min(runs, key=lambda value: (value.created_at, value.run_id))
        command = await self.runtime.session_store.get_start_command(first.run_id)
        return command.agent_id

    async def _result(
        self, task: DelegationTask, session_id: str, run
    ) -> DelegationResult:
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
            child_session_id=session_id,
            child_run_id=run.run_id,
            outcome=run.state,
            content=content,
            error=error,
        )

    @staticmethod
    def _input_text(items) -> str:
        return "\n".join(
            block.text
            for item in items
            for block in item.content
            if isinstance(block, TextBlock)
        )

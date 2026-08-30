"""Bounded orchestration of independently durable child Agent Runs."""

from __future__ import annotations

import asyncio

from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)
from sagents.v2.contracts.principals import RequestContext
from sagents.v2.contracts.run_state import RunState
from sagents.v2.agent.multi_agent.contracts import (
    AgentDescriptor,
    AgentMode,
    ChildRunExecutor,
    DelegationBatch,
    DelegationResult,
    WorkspaceSharingPolicy,
)
from sagents.v2.agent.multi_agent.registry import AgentRegistry


class MultiAgentCoordinator:
    """Validate delegation and run child tasks under an explicit mode policy.

    The coordinator does not create special multi-agent messages. Its executor
    creates real child Sessions/Runs, so each task has independent events,
    cancellation, checkpoints, budgets, and recovery identity.
    """

    def __init__(
        self,
        *,
        mode: AgentMode,
        registry: AgentRegistry,
        executor: ChildRunExecutor,
        max_concurrency: int = 4,
        workspace_policy: WorkspaceSharingPolicy = WorkspaceSharingPolicy.SHARED_PARENT,
    ) -> None:
        if mode not in {AgentMode.FIBRE, AgentMode.TEAM}:
            raise ValueError("multi-agent coordinator requires fibre or team mode")
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        self.mode = mode
        self.registry = registry
        self.executor = executor
        self.workspace_policy = workspace_policy
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._session_owners: dict[str, str] = {}
        self._session_lock = asyncio.Lock()

    async def spawn(self, descriptor: AgentDescriptor) -> AgentDescriptor:
        return await self.registry.spawn(descriptor, owner_mode=self.mode)

    async def delegate(
        self,
        batch: DelegationBatch,
        *,
        parent_run_id: str,
        parent_session_id: str,
        context: RequestContext,
    ) -> tuple[DelegationResult, ...]:
        """Run a delegation batch with bounded concurrency and Session ownership."""

        descriptors = []
        for task in batch.tasks:
            if task.child_session_id == parent_session_id:
                raise self._error(
                    "agent.parent_session_reuse",
                    "a child task cannot execute in the active parent session",
                )
            descriptors.append(await self.registry.get(task.agent_id))

        # Validate all durable Session ownership before any child is started.
        owner_reader = getattr(self.executor, "child_session_owner", None)
        durable_owners: dict[str, str] = {}
        if owner_reader is not None:
            for task in batch.tasks:
                if task.child_session_id is not None:
                    durable_owners[task.child_session_id] = await owner_reader(
                        task.child_session_id,
                        parent_session_id=parent_session_id,
                    )
        async with self._session_lock:
            for task in batch.tasks:
                if task.child_session_id is None:
                    continue
                owner = self._session_owners.get(task.child_session_id)
                owner = owner or durable_owners.get(task.child_session_id)
                if owner is not None and owner != task.agent_id:
                    raise self._error(
                        "agent.child_session_owner_conflict",
                        "child session belongs to a different agent",
                    )

        async def one(task, descriptor):
            async with self._semaphore:
                result = await self.executor.run_child(
                    descriptor,
                    task,
                    parent_run_id=parent_run_id,
                    workspace_policy=self.workspace_policy,
                    context=context,
                )
            async with self._session_lock:
                if result.child_session_id is not None:
                    self._session_owners[result.child_session_id] = task.agent_id
            return result

        settled = await asyncio.gather(
            *(
                one(task, descriptor)
                for task, descriptor in zip(batch.tasks, descriptors, strict=True)
            ),
            return_exceptions=True,
        )
        results: list[DelegationResult] = []
        for task, value in zip(batch.tasks, settled, strict=True):
            if not isinstance(value, BaseException):
                results.append(value)
                continue
            error = (
                value.info
                if isinstance(value, SageV2Error)
                else RuntimeErrorInfo(
                    code="agent.delegation_task_failed",
                    category=ErrorCategory.INTERNAL,
                    message=(
                        "delegation task failed before producing a durable "
                        f"child result: {type(value).__name__}: {value}"
                    ),
                    safe_to_resume=False,
                )
            )
            results.append(
                DelegationResult(
                    task_id=task.task_id,
                    agent_id=task.agent_id,
                    child_session_id=task.child_session_id,
                    child_run_id=None,
                    outcome=RunState.FAILED,
                    error=error,
                )
            )
        return tuple(results)

    @staticmethod
    def _error(code, message):
        return SageV2Error(
            RuntimeErrorInfo(
                code=code,
                category=ErrorCategory.CONFLICT,
                message=message,
                safe_to_resume=True,
            )
        )

"""Host-owned, Run-scoped execution resource bindings."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.principals import RequestContext
from sagents.v2.runtime.execution.sandbox import SandboxGrantIssuer, SandboxHandle

if TYPE_CHECKING:
    from sagents.v2.agent.multi_agent.contracts import WorkspaceSharingPolicy
    from sagents.v2.runtime.execution.lifecycle import (
        ExecutionBindingLifecycleCoordinator,
    )


@dataclass(frozen=True)
class ExecutionBindingRequest:
    """Identity and policy facts a Host uses to allocate one Run binding."""

    run_id: str
    agent_id: str
    context: RequestContext
    parent_run_id: str | None = None
    lifecycle: ExecutionBindingLifecycleCoordinator | None = None
    workspace_policy: WorkspaceSharingPolicy | str = "shared_parent"


@dataclass
class RunExecutionBinding:
    """A sandbox and grant authority owned by exactly one durable Run."""

    run_id: str
    agent_id: str
    workspace_root: str
    workspace_policy: WorkspaceSharingPolicy | str
    sandbox: SandboxHandle
    grant_issuer: SandboxGrantIssuer
    parent_run_id: str | None = None
    _closed: bool = field(default=False, init=False, repr=False)
    _close_task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _close_lock: asyncio.Lock = field(
        default_factory=asyncio.Lock, init=False, repr=False
    )

    def __post_init__(self) -> None:
        if self.sandbox.ref.owner_run_id != self.run_id:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="execution.binding_owner_mismatch",
                    category=ErrorCategory.AUTHORIZATION,
                    message=(
                        "execution binding sandbox owner must equal the durable run_id"
                    ),
                )
            )

    def validate_for(self, request: ExecutionBindingRequest) -> None:
        """Reject Host bindings that do not satisfy the requested identity/policy."""

        if (
            self.run_id != request.run_id
            or self.agent_id != request.agent_id
            or self.parent_run_id != request.parent_run_id
        ):
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="execution.binding_identity_mismatch",
                    category=ErrorCategory.AUTHORIZATION,
                    message="execution binding identity does not match its request",
                )
            )
        actual_policy = getattr(self.workspace_policy, "value", self.workspace_policy)
        requested_policy = getattr(
            request.workspace_policy, "value", request.workspace_policy
        )
        if str(actual_policy) != str(requested_policy):
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="execution.workspace_policy_unsupported",
                    category=ErrorCategory.AUTHORIZATION,
                    message=(
                        f"Host returned workspace policy {actual_policy!r}; "
                        f"requested {requested_policy!r}"
                    ),
                )
            )
        if self.sandbox.ref.tenant_id != request.context.actor.tenant_id:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="execution.binding_tenant_mismatch",
                    category=ErrorCategory.AUTHORIZATION,
                    message="execution binding tenant does not match its request",
                )
            )

    @property
    def closed(self) -> bool:
        return self._closed

    async def close(self) -> None:
        """Release the Host handle exactly once; provider policy owns destruction."""

        async with self._close_lock:
            if self._close_task is None:
                self._close_task = asyncio.create_task(self.sandbox.close())
            close_task = self._close_task
        # Shield the shared close operation so cancellation of one waiter does
        # not trigger a second provider close on retry.
        await asyncio.shield(close_task)
        self._closed = True

    async def on_suspended(self, context: RequestContext) -> None:
        if self.lifecycle is not None:
            await self.lifecycle.suspend(run_id=self.run_id, context=context)


class ExecutionBindingProvider(Protocol):
    """Host port for acquiring actual-Run execution resources."""

    async def acquire(
        self, request: ExecutionBindingRequest
    ) -> RunExecutionBinding: ...

    async def close(self) -> None:
        """Release provider-level resources during Host shutdown."""
        ...


__all__ = [
    "ExecutionBindingProvider",
    "ExecutionBindingRequest",
    "RunExecutionBinding",
]

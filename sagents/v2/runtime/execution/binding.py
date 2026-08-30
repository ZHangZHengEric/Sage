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


@dataclass(frozen=True)
class ExecutionBindingRequest:
    """Identity and policy facts a Host uses to allocate one Run binding."""

    run_id: str
    agent_id: str
    context: RequestContext
    parent_run_id: str | None = None
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
                        "execution binding sandbox owner must equal the durable "
                        "run_id"
                    ),
                )
            )

    @property
    def closed(self) -> bool:
        return self._closed

    async def close(self) -> None:
        """Release the Host handle exactly once; provider policy owns destruction."""

        async with self._close_lock:
            if self._closed:
                return
            await self.sandbox.close()
            self._closed = True


class ExecutionBindingProvider(Protocol):
    """Host port for acquiring actual-Run execution resources."""

    async def acquire(self, request: ExecutionBindingRequest) -> RunExecutionBinding:
        ...

    async def close(self) -> None:
        """Release provider-level resources during Host shutdown."""
        ...


__all__ = [
    "ExecutionBindingProvider",
    "ExecutionBindingRequest",
    "RunExecutionBinding",
]

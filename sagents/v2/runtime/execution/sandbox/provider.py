"""Enforcement ports for v2 filesystem, process, network, and sandbox lifecycle.

Policy decides whether an operation is allowed; an Interaction may obtain human
approval; these Provider interfaces are still responsible for enforcing the
exact signed intent at the resource boundary.
"""

from __future__ import annotations

from typing import Protocol

from sagents.v2.runtime.execution.sandbox.contracts import (
    FileStat,
    NetworkRequest,
    NetworkResult,
    OperationIntent,
    ProcessRequest,
    ProcessResult,
    ResolvedSandboxSpec,
    SandboxCapabilities,
    SandboxCheckpointRef,
    SandboxGrant,
    SandboxRef,
    SandboxSnapshot,
    TerminateMode,
)
from sagents.v2.contracts.principals import RequestContext


class SandboxFileSystem(Protocol):
    def normalize_path(self, path: str) -> str:
        """Resolve a caller path into this sandbox's canonical namespace."""
        ...

    async def read_bytes(
        self, path: str, *, intent: OperationIntent, grant: SandboxGrant
    ) -> bytes: ...

    async def write_bytes(
        self,
        path: str,
        content: bytes,
        *,
        intent: OperationIntent,
        grant: SandboxGrant,
        overwrite: bool = True,
    ) -> FileStat: ...

    async def delete(
        self, path: str, *, intent: OperationIntent, grant: SandboxGrant
    ) -> None: ...

    async def stat(
        self, path: str, *, intent: OperationIntent, grant: SandboxGrant
    ) -> FileStat: ...

    async def list_paths(
        self, path: str, *, intent: OperationIntent, grant: SandboxGrant
    ) -> tuple[FileStat, ...]: ...


class SandboxProcessRuntime(Protocol):
    async def run(
        self,
        request: ProcessRequest,
        *,
        intent: OperationIntent,
        grant: SandboxGrant,
    ) -> ProcessResult: ...


class SandboxNetworkRuntime(Protocol):
    async def request(
        self,
        request: NetworkRequest,
        *,
        intent: OperationIntent,
        grant: SandboxGrant,
    ) -> NetworkResult: ...


class SandboxHandle(Protocol):
    """Run-scoped access to one provisioned or reattached sandbox."""

    ref: SandboxRef
    filesystem: SandboxFileSystem
    process: SandboxProcessRuntime
    network: SandboxNetworkRuntime

    async def status(self) -> SandboxSnapshot: ...
    async def suspend(self) -> SandboxCheckpointRef: ...
    async def close(self) -> None: ...
    async def destroy(self) -> None: ...


class SandboxProvider(Protocol):
    """Provision and recover sandboxes with honestly reported capabilities."""

    async def capabilities(self) -> SandboxCapabilities: ...

    async def provision(
        self, spec: ResolvedSandboxSpec, context: RequestContext, *, run_id: str
    ) -> SandboxHandle: ...

    async def attach(
        self, ref: SandboxRef, context: RequestContext
    ) -> SandboxHandle: ...

    async def inspect(self, ref: SandboxRef) -> SandboxSnapshot: ...

    async def snapshot(self, ref: SandboxRef) -> SandboxCheckpointRef: ...

    async def restore(
        self, checkpoint: SandboxCheckpointRef, context: RequestContext
    ) -> SandboxHandle: ...

    async def terminate(self, ref: SandboxRef, mode: TerminateMode) -> None: ...

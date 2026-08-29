"""SAgents V2 module for runtime/execution/jobs/provider.py."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol

from sagents.v2.contracts.jobs import (
    JobCompletion,
    JobCursor,
    JobHandle,
    JobOutputChunk,
    JobRuntimeCapabilities,
    JobSnapshot,
    JobSpec,
)


JobEmitter = Callable[[str, bytes], Awaitable[None]]
JobRunner = Callable[[JobSpec, JobEmitter, asyncio.Event], Awaitable[JobCompletion]]


class JobRuntime(Protocol):
    async def capabilities(self) -> JobRuntimeCapabilities: ...
    async def submit(self, spec: JobSpec) -> JobHandle: ...
    async def inspect(self, job_id: str) -> JobSnapshot: ...
    async def wait(self, job_id: str) -> JobSnapshot: ...
    async def cancel(self, job_id: str, *, force: bool = False) -> JobSnapshot: ...
    async def read_output(
        self, cursor: JobCursor, *, max_bytes: int = 65536
    ) -> tuple[JobOutputChunk, ...]: ...
    async def handle_run_pause(self, run_id: str) -> tuple[JobSnapshot, ...]: ...
    async def mark_orphaned(self, job_id: str) -> JobSnapshot: ...
    async def adopt(self, job_id: str, *, owner_run_id: str) -> JobSnapshot: ...
    async def close(self) -> None: ...

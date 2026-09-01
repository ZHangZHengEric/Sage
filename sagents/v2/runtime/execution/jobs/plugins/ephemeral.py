"""In-process durable-shape JobRuntime used for deterministic conformance tests."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sagents.v2.runtime.execution.jobs.provider import JobRunner
from sagents.v2.contracts.common import new_id, utc_now
from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)
from sagents.v2.contracts.jobs import (
    JobCursor,
    JobHandle,
    JobOutputChunk,
    JobPauseBehavior,
    JobRuntimeCapabilities,
    JobSnapshot,
    JobSpec,
    JobState,
)


TERMINAL_JOB_STATES = frozenset({JobState.COMPLETED, JobState.FAILED, JobState.KILLED})


@dataclass
class _JobRow:
    spec: JobSpec
    handle: JobHandle
    created_at: datetime
    updated_at: datetime
    state: JobState = JobState.CREATED
    exit_code: int | None = None
    error: RuntimeErrorInfo | None = None
    usage: object | None = None
    output: list[JobOutputChunk] = field(default_factory=list)
    output_size: int = 0
    output_truncated: bool = False
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    completed: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None
    runner: JobRunner | None = None


class InMemoryJobRuntime:
    """Model concurrent Job lifecycle/cursors without cross-process durability."""

    api_version = "2"

    def __init__(
        self,
        runners: Mapping[str, JobRunner],
        *,
        max_concurrent_jobs: int = 32,
        terminal_ttl_seconds: int = 86_400,
        max_retained_terminal_jobs: int = 4096,
        max_retained_output_bytes: int = 256 * 1024 * 1024,
        output_reconnect_window_seconds: int = 300,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if max_concurrent_jobs < 1:
            raise ValueError("max_concurrent_jobs must be positive")
        if terminal_ttl_seconds < 1:
            raise ValueError("terminal_ttl_seconds must be positive")
        if (
            max_retained_terminal_jobs < 0
            or max_retained_output_bytes < 0
            or output_reconnect_window_seconds < 0
        ):
            raise ValueError("terminal retention limits must be non-negative")
        self._runners = dict(runners)
        self._owner_runners: dict[tuple[str, str], JobRunner] = {}
        self._max_concurrent = max_concurrent_jobs
        self._clock = clock
        self._terminal_ttl = timedelta(seconds=terminal_ttl_seconds)
        self._max_retained_terminal_jobs = max_retained_terminal_jobs
        self._max_retained_output_bytes = max_retained_output_bytes
        self._output_reconnect_window = timedelta(
            seconds=output_reconnect_window_seconds
        )
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(max_concurrent_jobs)
        self._rows: dict[str, _JobRow] = {}
        self._idempotency: dict[tuple[str, str], str] = {}
        self._closed = False

    def register_runner(
        self, kind: str, runner: JobRunner, *, owner_run_id: str | None = None
    ) -> None:
        """Bind a local runner globally or to one durable Run identity."""

        self._ensure_open()
        if owner_run_id is None:
            self._runners[kind] = runner
        else:
            self._owner_runners[(owner_run_id, kind)] = runner

    def unregister_runner(
        self,
        kind: str,
        *,
        owner_run_id: str,
        runner: JobRunner | None = None,
    ) -> None:
        """Release a Run-scoped runner without removing a newer replacement."""

        key = (owner_run_id, kind)
        current = self._owner_runners.get(key)
        if current is None or (runner is not None and current is not runner):
            return
        self._owner_runners.pop(key, None)

    async def capabilities(self) -> JobRuntimeCapabilities:
        return JobRuntimeCapabilities(
            durable_across_process_restart=False,
            supports_reconnect=False,
            supports_adoption=True,
            supports_suspend=False,
            supports_output_cursor=True,
            supports_terminal_purge=True,
            supports_automatic_terminal_retention=True,
            max_concurrent_jobs=self._max_concurrent,
            terminal_ttl_seconds=int(self._terminal_ttl.total_seconds()),
            max_retained_terminal_jobs=self._max_retained_terminal_jobs,
            max_retained_output_bytes=self._max_retained_output_bytes,
            output_reconnect_window_seconds=int(
                self._output_reconnect_window.total_seconds()
            ),
        )

    async def submit(self, spec: JobSpec) -> JobHandle:
        async with self._lock:
            self._ensure_open()
            self._sweep_terminal_locked()
            key = (spec.owner_run_id, spec.idempotency_key)
            existing = self._idempotency.get(key)
            if existing is not None:
                return self._snapshot_handle(self._rows[existing])
            runner = self._owner_runners.get(
                (spec.owner_run_id, spec.kind)
            ) or self._runners.get(spec.kind)
            if runner is None:
                raise self._error(
                    "job.kind_unsupported",
                    ErrorCategory.VALIDATION,
                    f"no runner is registered for job kind {spec.kind!r}",
                )
            if spec.pause_behavior == JobPauseBehavior.SUSPEND:
                raise self._error(
                    "job.pause_behavior_unsupported",
                    ErrorCategory.VALIDATION,
                    "in-memory jobs cannot be frozen and resumed",
                )
            now = self._clock()
            job_id = new_id("job")
            handle = JobHandle(
                job_id=job_id,
                owner_run_id=spec.owner_run_id,
                kind=spec.kind,
                state=JobState.CREATED,
                pause_behavior=spec.pause_behavior,
                execution_affinity=spec.execution_affinity,
                output_cursor=JobCursor(job_id=job_id, offset=0),
            )
            row = _JobRow(
                spec=spec,
                handle=handle,
                created_at=now,
                updated_at=now,
                runner=runner,
            )
            self._rows[job_id] = row
            self._idempotency[key] = job_id
            row.task = asyncio.create_task(
                self._execute(job_id), name=f"sage-job:{job_id}"
            )
            return handle

    async def inspect(self, job_id: str) -> JobSnapshot:
        async with self._lock:
            return self._snapshot(self._row(job_id))

    async def wait(self, job_id: str) -> JobSnapshot:
        async with self._lock:
            row = self._row(job_id)
            completed = row.completed
        await completed.wait()
        return await self.inspect(job_id)

    async def cancel(self, job_id: str, *, force: bool = False) -> JobSnapshot:
        async with self._lock:
            row = self._row(job_id)
            if row.state in TERMINAL_JOB_STATES:
                return self._snapshot(row)
            row.state = JobState.STOPPING
            row.updated_at = self._clock()
            row.cancel_event.set()
            task = row.task
            if task is not None:
                task.cancel()
        if task is not None:
            try:
                await task
            except asyncio.CancelledError:
                pass
        async with self._lock:
            row = self._row(job_id)
            if row.state not in TERMINAL_JOB_STATES:
                row.state = JobState.KILLED
                row.updated_at = self._clock()
                row.completed.set()
        return await self.inspect(job_id)

    async def read_output(
        self, cursor: JobCursor, *, max_bytes: int = 65536
    ) -> tuple[JobOutputChunk, ...]:
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        async with self._lock:
            row = self._row(cursor.job_id)
            result: list[JobOutputChunk] = []
            remaining = max_bytes
            for chunk in row.output:
                if chunk.next_offset <= cursor.offset:
                    continue
                start = max(0, cursor.offset - chunk.offset)
                data = chunk.data[start : start + remaining]
                if not data:
                    continue
                offset = chunk.offset + start
                result.append(
                    chunk.model_copy(
                        update={
                            "offset": offset,
                            "next_offset": offset + len(data),
                            "data": data,
                        }
                    )
                )
                remaining -= len(data)
                if remaining == 0:
                    break
            return tuple(result)

    async def handle_run_pause(self, run_id: str) -> tuple[JobSnapshot, ...]:
        async with self._lock:
            job_ids = [
                job_id
                for job_id, row in self._rows.items()
                if row.spec.owner_run_id == run_id
                and row.state not in TERMINAL_JOB_STATES
            ]
            cancel_ids = [
                job_id
                for job_id in job_ids
                if self._rows[job_id].spec.pause_behavior == JobPauseBehavior.CANCEL
            ]
        for job_id in cancel_ids:
            await self.cancel(job_id)
        return tuple(
            await asyncio.gather(*(self.inspect(job_id) for job_id in job_ids))
        )

    async def list_run_jobs(self, run_id: str) -> tuple[JobSnapshot, ...]:
        async with self._lock:
            self._sweep_terminal_locked()
            return tuple(
                self._snapshot(row)
                for row in self._rows.values()
                if row.spec.owner_run_id == run_id
            )

    async def mark_orphaned(self, job_id: str) -> JobSnapshot:
        async with self._lock:
            row = self._row(job_id)
            if row.state not in {JobState.RUNNING, JobState.STOPPING}:
                raise self._error(
                    "job.invalid_transition",
                    ErrorCategory.CONFLICT,
                    f"cannot orphan job in state {row.state.value}",
                )
            row.state = JobState.ORPHANED
            row.updated_at = self._clock()
            return self._snapshot(row)

    async def adopt(self, job_id: str, *, owner_run_id: str) -> JobSnapshot:
        async with self._lock:
            row = self._row(job_id)
            if row.state != JobState.ORPHANED:
                raise self._error(
                    "job.invalid_transition",
                    ErrorCategory.CONFLICT,
                    "only orphaned jobs can be adopted",
                )
            if row.spec.owner_run_id != owner_run_id:
                raise self._error(
                    "job.owner_conflict",
                    ErrorCategory.AUTHORIZATION,
                    "job owner_run_id does not match",
                )
            row.state = JobState.RUNNING
            row.updated_at = self._clock()
            return self._snapshot(row)

    async def purge_terminal(self, *, owner_run_id: str) -> int:
        """Forget settled jobs after the host's replay/output retention horizon."""

        async with self._lock:
            job_ids = {
                job_id
                for job_id, row in self._rows.items()
                if row.spec.owner_run_id == owner_run_id
                and row.state in TERMINAL_JOB_STATES
            }
            for job_id in job_ids:
                self._rows.pop(job_id, None)
            for key, job_id in tuple(self._idempotency.items()):
                if job_id in job_ids:
                    self._idempotency.pop(key, None)
            return len(job_ids)

    async def close(self) -> None:
        async with self._lock:
            self._closed = True
            ids = [
                job_id
                for job_id, row in self._rows.items()
                if row.state not in TERMINAL_JOB_STATES
            ]
        for job_id in ids:
            await self.cancel(job_id, force=True)

    async def _execute(self, job_id: str) -> None:
        row = self._rows[job_id]
        try:
            async with self._semaphore:
                async with self._lock:
                    if row.cancel_event.is_set():
                        raise asyncio.CancelledError
                    row.state = JobState.RUNNING
                    row.updated_at = self._clock()

                async def emit(stream: str, data: bytes) -> None:
                    if stream not in {"stdout", "stderr", "progress"}:
                        raise ValueError(f"unsupported job output stream {stream!r}")
                    if not isinstance(data, bytes):
                        raise TypeError("job output must be bytes")
                    async with self._lock:
                        if row.cancel_event.is_set():
                            raise asyncio.CancelledError
                        maximum = row.spec.max_output_bytes
                        accepted = data
                        if maximum is not None:
                            available = max(0, maximum - row.output_size)
                            accepted = data[:available]
                            if len(accepted) < len(data):
                                row.output_truncated = True
                        if accepted:
                            offset = row.output_size
                            row.output.append(
                                JobOutputChunk(
                                    job_id=job_id,
                                    stream=stream,
                                    offset=offset,
                                    next_offset=offset + len(accepted),
                                    data=accepted,
                                    occurred_at=self._clock(),
                                )
                            )
                            row.output_size += len(accepted)
                            row.updated_at = self._clock()

                assert row.runner is not None
                completion = await row.runner(row.spec, emit, row.cancel_event)
                async with self._lock:
                    row.exit_code = completion.exit_code
                    row.usage = completion.usage
                    row.state = JobState.COMPLETED
                    row.updated_at = self._clock()
        except asyncio.CancelledError:
            async with self._lock:
                row.state = JobState.KILLED
                row.updated_at = self._clock()
        except Exception as exc:
            async with self._lock:
                row.error = RuntimeErrorInfo(
                    code="job.runner_failed",
                    category=ErrorCategory.PROVIDER_PERMANENT,
                    message=str(exc),
                    safe_to_resume=True,
                )
                row.state = JobState.FAILED
                row.updated_at = self._clock()
        finally:
            row.completed.set()
            async with self._lock:
                self._sweep_terminal_locked()

    def _sweep_terminal_locked(self) -> int:
        terminal = sorted(
            (
                row
                for row in self._rows.values()
                if row.state in TERMINAL_JOB_STATES
            ),
            key=lambda row: (row.updated_at, row.handle.job_id),
        )
        now = self._clock()
        purge_ids = {
            row.handle.job_id
            for row in terminal
            if now - row.updated_at
            >= max(self._terminal_ttl, self._output_reconnect_window)
        }
        retained = [row for row in terminal if row.handle.job_id not in purge_ids]
        eligible = [
            row
            for row in retained
            if now - row.updated_at >= self._output_reconnect_window
        ]
        while len(retained) > self._max_retained_terminal_jobs and eligible:
            removed = eligible.pop(0)
            retained.remove(removed)
            purge_ids.add(removed.handle.job_id)
        retained_output = sum(row.output_size for row in retained)
        eligible = [row for row in eligible if row in retained]
        while eligible and retained_output > self._max_retained_output_bytes:
            removed = eligible.pop(0)
            retained.remove(removed)
            purge_ids.add(removed.handle.job_id)
            retained_output -= removed.output_size
        if not purge_ids:
            return 0
        for job_id in purge_ids:
            self._rows.pop(job_id, None)
        for key, job_id in tuple(self._idempotency.items()):
            if job_id in purge_ids:
                self._idempotency.pop(key, None)
        return len(purge_ids)

    def _snapshot_handle(self, row: _JobRow) -> JobHandle:
        return row.handle.model_copy(
            update={
                "state": row.state,
                "output_cursor": JobCursor(
                    job_id=row.handle.job_id, offset=row.output_size
                ),
            }
        )

    def _snapshot(self, row: _JobRow) -> JobSnapshot:
        handle = self._snapshot_handle(row)
        from sagents.v2.contracts.items import UsageSummary

        return JobSnapshot(
            **handle.model_dump(),
            created_at=row.created_at,
            updated_at=row.updated_at,
            exit_code=row.exit_code,
            usage=row.usage if row.usage is not None else UsageSummary(),
            error=row.error,
        )

    def _row(self, job_id: str) -> _JobRow:
        try:
            return self._rows[job_id]
        except KeyError as exc:
            raise self._error(
                "job.not_found",
                ErrorCategory.VALIDATION,
                f"job {job_id!r} was not found",
            ) from exc

    def _ensure_open(self) -> None:
        if self._closed:
            raise self._error(
                "job.runtime_closed",
                ErrorCategory.CANCELLED,
                "job runtime is closed",
            )

    @staticmethod
    def _error(code: str, category: ErrorCategory, message: str) -> SageV2Error:
        return SageV2Error(
            RuntimeErrorInfo(
                code=code,
                category=category,
                message=message,
                safe_to_resume=True,
            )
        )

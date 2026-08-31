# pyright: strict
"""Single-process worker dispatcher backed by the Scheduler lease contract."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta

from sagents.v2.contracts.principals import RequestContext
from sagents.v2.contracts.run_state import (
    RunSnapshot,
    RunState,
    TERMINAL_RUN_STATES,
)
from sagents.v2.contracts.common import utc_now
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.runtime.execution.scheduler import (
    LeaseReleaseReason,
    Scheduler,
    WorkItem,
    WorkerLease,
)


@dataclass
class _DispatchRequest:
    agent: object
    context: RequestContext
    resume: bool
    result: asyncio.Future[RunSnapshot]
    recovered: bool = False


class LocalWorkerDispatcher:
    """Drive accepted Runs under bounded, renewable Scheduler leases."""

    def __init__(
        self,
        scheduler: Scheduler,
        *,
        max_concurrent_runs: int = 8,
        max_concurrent_runs_per_tenant: int = 2,
        lease_seconds: float = 30.0,
        lease_scope_factory=None,
    ) -> None:
        if max_concurrent_runs < 1 or max_concurrent_runs_per_tenant < 1:
            raise ValueError("dispatcher concurrency limits must be positive")
        if lease_seconds <= 0:
            raise ValueError("dispatcher lease_seconds must be positive")
        self.scheduler = scheduler
        self.max_concurrent_runs = max_concurrent_runs
        self.max_concurrent_runs_per_tenant = max_concurrent_runs_per_tenant
        self.lease_duration = timedelta(seconds=lease_seconds)
        self.lease_scope_factory = lease_scope_factory
        self._requests: dict[str, _DispatchRequest] = {}
        self._workers: list[asyncio.Task[None]] = []
        self._active_tenants: dict[str | None, int] = {}
        self._recovery_agent = None
        self._closed = False

    def attach_recovery_agent(self, agent) -> None:
        """Bind the Application Agent used for durable orphan WorkItems."""

        if self._recovery_agent is not None and self._recovery_agent is not agent:
            raise RuntimeError("dispatcher recovery Agent is already attached")
        self._recovery_agent = agent

    async def start(self) -> None:
        if self._closed:
            raise RuntimeError("local worker dispatcher is closed")
        self._workers = [worker for worker in self._workers if not worker.done()]
        if self._workers:
            return
        self._workers = [
            asyncio.create_task(self._worker(index), name=f"sage-worker:{index}")
            for index in range(self.max_concurrent_runs)
        ]

    async def submit(
        self,
        agent,
        handle,
        context: RequestContext,
        *,
        resume: bool = False,
    ) -> asyncio.Future[RunSnapshot]:
        if self._closed:
            raise RuntimeError("local worker dispatcher is closed")
        await self.start()
        current = self._requests.get(handle.run_id)
        if current is not None:
            return current.result
        loop = asyncio.get_running_loop()
        result: asyncio.Future[RunSnapshot] = loop.create_future()
        request = _DispatchRequest(
            agent=agent,
            context=context,
            resume=resume,
            result=result,
        )
        self._requests[handle.run_id] = request
        try:
            revision = getattr(handle, "revision", None)
            if revision is None:
                revision = getattr(handle, "run_revision", 0)
            accepted = await self.scheduler.submit(
                WorkItem(
                    work_id=f"work-{handle.run_id}",
                    run_id=handle.run_id,
                    tenant_id=context.actor.tenant_id,
                    priority=0,
                    available_at=utc_now(),
                    idempotency_key=(
                        f"run:{handle.run_id}:"
                        f"{'resume' if resume else 'start'}:{revision}"
                    ),
                    payload={
                        "resume": resume,
                        "request_context": context.model_dump(mode="json"),
                    },
                )
            )
            if not accepted:
                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="scheduler.duplicate_submission",
                        category=ErrorCategory.CONFLICT,
                        message="scheduler rejected a duplicate WorkItem submission",
                        safe_to_resume=True,
                    )
                )
        except Exception:
            self._requests.pop(handle.run_id, None)
            raise
        return result

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        workers, self._workers = self._workers, []
        for worker in workers:
            worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        for run_id, request in tuple(self._requests.items()):
            if not request.result.done():
                await self._finish_shutdown_request(run_id, request)
        self._requests.clear()

    async def _worker(self, index: int) -> None:
        worker_id = f"local-{index}"
        while True:
            lease = await self.scheduler.claim(
                worker_id,
                lease_duration=self.lease_duration,
                wait_timeout=1.0,
            )
            if lease is None:
                continue
            tenant = lease.work.tenant_id
            if self._active_tenants.get(tenant, 0) >= self.max_concurrent_runs_per_tenant:
                await self.scheduler.release(
                    lease,
                    LeaseReleaseReason.WORKER_SHUTDOWN,
                    requeue=True,
                )
                await asyncio.sleep(0)
                continue
            request = self._requests.get(lease.work.run_id)
            if request is None:
                request = self._restore_request(lease)
                if request is None:
                    await self.scheduler.release(
                        lease, LeaseReleaseReason.CANCELLED, requeue=False
                    )
                    continue
                self._requests[lease.work.run_id] = request
            self._active_tenants[tenant] = self._active_tenants.get(tenant, 0) + 1
            renewer = asyncio.create_task(self._renew(lease))
            execution = None
            snapshot = None
            try:
                scope = (
                    self.lease_scope_factory(lease)
                    if self.lease_scope_factory is not None
                    else _NullAsyncScope()
                )
                async with scope:
                    if request.recovered:
                        recovered = await request.agent.runtime.get_run(
                            lease.work.run_id
                        )
                        if (
                            recovered.state in TERMINAL_RUN_STATES
                            or recovered.state == RunState.SUSPENDED
                        ):
                            snapshot = recovered
                            execution = None
                        elif recovered.state in {
                            RunState.RUNNING,
                            RunState.SUSPEND_REQUESTED,
                        }:
                            error = RuntimeErrorInfo(
                                code="execution.worker_restarted",
                                category=ErrorCategory.RESOURCE_LOST,
                                message=(
                                    "worker process restarted without a safe checkpoint"
                                ),
                                safe_to_resume=True,
                            )
                            snapshot = await request.agent.runtime.fail_run(
                                run_id=recovered.run_id,
                                expected_revision=recovered.revision,
                                error=error,
                                context=request.context,
                                idempotency_key=(
                                    f"worker-restarted:{recovered.run_id}:"
                                    f"{recovered.revision}"
                                ),
                            )
                            execution = None
                        else:
                            request.resume = recovered.state == RunState.RESUMING
                    if snapshot is None:
                        execution = request.agent._ensure_execution(
                            lease.work.run_id,
                            request.context,
                            resume=request.resume,
                        )
                        done, _ = await asyncio.wait(
                            {execution, renewer}, return_when=asyncio.FIRST_COMPLETED
                        )
                        if renewer in done:
                            renewal_error = renewer.exception()
                            execution.cancel()
                            await asyncio.gather(execution, return_exceptions=True)
                            if renewal_error is None:
                                renewal_error = RuntimeError(
                                    "scheduler lease renewer stopped"
                                )
                            await request.agent._fail_driver_crash(
                                lease.work.run_id,
                                renewal_error,
                                request.context,
                            )
                            raise renewal_error
                        snapshot = execution.result()
                reason = {
                    RunState.COMPLETED: LeaseReleaseReason.COMPLETED,
                    RunState.FAILED: LeaseReleaseReason.FAILED,
                    RunState.CANCELLED: LeaseReleaseReason.CANCELLED,
                    RunState.SUSPENDED: LeaseReleaseReason.SUSPENDED,
                }.get(snapshot.state, LeaseReleaseReason.FAILED)
                await self.scheduler.release(lease, reason, requeue=False)
                if not request.result.done():
                    request.result.set_result(snapshot)
            except asyncio.CancelledError:
                if execution is not None and not execution.done():
                    execution.cancel()
                    await asyncio.gather(execution, return_exceptions=True)
                await self._finish_shutdown_request(
                    lease.work.run_id, request, lease=lease
                )
                raise
            except Exception as exc:
                if not request.result.done():
                    request.result.set_exception(exc)
                try:
                    await self.scheduler.release(
                        lease, LeaseReleaseReason.FAILED, requeue=False
                    )
                except Exception:
                    # A release failure must not permanently shrink the pool.
                    # The Scheduler will reap an active lease if one remains.
                    pass
            finally:
                renewer.cancel()
                await asyncio.gather(renewer, return_exceptions=True)
                self._active_tenants[tenant] -= 1
                if self._active_tenants[tenant] == 0:
                    self._active_tenants.pop(tenant)
                self._requests.pop(lease.work.run_id, None)

    def _restore_request(self, lease: WorkerLease) -> _DispatchRequest | None:
        if self._recovery_agent is None:
            return None
        raw_context = lease.work.payload.get("request_context")
        if not isinstance(raw_context, dict):
            return None
        context = RequestContext.model_validate(raw_context)
        result = asyncio.get_running_loop().create_future()
        # Recovered work has no in-process caller awaiting this Future.
        result.add_done_callback(self._consume_detached_result)
        return _DispatchRequest(
            agent=self._recovery_agent,
            context=context,
            resume=bool(lease.work.payload.get("resume")),
            result=result,
            recovered=True,
        )

    async def _finish_shutdown_request(
        self,
        run_id: str,
        request: _DispatchRequest,
        *,
        lease: WorkerLease | None = None,
    ) -> None:
        """Resolve a submitted Future even when failure recording is unavailable."""

        try:
            snapshot = await request.agent._fail_driver_crash(
                run_id,
                self._shutdown_error(),
                request.context,
            )
        except BaseException as exc:
            if not request.result.done():
                request.result.set_exception(exc)
        else:
            if not request.result.done():
                request.result.set_result(snapshot)
        finally:
            if lease is not None:
                try:
                    await self.scheduler.release(
                        lease, LeaseReleaseReason.FAILED, requeue=False
                    )
                except BaseException:
                    # Expiry/reaping remains the final fallback, but shutdown
                    # must never strand the caller's Future on release failure.
                    pass

    async def _renew(self, lease) -> None:
        delay = max(self.lease_duration.total_seconds() / 3, 0.05)
        current = lease
        while True:
            await asyncio.sleep(delay)
            current = await self.scheduler.renew(
                current, lease_duration=self.lease_duration
            )

    @staticmethod
    def _consume_detached_result(result: asyncio.Future[RunSnapshot]) -> None:
        """Retrieve orphan completion errors so asyncio does not log them later."""

        if not result.cancelled():
            result.exception()

    @staticmethod
    def _shutdown_error() -> SageV2Error:
        return SageV2Error(
            RuntimeErrorInfo(
                code="scheduler.worker_shutdown",
                category=ErrorCategory.RESOURCE_LOST,
                message="local worker stopped before the Run completed",
                safe_to_resume=True,
            )
        )


class _NullAsyncScope:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

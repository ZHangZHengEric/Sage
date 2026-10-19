# pyright: strict
"""Single-process worker dispatcher backed by the Scheduler lease contract."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from datetime import datetime, timedelta
from collections.abc import Awaitable, Callable
from typing import Any

from sagents.v2.contracts.commands import CancelRun
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
    SchedulerClaimPolicy,
    Scheduler,
    WorkItem,
    WorkerLease,
)
from sagents.v2.runtime.observability.logs import get_logger

from sagents.v2.runtime.execution.ownership import (
    ACTIVE_OWNERSHIP,
    ExecutionOwnership,
    is_lease_loss,
    revoke_ownership,
    require_execution_ownership,
)

DEFAULT_LEASE_SECONDS = 48 * 60 * 60


_LOGGER = get_logger(__name__)


@dataclass
class _DispatchRequest:
    agent: object
    context: RequestContext
    resume: bool
    result: asyncio.Future[RunSnapshot]
    recovered: bool = False
    claimed: bool = False


@dataclass
class _CleanupRequest:
    operation: Callable[[], Awaitable[Any]]
    result: asyncio.Future[Any]
    claimed: bool = False


def _agent_method(agent: Any, public: str, private: str):
    method = getattr(agent, public, None)
    if method is None:
        method = getattr(agent, private)
    return method


class LocalWorkerDispatcher:
    """Drive accepted Runs under bounded, renewable Scheduler leases."""

    def __init__(
        self,
        scheduler: Scheduler,
        *,
        max_concurrent_runs: int = 8,
        max_concurrent_runs_per_tenant: int = 2,
        lease_seconds: float = DEFAULT_LEASE_SECONDS,
        lease_scope_factory=None,
        preserve_runs_on_shutdown: bool = True,
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
        self.preserve_runs_on_shutdown = preserve_runs_on_shutdown
        self._supports_deferred_work = "available_at" in inspect.signature(scheduler.release).parameters
        self._requests: dict[str, _DispatchRequest] = {}
        self._run_gates: dict[str, tuple[asyncio.Lock, int]] = {}
        self._cleanup_requests: dict[str, _CleanupRequest] = {}
        self._workers: list[asyncio.Task[None]] = []
        self._claim_policy = SchedulerClaimPolicy(
            max_active_per_tenant=max_concurrent_runs_per_tenant
        )
        self.recovery_filter = None
        self._recovery_agent = None
        self._lifecycle = asyncio.Condition()
        self._submissions_inflight = 0
        self._closed = False
        self._claim_error: Exception | None = None

    def attach_recovery_agent(self, agent, *, replace: bool = False) -> None:
        """Bind the Application Agent used for durable orphan WorkItems."""

        if (
            self._recovery_agent is not None
            and self._recovery_agent is not agent
            and not replace
        ):
            raise RuntimeError("dispatcher recovery Agent is already attached")
        self._recovery_agent = agent

    async def start(self, *, recover: bool = True) -> None:
        async with self._lifecycle:
            await self._start_locked(recover=recover)

    async def _start_locked(self, *, recover: bool) -> None:
        if self._closed:
            raise RuntimeError("local worker dispatcher is closed")
        if self._claim_error is not None:
            raise self._claim_error
        self._workers = [worker for worker in self._workers if not worker.done()]
        if self._workers:
            return
        if recover:
            await self._restore_dispatchable_work()
        self._workers = [
            asyncio.create_task(self._worker(index), name=f"sage-worker:{index}")
            for index in range(self.max_concurrent_runs)
        ]

    async def refresh_recovery(self) -> None:
        """Restore newly available Agent revisions under the dispatcher lock."""
        async with self._lifecycle:
            await self._restore_dispatchable_work()

    async def _restore_dispatchable_work(self) -> None:
        """Rebuild missing Scheduler entries from authoritative Run intents."""

        if self._recovery_agent is None:
            return
        store = self._recovery_agent.runtime.session_store
        reader = getattr(store, "list_dispatchable_runs", None)
        if reader is None:
            return
        for intent in await reader():
            if self.recovery_filter is not None and not self.recovery_filter(
                intent.run
            ):
                continue
            try:
                work = self._work_item(
                    intent.run, intent.context,
                    resume=intent.run.state == RunState.RESUMING,
                )
                wake_at = await self._automatic_resume_at(store, intent.run.run_id)
                if wake_at is not None and intent.run.state == RunState.RUNNING:
                    work = work.model_copy(update={"available_at": wake_at})
                await self.scheduler.submit(
                    work
                )
            except SageV2Error as exc:
                if exc.info.code != "scheduler.work_id_conflict":
                    raise

    async def submit(
        self,
        agent,
        handle,
        context: RequestContext,
        *,
        resume: bool = False,
    ) -> asyncio.Future[RunSnapshot]:
        while True:
            predecessor = None
            async with self._lifecycle:
                await self._start_locked(recover=False)
                current = self._requests.get(handle.run_id)
                if current is not None:
                    if resume and current.claimed:
                        # A reply may be accepted while the previous suspended
                        # drive is still releasing resources and its lease.
                        # Wait for that generation, then schedule the durable
                        # RESUMING state instead of returning its old result.
                        predecessor = current.result
                    else:
                        return current.result
                else:
                    loop = asyncio.get_running_loop()
                    result: asyncio.Future[RunSnapshot] = loop.create_future()
                    request = _DispatchRequest(agent=agent, context=context,
                        resume=resume, result=result)
                    self._requests[handle.run_id] = request
                    self._submissions_inflight += 1
                    break
            try:
                await asyncio.shield(predecessor)
            except Exception:
                # Durable state decides whether the accepted resume survives a
                # predecessor cleanup failure. Never replay a tool here.
                pass
            handle = await agent.runtime.get_run(handle.run_id)
            if handle.state != RunState.RESUMING:
                result = asyncio.get_running_loop().create_future()
                result.set_result(handle)
                return result
        try:
            revision = getattr(handle, "revision", None)
            if revision is None:
                revision = getattr(handle, "run_revision", 0)
            await self.scheduler.submit(
                self._work_item(handle, context, resume=resume, revision=revision)
            )
        except BaseException:
            async with self._lifecycle:
                self._discard_request(handle.run_id, request)
            raise
        finally:
            async with self._lifecycle:
                self._submissions_inflight -= 1
                self._lifecycle.notify_all()
        return result

    async def submit_cleanup(
        self,
        *,
        run_id: str,
        context: RequestContext,
        generation: int,
        attempt: int = 0,
        operation: Callable[[], Awaitable[Any]],
    ) -> asyncio.Future[Any]:
        """Run one resource cleanup under the same per-Run Scheduler fence."""

        async with self._lifecycle:
            await self._start_locked(recover=False)
            work_id = f"cleanup-{run_id}-{generation}-{attempt}"
            current = self._cleanup_requests.get(work_id)
            if current is not None:
                return current.result
            result = asyncio.get_running_loop().create_future()
            request = _CleanupRequest(
                operation=operation,
                result=result,
            )
            self._cleanup_requests[work_id] = request
            self._submissions_inflight += 1
        try:
            await self.scheduler.submit(
                WorkItem(
                    work_id=work_id,
                    run_id=run_id,
                    tenant_id=context.actor.tenant_id,
                    priority=-10,
                    available_at=utc_now(),
                    idempotency_key=(
                        f"sandbox-cleanup:{run_id}:{generation}:{attempt}"
                    ),
                    payload={"kind": "sandbox_cleanup", "generation": generation},
                )
            )
        except BaseException:
            async with self._lifecycle:
                if self._cleanup_requests.get(work_id) is request:
                    self._cleanup_requests.pop(work_id, None)
            raise
        finally:
            async with self._lifecycle:
                self._submissions_inflight -= 1
                self._lifecycle.notify_all()
        return result

    @staticmethod
    def _work_item(handle, context, *, resume: bool, revision=None) -> WorkItem:
        if revision is None:
            revision = getattr(handle, "revision", None)
        if revision is None:
            revision = getattr(handle, "run_revision", 0)
        return WorkItem(
            work_id=f"work-{handle.run_id}",
            run_id=handle.run_id,
            tenant_id=context.actor.tenant_id,
            priority=0,
            available_at=utc_now(),
            idempotency_key=(
                f"run:{handle.run_id}:{'resume' if resume else 'start'}:{revision}"
            ),
            payload={
                "resume": resume,
                "request_context": context.model_dump(mode="json"),
            },
        )

    async def close(self) -> None:
        async with self._lifecycle:
            if self._closed:
                return
            self._closed = True
            while self._submissions_inflight:
                await self._lifecycle.wait()
            workers, self._workers = self._workers, []
        for worker in workers:
            worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        for run_id, request in tuple(self._requests.items()):
            if not request.result.done():
                await self._finish_shutdown_request(run_id, request)
        self._requests.clear()
        for request in self._cleanup_requests.values():
            if not request.result.done():
                request.result.cancel()
        self._cleanup_requests.clear()

    async def _worker(self, index: int) -> None:
        worker_id = f"local-{index}"
        retry_delay = 0.1
        while self._claim_error is None:
            try:
                lease = await self.scheduler.claim(
                    worker_id,
                    lease_duration=self.lease_duration,
                    policy=self._claim_policy,
                    wait_timeout=1.0,
                )
            except Exception as exc:
                transient = isinstance(exc, (OSError, TimeoutError)) or (
                    isinstance(exc, SageV2Error)
                    and exc.info.retryable
                    and exc.info.code != "scheduler.persistence_failed"
                )
                if not transient:
                    # A dead worker must not leave accepted callers waiting
                    # forever when the scheduler requires operator recovery.
                    self._claim_error = exc
                    for requests in (self._requests, self._cleanup_requests):
                        for key, request in tuple(requests.items()):
                            if request.claimed:
                                continue
                            if not request.result.done():
                                request.result.set_exception(exc)
                            requests.pop(key, None)
                    _LOGGER.exception(
                        "scheduler.claim.failed",
                        "scheduler claim failed permanently",
                        exc,
                    )
                    return
                _LOGGER.warning(
                    "scheduler.claim.retry",
                    "scheduler claim failed; retrying",
                    retry_delay_seconds=retry_delay,
                )
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 5.0)
                continue
            retry_delay = 0.1
            if lease is None:
                await self._settle_deferred_controls()
                continue
            cleanup = self._cleanup_requests.get(lease.work.work_id)
            if cleanup is not None:
                cleanup.claimed = True
                await self._execute_cleanup(lease, cleanup)
                continue
            request = self._requests.get(lease.work.run_id)
            if request is None:
                request = self._restore_request(lease)
                if request is None:
                    try:
                        await self._release_lease(
                            lease, LeaseReleaseReason.CANCELLED, requeue=False
                        )
                    except Exception as exc:
                        # No execution started. An unreleased orphan can expire,
                        # but must not take a worker out of the pool.
                        _LOGGER.exception(
                            "scheduler.orphan_release.failed",
                            "failed to release orphan work",
                            exc,
                            run_id=lease.work.run_id,
                        )
                    continue
                self._requests[lease.work.run_id] = request
            request.claimed = True
            if lease.work.attempt > 1:
                request.recovered = True
            ownership = ExecutionOwnership(
                run_id=lease.work.run_id, supports_deferred_work=self._supports_deferred_work,
            )
            ownership_token = ACTIVE_OWNERSHIP.set(ownership)
            renewer = asyncio.create_task(self._renew(lease))
            gate, users = self._run_gates.get(lease.work.run_id, (asyncio.Lock(), 0))
            self._run_gates[lease.work.run_id] = (gate, users + 1)
            gate_held = False
            requeued = False
            execution = None
            snapshot = None
            try:
                await gate.acquire()
                gate_held = True
                scope = (
                    self.lease_scope_factory(lease)
                    if self.lease_scope_factory is not None
                    else _NullAsyncScope()
                )
                # Old queue entries can outlive an unavailable Agent revision.
                # Release outside the fenced store scope; preserve the intent
                # and queue entry without entering that revision's driver.
                if request.recovered and self.recovery_filter is not None:
                    current = await request.agent.runtime.get_run(lease.work.run_id)
                    if current.state not in TERMINAL_RUN_STATES and not self.recovery_filter(current):
                        await self._release_lease(
                            lease, LeaseReleaseReason.DEFERRED,
                            requeue=True, available_at=utc_now() + timedelta(seconds=60),
                        )
                        requeued = True
                        self._discard_request(lease.work.run_id, request)
                        if not request.result.done():
                            request.result.set_result(current)
                        continue
                async with scope:
                    # A crash can happen after the checkpoint but before the
                    # lease is delayed. Honor the durable timestamp on takeover.
                    runtime = getattr(request.agent, "runtime", None)
                    if request.recovered and runtime is not None and self._supports_deferred_work:
                        wake_at = await self._automatic_resume_at(runtime.session_store, lease.work.run_id)
                        current = await runtime.get_run(lease.work.run_id)
                        if wake_at is not None and wake_at > utc_now() and current.state == RunState.RUNNING:
                            snapshot = current
                    if request.recovered and snapshot is None:
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
                            recover_barrier = getattr(
                                request.agent, "recover_interrupted_run", None
                            ) or getattr(
                                request.agent, "_recover_interrupted_run", None
                            )
                            if recover_barrier is not None:
                                try:
                                    execution = asyncio.create_task(
                                        recover_barrier(
                                            recovered.run_id, request.context
                                        )
                                    )
                                    done, _ = await asyncio.wait(
                                        {execution, renewer},
                                        return_when=asyncio.FIRST_COMPLETED,
                                    )
                                    if renewer in done:
                                        revoke_ownership()
                                        execution.cancel()
                                        await asyncio.gather(
                                            execution, return_exceptions=True
                                        )
                                        raise self._renewal_error(renewer)
                                    snapshot = execution.result()
                                except Exception as exc:
                                    if ownership.revoked or is_lease_loss(exc):
                                        raise
                                    if await self._defer_recovery_error(lease, request, exc):
                                        requeued = True
                                        continue
                                    error = RuntimeErrorInfo(
                                        code="execution.barrier_recovery_failed",
                                        category=ErrorCategory.UNCERTAIN_SIDE_EFFECT,
                                        message=(
                                            "worker restarted after a possible side "
                                            "effect and barrier recovery failed"
                                        ),
                                        safe_to_resume=False,
                                        metadata={"recovery_error": str(exc)},
                                    )
                                    snapshot = (
                                        await self._fail_recovered_execution_tree(
                                            request.agent.runtime,
                                            recovered,
                                            request.context,
                                            error,
                                        )
                                    )
                            if snapshot is None:
                                error = RuntimeErrorInfo(
                                    code="execution.worker_restarted",
                                    category=ErrorCategory.RESOURCE_LOST,
                                    message=(
                                        "worker process restarted without a safe "
                                        "checkpoint or crossed tool barrier"
                                    ),
                                    safe_to_resume=False,
                                )
                                snapshot = await self._fail_recovered_execution_tree(
                                    request.agent.runtime,
                                    recovered,
                                    request.context,
                                    error,
                                )
                            execution = None
                        else:
                            request.resume = recovered.state == RunState.RESUMING
                    if snapshot is None:
                        execution = _agent_method(
                            request.agent, "ensure_execution", "_ensure_execution"
                        )(
                            lease.work.run_id,
                            request.context,
                            resume=request.resume,
                        )
                        done, _ = await asyncio.wait(
                            {execution, renewer}, return_when=asyncio.FIRST_COMPLETED
                        )
                        if renewer in done:
                            revoke_ownership()
                            execution.cancel()
                            await asyncio.gather(execution, return_exceptions=True)
                            raise self._renewal_error(renewer)
                        snapshot = execution.result()
                if snapshot.state == RunState.RUNNING and self._supports_deferred_work:
                    wake_at = await self._automatic_resume_at(request.agent.runtime.session_store, snapshot.run_id)
                    if wake_at is not None:
                        request.recovered = True
                        request.claimed = False
                        requeued = True
                        await self._release_lease(
                            lease, LeaseReleaseReason.DEFERRED,
                            requeue=True, available_at=wake_at,
                        )
                        continue
                reason = {
                    RunState.COMPLETED: LeaseReleaseReason.COMPLETED,
                    RunState.FAILED: LeaseReleaseReason.FAILED,
                    RunState.CANCELLED: LeaseReleaseReason.CANCELLED,
                    RunState.SUSPENDED: LeaseReleaseReason.SUSPENDED,
                }.get(snapshot.state, LeaseReleaseReason.FAILED)
                await self._release_lease(
                    lease,
                    reason,
                    requeue=snapshot.state == RunState.RESUMING,
                )
                self._discard_request(lease.work.run_id, request)
                if not request.result.done():
                    request.result.set_result(snapshot)
            except asyncio.CancelledError:
                if execution is not None and not execution.done():
                    execution.cancel()
                    await asyncio.gather(execution, return_exceptions=True)
                # ``async with scope`` has already unwound at this point.  A
                # driver backed directly by LeaseFencedSessionStore still needs
                # the same lease while its terminal shutdown fact is committed.
                shutdown_scope = (
                    self.lease_scope_factory(lease)
                    if self.lease_scope_factory is not None
                    else _NullAsyncScope()
                )
                try:
                    async with shutdown_scope:
                        if self._closed:
                            await self._finish_shutdown_request(
                                lease.work.run_id, request, lease=lease
                            )
                        else:
                            recovery = asyncio.create_task(
                                self._finish_cancelled_execution(
                                    lease.work.run_id, request, lease=lease
                                )
                            )
                            try:
                                done, _ = await asyncio.wait(
                                    {recovery, renewer},
                                    return_when=asyncio.FIRST_COMPLETED,
                                )
                                if renewer in done:
                                    revoke_ownership()
                                    recovery.cancel()
                                    await asyncio.gather(
                                        recovery, return_exceptions=True
                                    )
                                    renewal_error = self._renewal_error(renewer)
                                    raise renewal_error
                                recovery.result()
                            finally:
                                if not recovery.done():
                                    recovery.cancel()
                                await asyncio.gather(recovery, return_exceptions=True)
                except asyncio.CancelledError:
                    # close() may cancel the worker while recovery is in flight.
                    # Settle shutdown before the request is discarded below.
                    async with (
                        self.lease_scope_factory(lease)
                        if self.lease_scope_factory is not None
                        else _NullAsyncScope()
                    ):
                        await self._finish_shutdown_request(
                            lease.work.run_id, request, lease=lease
                        )
                    raise
                except BaseException as exc:
                    if ownership.revoked or is_lease_loss(exc):
                        requeued = await self._requeue_lost_lease(lease, request, exc)
                    else:
                        try:
                            await self._release_lease(
                                lease, LeaseReleaseReason.FAILED, requeue=False
                            )
                        except Exception:
                            pass
                        if not request.result.done():
                            request.result.set_exception(exc)
                if self._closed:
                    raise
            except Exception as exc:
                if ownership.revoked or is_lease_loss(exc):
                    revoke_ownership()
                    if execution is not None and not execution.done():
                        execution.cancel()
                        await asyncio.gather(execution, return_exceptions=True)
                    requeued = await self._requeue_lost_lease(lease, request, exc)
                else:
                    try:
                        await self._release_lease(
                            lease, LeaseReleaseReason.FAILED, requeue=False
                        )
                    except Exception:
                        pass
                    self._discard_request(lease.work.run_id, request)
                    if not request.result.done():
                        request.result.set_exception(exc)
            finally:
                renewer.cancel()
                await asyncio.gather(renewer, return_exceptions=True)
                if not requeued:
                    self._discard_request(lease.work.run_id, request)
                if gate_held:
                    gate.release()
                _, users = self._run_gates[lease.work.run_id]
                if users == 1:
                    self._run_gates.pop(lease.work.run_id)
                else:
                    self._run_gates[lease.work.run_id] = (gate, users - 1)
                ACTIVE_OWNERSHIP.reset(ownership_token)

    @staticmethod
    async def _automatic_resume_at(store, run_id):
        try:
            checkpoint = await store.get_latest_checkpoint(run_id)
        except SageV2Error as exc:
            if exc.info.code == "checkpoint.not_found_for_run":
                return None
            raise
        if checkpoint.state.get("execution_checkpoint") is not True:
            return None
        value = checkpoint.state.get("automatic_resume_at")
        due = datetime.fromisoformat(value) if isinstance(value, str) else value
        if due is not None:
            from sagents.v2.runtime.execution.budgets import evaluate_run_budget
            budget = await evaluate_run_budget(store, await store.get_run(run_id), utc_now(), check_tokens=False)
            if budget.deadline is not None:
                due = min(due, budget.deadline)
        return due

    async def _settle_deferred_controls(self):
        for run_id, request in tuple(self._requests.items()):
            if request.claimed or not request.recovered or request.result.done():
                continue
            snapshot = await request.agent.runtime.get_run(run_id)
            if snapshot.state == RunState.SUSPEND_REQUESTED:
                wake = getattr(self.scheduler, "reschedule_pending", None)
                if wake is not None:
                    await wake(f"work-{run_id}", utc_now())
                continue
            if snapshot.state not in TERMINAL_RUN_STATES and snapshot.state != RunState.SUSPENDED:
                continue
            await self.scheduler.cancel(f"work-{run_id}")
            self._discard_request(run_id, request)
            if not request.result.done():
                request.result.set_result(snapshot)

    async def _defer_recovery_error(self, lease, request, error):
        if not (
            self._supports_deferred_work and isinstance(error, SageV2Error)
            and error.info.retryable and error.info.safe_to_resume
            and error.info.category in {
                ErrorCategory.PROVIDER_TRANSIENT, ErrorCategory.RATE_LIMITED,
                ErrorCategory.RESOURCE_LOST,
            }
        ):
            return False
        runtime = request.agent.runtime
        run = await runtime.get_run(lease.work.run_id)
        if run.state not in {RunState.RUNNING, RunState.SUSPEND_REQUESTED}:
            return False
        command = await runtime.session_store.get_start_command(run.run_id)
        due = utc_now() + timedelta(seconds=min(60, 2 ** min(lease.work.attempt - 1, 6)))
        if command.config.deadline_seconds is not None:
            deadline = run.created_at + timedelta(seconds=command.config.deadline_seconds)
            if deadline <= utc_now():
                return False
            due = min(due, deadline)
        await self._release_lease(
            lease, LeaseReleaseReason.DEFERRED, requeue=True, available_at=due,
        )
        request.recovered = True
        request.claimed = False
        _LOGGER.warning(
            "scheduler.recovery.retry", "recoverable resource failure; scheduled another attempt",
            run_id=run.run_id, error_code=error.info.code, retry_at=due.isoformat(),
        )
        return True

    async def _release_lease(self, lease, reason, **kwargs):
        # A durable release may be in fsync when shutdown cancels its Worker.
        # Drain that atomic transition before handling cancellation; otherwise
        # the scheduler may be poisoned or the same lease released twice.
        release = asyncio.create_task(self.scheduler.release(lease, reason, **kwargs))
        cancelled = False
        while not release.done():
            try:
                await asyncio.shield(release)
            except asyncio.CancelledError:
                cancelled = True
        release.result()
        if cancelled:
            raise asyncio.CancelledError

    async def _requeue_lost_lease(self, lease, request, error) -> bool:
        """Keep the caller and Run tree alive until a fresh fenced claim recovers it."""
        if getattr(request.agent, "runtime", None) is None:
            # Compatibility drivers without durable Run state cannot be resumed.
            if not request.result.done():
                request.result.set_exception(error)
            return False
        request.recovered = True
        request.claimed = False
        try:
            await self._release_lease(
                lease, LeaseReleaseReason.WORKER_SHUTDOWN, requeue=True
            )
        except Exception as exc:
            if not is_lease_loss(exc):
                # Keep durable Run state recoverable even if the Scheduler needs
                # operator repair; never strand its in-process caller or worker.
                if not request.result.done():
                    request.result.set_exception(exc)
                return False
            # An expired/stolen lease has already been requeued by the Scheduler.
        _LOGGER.warning(
            "scheduler.worker.ownership_lost",
            "worker lease lost; preserving Run tree for a fresh claim",
            run_id=lease.work.run_id,
            lease_id=lease.lease_id,
            fencing_token=lease.fencing_token,
            diagnostic=str(error),
        )
        return True

    async def _execute_cleanup(
        self, lease: WorkerLease, request: _CleanupRequest
    ) -> None:
        renewer = asyncio.create_task(self._renew(lease))
        operation = None
        try:
            scope = (
                self.lease_scope_factory(lease)
                if self.lease_scope_factory is not None
                else _NullAsyncScope()
            )
            async with scope:
                operation = asyncio.create_task(request.operation())
                done, _ = await asyncio.wait(
                    {operation, renewer}, return_when=asyncio.FIRST_COMPLETED
                )
                if renewer in done:
                    operation.cancel()
                    await asyncio.gather(operation, return_exceptions=True)
                    raise renewer.exception() or RuntimeError(
                        "scheduler lease renewer stopped"
                    )
                value = operation.result()
            await self._release_lease(
                lease, LeaseReleaseReason.COMPLETED, requeue=False
            )
            if not request.result.done():
                request.result.set_result(value)
        except asyncio.CancelledError:
            if operation is not None and not operation.done():
                operation.cancel()
                await asyncio.gather(operation, return_exceptions=True)
            if not request.result.done():
                request.result.cancel()
            raise
        except Exception as exc:
            if not request.result.done():
                request.result.set_exception(exc)
            try:
                await self._release_lease(
                    lease, LeaseReleaseReason.FAILED, requeue=False
                )
            except Exception:
                pass
        finally:
            renewer.cancel()
            await asyncio.gather(renewer, return_exceptions=True)
            self._cleanup_requests.pop(lease.work.work_id, None)

    async def _fail_recovered_execution_tree(
        self, runtime, root, context: RequestContext, root_error: RuntimeErrorInfo
    ) -> RunSnapshot:
        """Settle inline child Runs before failing an uncheckpointed root.

        Delegated children share the root worker lease. A process loss therefore
        invalidates every active descendant in that execution tree; leaving one
        RUNNING would advertise resumability without a surviving driver.
        """

        require_execution_ownership()
        sessions = await runtime.session_store.list_descendant_sessions(root.session_id)
        candidates = []
        for session in sessions:
            candidates.extend(
                await runtime.session_store.list_session_runs(session.session_id)
            )
        for child in candidates:
            if child.state in TERMINAL_RUN_STATES or child.state == RunState.SUSPENDED:
                continue
            if not await self._has_run_ancestor(
                runtime.session_store, child.run_id, root.run_id
            ):
                continue
            error = RuntimeErrorInfo(
                code="execution.parent_worker_restarted",
                category=ErrorCategory.RESOURCE_LOST,
                message="parent worker restarted without the child Run driver",
                safe_to_resume=True,
            )
            await runtime.fail_run(
                run_id=child.run_id,
                expected_revision=child.revision,
                error=error,
                context=context,
                idempotency_key=(
                    f"parent-worker-restarted:{root.run_id}:"
                    f"{child.run_id}:{child.revision}"
                ),
            )
        return await runtime.fail_run(
            run_id=root.run_id,
            expected_revision=root.revision,
            error=root_error,
            context=context,
            idempotency_key=f"worker-restarted:{root.run_id}:{root.revision}",
        )

    @staticmethod
    async def _has_run_ancestor(session_store, run_id: str, ancestor: str) -> bool:
        candidate = run_id
        seen: set[str] = set()
        while candidate and candidate not in seen:
            seen.add(candidate)
            command = await session_store.get_start_command(candidate)
            if command.parent_run_id == ancestor:
                return True
            candidate = command.parent_run_id
        return False

    def _restore_request(self, lease: WorkerLease) -> _DispatchRequest | None:
        if self._recovery_agent is None:
            return None
        raw_context = lease.work.payload.get("request_context")
        if not isinstance(raw_context, dict):
            return None
        try:
            context = RequestContext.model_validate(raw_context)
        except (TypeError, ValueError):
            _LOGGER.warning(
                "scheduler.recovery.invalid_context",
                "cannot recover work with invalid request context",
            )
            return None
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

    def _discard_request(self, run_id: str, request: _DispatchRequest) -> None:
        """Remove only this generation of a Run's in-process dispatch request."""

        if self._requests.get(run_id) is request:
            self._requests.pop(run_id, None)

    async def _finish_shutdown_request(
        self,
        run_id: str,
        request: _DispatchRequest,
        *,
        lease: WorkerLease | None = None,
    ) -> None:
        """Resolve a submitted Future even when failure recording is unavailable."""

        runtime = getattr(request.agent, "runtime", None)
        if self.preserve_runs_on_shutdown and runtime is not None:
            snapshot = await runtime.get_run(run_id)
            if lease is not None:
                try:
                    await self._release_lease(
                        lease, LeaseReleaseReason.WORKER_SHUTDOWN,
                        requeue=snapshot.state not in TERMINAL_RUN_STATES and snapshot.state != RunState.SUSPENDED,
                    )
                except SageV2Error as exc:
                    if not is_lease_loss(exc):
                        raise
            if not request.result.done():
                request.result.set_result(snapshot)
            return

        try:
            snapshot = await _agent_method(
                request.agent, "fail_driver_crash", "_fail_driver_crash"
            )(
                run_id,
                self._shutdown_error(),
                request.context,
            )
        except BaseException as exc:
            if not request.result.done():
                request.result.set_exception(exc)
        else:
            # Explicit dispatcher shutdown remains terminal. Local task
            # cancellation alone no longer fails children, so settle any active
            # descendants once the root's shutdown fact is authoritative.
            runtime = getattr(request.agent, "runtime", None)
            if runtime is not None and snapshot.state in TERMINAL_RUN_STATES:
                await self._cancel_shutdown_descendants(
                    runtime, snapshot, request.context
                )
            if not request.result.done():
                request.result.set_result(snapshot)
        finally:
            if lease is not None:
                try:
                    await self._release_lease(
                        lease, LeaseReleaseReason.FAILED, requeue=False
                    )
                except BaseException:
                    # Expiry/reaping remains the final fallback, but shutdown
                    # must never strand the caller's Future on release failure.
                    pass

    async def _cancel_shutdown_descendants(self, runtime, root, context):
        for session in await runtime.session_store.list_descendant_sessions(
            root.session_id
        ):
            for child in await runtime.session_store.list_session_runs(
                session.session_id
            ):
                if (
                    child.state in TERMINAL_RUN_STATES
                    or not await self._has_run_ancestor(
                        runtime.session_store, child.run_id, root.run_id
                    )
                ):
                    continue
                await runtime.cancel_run(
                    CancelRun(
                        run_id=child.run_id,
                        expected_revision=child.revision,
                        idempotency_key=f"parent-shutdown:{root.run_id}:{child.run_id}",
                        reason="parent_worker_shutdown",
                    ),
                    context,
                )

    async def _finish_cancelled_execution(
        self,
        run_id: str,
        request: _DispatchRequest,
        *,
        lease: WorkerLease | None = None,
    ) -> None:
        """Recover a live driver cancel instead of pretending the worker died.

        ``execution.result()`` raising ``CancelledError`` is not process
        shutdown. Long MCP waits (video generate) hit this when the driver
        task is cancelled while the dispatcher and sidecar stay up. The
        durable ``tool.call.started`` barrier must be recovered so a later
        turn can see the side effect.
        """

        _LOGGER.warning(
            "scheduler.worker.execution_cancelled",
            "execution cancelled while the local worker stayed up; recovering",
            run_id=run_id,
        )
        snapshot = None
        recover = getattr(request.agent, "recover_interrupted_run", None) or getattr(
            request.agent, "_recover_interrupted_run", None
        )
        if recover is not None:
            try:
                snapshot = await recover(run_id, request.context)
            except Exception as exc:
                require_execution_ownership()
                if is_lease_loss(exc):
                    raise
                _LOGGER.exception(
                    "scheduler.worker.recovery_failed",
                    "live execution cancel could not recover the Run barrier",
                    exc,
                    run_id=run_id,
                )
                runtime = getattr(request.agent, "runtime", None)
                if runtime is not None:
                    try:
                        current = await runtime.get_run(run_id)
                    except Exception:
                        current = None
                    if current is not None and (
                        current.state in TERMINAL_RUN_STATES
                        or current.state == RunState.SUSPENDED
                    ):
                        snapshot = current
                    elif current is not None:
                        error = RuntimeErrorInfo(
                            code="execution.barrier_recovery_failed",
                            category=ErrorCategory.UNCERTAIN_SIDE_EFFECT,
                            message=(
                                "worker lost the driver after a possible side "
                                "effect and barrier recovery failed"
                            ),
                            safe_to_resume=False,
                            metadata={"recovery_error": str(exc)},
                        )
                        snapshot = await self._fail_recovered_execution_tree(
                            runtime,
                            current,
                            request.context,
                            error,
                        )
        if snapshot is None:
            snapshot = await _agent_method(
                request.agent, "fail_driver_crash", "_fail_driver_crash"
            )(
                run_id,
                self._shutdown_error(),
                request.context,
            )
        reason = {
            RunState.COMPLETED: LeaseReleaseReason.COMPLETED,
            RunState.FAILED: LeaseReleaseReason.FAILED,
            RunState.CANCELLED: LeaseReleaseReason.CANCELLED,
            RunState.SUSPENDED: LeaseReleaseReason.SUSPENDED,
        }.get(snapshot.state, LeaseReleaseReason.FAILED)
        try:
            if lease is not None:
                await self._release_lease(
                    lease,
                    reason,
                    requeue=snapshot.state == RunState.RESUMING,
                )
        except BaseException:
            pass
        self._discard_request(run_id, request)
        if not request.result.done():
            request.result.set_result(snapshot)

    @staticmethod
    def _renewal_error(renewer):
        # Task.exception() raises CancelledError for a cancelled heartbeat. It
        # must be treated as lost ownership, not as a user/shutdown cancellation.
        if renewer.cancelled():
            return RuntimeError("scheduler lease renewer was cancelled")
        return renewer.exception() or RuntimeError("scheduler lease renewer stopped")

    async def _renew(self, lease) -> None:
        delay = max(min(self.lease_duration.total_seconds() / 3, 10.0), 0.05)
        current = lease
        while True:
            await asyncio.sleep(delay)
            try:
                current = await self.scheduler.renew(
                    current, lease_duration=self.lease_duration
                )
            except Exception as exc:
                transient = isinstance(exc, (OSError, TimeoutError)) or (
                    isinstance(exc, SageV2Error)
                    and exc.info.retryable
                    and not is_lease_loss(exc)
                )
                if transient and utc_now() < current.expires_at:
                    _LOGGER.warning(
                        "scheduler.renew.retry",
                        "lease renewal temporarily failed",
                        run_id=lease.work.run_id,
                        diagnostic=str(exc),
                    )
                    continue
                revoke_ownership()
                raise

    @staticmethod
    def _consume_detached_result(result: asyncio.Future[RunSnapshot]) -> None:
        """Retrieve orphan completion errors so asyncio does not log them later."""

        if not result.cancelled():
            error = result.exception()
            if error is not None:
                _LOGGER.exception("scheduler.recovery.failed", "automatic recovery failed", error)

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

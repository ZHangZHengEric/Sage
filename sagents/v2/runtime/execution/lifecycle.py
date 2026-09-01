"""Durable orchestration for replaceable Run-scoped sandbox compute."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime, timedelta

from sagents.v2.contracts.checkpoint import SuspensionReason
from sagents.v2.contracts.common import utc_now
from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)
from sagents.v2.contracts.jobs import (
    JobExecutionAffinity,
    JobPauseBehavior,
    JobState,
)
from sagents.v2.contracts.principals import RequestContext
from sagents.v2.contracts.run_state import RunState
from sagents.v2.runtime.execution.resources import (
    ExecutionLifecycleMetrics,
    ExecutionResourceRecord,
    ExecutionResourceState,
)
from sagents.v2.runtime.execution.sandbox import (
    ResolvedSandboxSpec,
    SandboxHandle,
    SandboxProvider,
    SandboxReleaseDisposition,
    SandboxReleaseRequest,
    SandboxState,
)


_TERMINAL_JOB_STATES = frozenset(
    {JobState.COMPLETED, JobState.FAILED, JobState.KILLED}
)
_UNSAFE_RELEASE_REASONS = frozenset({SuspensionReason.POLICY_HOLD})


class ExecutionBindingLifecycleCoordinator:
    """Keep approvals durable while compute is released and later recreated.

    The coordinator is the only runtime component allowed to invoke the v3
    provider release API. Tools merely declare Job affinity and pause behavior.
    Every authoritative mutation goes through SessionStore so a fenced Worker
    lease can serialize cleanup against resume.
    """

    def __init__(
        self,
        *,
        sandbox_provider: SandboxProvider,
        session_store,
        job_runtime,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.sandbox_provider = sandbox_provider
        self.session_store = session_store
        self.job_runtime = job_runtime
        self._clock = clock

    async def bind_provisioned(
        self,
        *,
        run_id: str,
        handle: SandboxHandle,
        spec: ResolvedSandboxSpec,
        run_resolved_spec_hash: str,
        context: RequestContext,
    ) -> ExecutionResourceRecord:
        """Persist a sandbox created after the Worker acquired the Run lease."""

        existing = await self.session_store.get_execution_resource(run_id)
        if existing is not None:
            if existing.sandbox_ref == handle.ref and existing.state == ExecutionResourceState.ACTIVE:
                return existing
            raise self._error(
                "sandbox.binding_conflict",
                ErrorCategory.CONFLICT,
                "Run already owns a different execution resource",
            )
        run = await self.session_store.get_run(run_id)
        record = ExecutionResourceRecord(
            run_id=run_id,
            generation=1,
            sandbox_ref=handle.ref,
            sandbox_spec=spec,
            run_resolved_spec_hash=run_resolved_spec_hash,
            state=ExecutionResourceState.ACTIVE,
            updated_at=self._clock(),
        )
        try:
            return await self.session_store.commit_execution_resource(
                record=record,
                expected_run_revision=run.revision,
                expected_resource_revision=None,
                event_type="sandbox.ready",
                context=context,
                idempotency_key=f"sandbox-bind:{run_id}:1",
            )
        except BaseException:
            await self._best_effort_fence_unbound(handle.ref, context)
            raise

    async def acquire(
        self,
        *,
        run_id: str,
        spec: ResolvedSandboxSpec,
        run_resolved_spec_hash: str,
        context: RequestContext,
    ) -> SandboxHandle:
        """Attach, restore, or provision immediately on the RESUMING Worker."""

        run = await self.session_store.get_run(run_id)
        record = await self.session_store.get_execution_resource(run_id)
        if record is None:
            handle = await self.sandbox_provider.provision(spec, context, run_id=run_id)
            await self.bind_provisioned(
                run_id=run_id,
                handle=handle,
                spec=spec,
                run_resolved_spec_hash=run_resolved_spec_hash,
                context=context,
            )
            return handle

        self._validate_policy(record, spec, run.resolved_spec_hash)
        if record.state in {
            ExecutionResourceState.RELEASE_REQUESTED,
            ExecutionResourceState.RELEASE_FAILED,
        }:
            record = await self._release_record(record, context)
        if record.state == ExecutionResourceState.RELEASE_BLOCKED:
            snapshot = await self.sandbox_provider.inspect(record.sandbox_ref)
            if snapshot.state not in {SandboxState.TERMINATED, SandboxState.LOST}:
                handle = await self.sandbox_provider.attach(record.sandbox_ref, context)
                await self._commit_active(record, handle, context, event_type="sandbox.resumed")
                return handle
            raise self._error(
                "sandbox.restore_failed",
                ErrorCategory.RESOURCE_LOST,
                "retained sandbox is no longer reconnectable",
            )
        if record.state == ExecutionResourceState.ACTIVE:
            handle = await self.sandbox_provider.attach(record.sandbox_ref, context)
            await self._commit_active(record, handle, context, event_type="sandbox.resumed")
            return handle
        if record.state not in {
            ExecutionResourceState.RELEASED,
            ExecutionResourceState.RESTORE_REQUESTED,
        }:
            raise self._error(
                "sandbox.restore_failed",
                ErrorCategory.CONFLICT,
                f"cannot acquire sandbox while resource is {record.state.value}",
            )

        requested = record
        if record.state == ExecutionResourceState.RELEASED:
            requested = record.model_copy(
                update={
                    "state": ExecutionResourceState.RESTORE_REQUESTED,
                    "error": None,
                    "next_retry_at": None,
                    "updated_at": self._clock(),
                }
            )
            requested = await self._commit(
                requested,
                context,
                "sandbox.restore_requested",
                f"sandbox-restore-requested:{run_id}:{record.generation + 1}",
            )
        try:
            if record.sandbox_checkpoint is not None:
                handle = await self.sandbox_provider.restore(
                    record.sandbox_checkpoint, context
                )
            elif record.release_disposition == SandboxReleaseDisposition.SNAPSHOT_AND_TERMINATE:
                raise self._error(
                    "sandbox.restore_failed",
                    ErrorCategory.RESOURCE_LOST,
                    "sandbox snapshot is missing",
                )
            else:
                handle = await self.sandbox_provider.provision(
                    spec, context, run_id=run_id
                )
        except Exception as exc:
            if isinstance(exc, SageV2Error) and not exc.info.retryable:
                raise
            error = exc.info if isinstance(exc, SageV2Error) else RuntimeErrorInfo(
                code="sandbox.restore_failed",
                category=ErrorCategory.PROVIDER_TRANSIENT,
                message=str(exc),
                retryable=True,
                safe_to_resume=True,
            )
            retry_count = requested.retry_count + 1
            failed = requested.model_copy(
                update={
                    "retry_count": retry_count,
                    "error": error,
                    "updated_at": self._clock(),
                }
            )
            await self._commit(
                failed,
                context,
                "sandbox.restore_failed",
                f"sandbox-restore-failed:{run_id}:{requested.generation + 1}:{retry_count}",
            )
            raise SageV2Error(error) from exc
        await self._commit_active(
            requested, handle, context, event_type="sandbox.resumed"
        )
        return handle

    async def suspend(
        self, *, run_id: str, context: RequestContext
    ) -> ExecutionResourceRecord | None:
        """Release safe paused compute without changing Run or Interaction state."""

        run = await self.session_store.get_run(run_id)
        if run.state != RunState.SUSPENDED or run.suspension_id is None:
            return await self.session_store.get_execution_resource(run_id)
        record = await self.session_store.get_execution_resource(run_id)
        if record is None or record.state != ExecutionResourceState.ACTIVE:
            return record
        suspension = await self.session_store.get_suspension(run.suspension_id)
        jobs = await self.job_runtime.handle_run_pause(run_id)
        blockers = tuple(
            sorted(
                job.job_id
                for job in jobs
                if job.state not in _TERMINAL_JOB_STATES
                and job.execution_affinity == JobExecutionAffinity.SANDBOX
                and job.pause_behavior
                in {JobPauseBehavior.CONTINUE, JobPauseBehavior.DETACH}
            )
        )
        blocking_children = await self._blocking_child_runs(run.session_id)
        unsafe = suspension.reason in _UNSAFE_RELEASE_REASONS
        disposition = (
            record.sandbox_spec.lifecycle.unsafe_pause_behavior
            if unsafe
            else record.sandbox_spec.lifecycle.safe_pause_behavior
        )
        release_key = record.release_idempotency_key or self._release_key(
            record, suspension.suspension_id
        )
        if blockers or blocking_children or disposition == SandboxReleaseDisposition.DETACH:
            blocked = record.model_copy(
                update={
                    "state": ExecutionResourceState.RELEASE_BLOCKED,
                    "release_disposition": disposition,
                    "suspension_id": suspension.suspension_id,
                    "suspension_reason": suspension.reason.value,
                    "blocking_job_ids": blockers,
                    "blocking_child_run_ids": blocking_children,
                    "release_idempotency_key": release_key,
                    "updated_at": self._clock(),
                }
            )
            if disposition == SandboxReleaseDisposition.DETACH:
                snapshot = await self.sandbox_provider.inspect(record.sandbox_ref)
                await self.sandbox_provider.release(
                    SandboxReleaseRequest(
                        ref=record.sandbox_ref,
                        disposition=disposition,
                        reason=suspension.reason.value,
                        expected_revision=snapshot.revision,
                        idempotency_key=release_key,
                    ),
                    context,
                )
            return await self._commit(
                blocked,
                context,
                "sandbox.release_blocked",
                f"sandbox-release-blocked:{release_key}",
            )
        requested = record.model_copy(
            update={
                "state": ExecutionResourceState.RELEASE_REQUESTED,
                "release_disposition": disposition,
                "suspension_id": suspension.suspension_id,
                "suspension_reason": suspension.reason.value,
                "blocking_job_ids": (),
                "blocking_child_run_ids": (),
                "release_idempotency_key": release_key,
                "release_requested_at": self._clock(),
                "error": None,
                "updated_at": self._clock(),
            }
        )
        requested = await self._commit(
            requested,
            context,
            "sandbox.release_requested",
            f"sandbox-release-requested:{release_key}",
        )
        return await self._release_record(requested, context)

    async def reconcile_run(
        self, *, run_id: str, context: RequestContext
    ) -> ExecutionResourceRecord | None:
        """Re-evaluate one blocked/failed cleanup under a Scheduler fence."""

        record = await self.session_store.get_execution_resource(run_id)
        if record is None:
            return None
        if record.state == ExecutionResourceState.RELEASE_BLOCKED:
            if record.release_disposition == SandboxReleaseDisposition.DETACH:
                return record
            run = await self.session_store.get_run(run_id)
            if await self._blocking_child_runs(run.session_id):
                return record
            jobs = await self.job_runtime.list_run_jobs(run_id)
            active_ids = {
                job.job_id
                for job in jobs
                if job.state not in _TERMINAL_JOB_STATES
                and job.execution_affinity == JobExecutionAffinity.SANDBOX
            }
            if active_ids.intersection(record.blocking_job_ids):
                return record
            requested = record.model_copy(
                update={
                    "state": ExecutionResourceState.RELEASE_REQUESTED,
                    "blocking_job_ids": (),
                    "blocking_child_run_ids": (),
                    "release_requested_at": self._clock(),
                    "updated_at": self._clock(),
                }
            )
            record = await self._commit(
                requested,
                context,
                "sandbox.release_requested",
                f"sandbox-release-unblocked:{record.release_idempotency_key}",
            )
        if record.state in {
            ExecutionResourceState.RELEASE_REQUESTED,
            ExecutionResourceState.RELEASE_FAILED,
        }:
            if record.next_retry_at is not None and record.next_retry_at > self._clock():
                return record
            return await self._release_record(record, context)
        return record

    async def _release_record(
        self, record: ExecutionResourceRecord, context: RequestContext
    ) -> ExecutionResourceRecord:
        disposition = record.release_disposition
        release_key = record.release_idempotency_key
        if disposition is None or release_key is None:
            raise self._error(
                "sandbox.release_state_invalid",
                ErrorCategory.CORRUPT_STATE,
                "pending release is missing disposition or idempotency key",
            )
        try:
            snapshot = await self.sandbox_provider.inspect(record.sandbox_ref)
            receipt = await self.sandbox_provider.release(
                SandboxReleaseRequest(
                    ref=record.sandbox_ref,
                    disposition=disposition,
                    reason=record.suspension_reason or "suspended",
                    expected_revision=snapshot.revision,
                    idempotency_key=release_key,
                ),
                context,
            )
            if disposition != SandboxReleaseDisposition.DETACH and not receipt.compute_released:
                raise self._error(
                    "sandbox.release_unconfirmed",
                    ErrorCategory.UNCERTAIN_SIDE_EFFECT,
                    "provider did not confirm compute fencing",
                    retryable=True,
                )
            released = record.model_copy(
                update={
                    "state": ExecutionResourceState.RELEASED,
                    "sandbox_checkpoint": receipt.checkpoint,
                    "compute_released": receipt.compute_released,
                    "error": None,
                    "next_retry_at": None,
                    "released_at": receipt.released_at,
                    "updated_at": receipt.released_at,
                }
            )
            return await self._commit(
                released,
                context,
                "sandbox.released",
                f"sandbox-released:{release_key}",
            )
        except Exception as exc:
            error = exc.info if isinstance(exc, SageV2Error) else RuntimeErrorInfo(
                code="sandbox.release_failed",
                category=ErrorCategory.PROVIDER_TRANSIENT,
                message=str(exc),
                retryable=True,
                safe_to_resume=True,
            )
            retry_count = record.retry_count + 1
            delay = min(300, 2 ** min(retry_count - 1, 9))
            failed = record.model_copy(
                update={
                    "state": ExecutionResourceState.RELEASE_FAILED,
                    "retry_count": retry_count,
                    "next_retry_at": self._clock() + timedelta(seconds=delay),
                    "error": error,
                    "updated_at": self._clock(),
                }
            )
            return await self._commit(
                failed,
                context,
                "sandbox.release_failed",
                f"sandbox-release-failed:{release_key}:{retry_count}",
            )

    async def _commit_active(
        self,
        previous: ExecutionResourceRecord,
        handle: SandboxHandle,
        context: RequestContext,
        *,
        event_type: str,
    ) -> ExecutionResourceRecord:
        active = previous.model_copy(
            update={
                "generation": previous.generation + 1,
                "sandbox_ref": handle.ref,
                "state": ExecutionResourceState.ACTIVE,
                "release_disposition": None,
                "sandbox_checkpoint": None,
                "suspension_id": None,
                "suspension_reason": None,
                "blocking_job_ids": (),
                "blocking_child_run_ids": (),
                "release_idempotency_key": None,
                "release_requested_at": None,
                "released_at": None,
                "compute_released": False,
                "retry_count": 0,
                "next_retry_at": None,
                "error": None,
                "updated_at": self._clock(),
            }
        )
        try:
            return await self._commit(
                active,
                context,
                event_type,
                f"sandbox-active:{active.run_id}:{active.generation}",
            )
        except BaseException:
            await self._best_effort_fence_unbound(handle.ref, context)
            raise

    async def _commit(
        self,
        record: ExecutionResourceRecord,
        context: RequestContext,
        event_type: str,
        idempotency_key: str,
    ) -> ExecutionResourceRecord:
        run = await self.session_store.get_run(record.run_id)
        current = await self.session_store.get_execution_resource(record.run_id)
        return await self.session_store.commit_execution_resource(
            record=record,
            expected_run_revision=run.revision,
            expected_resource_revision=(current.revision if current is not None else None),
            event_type=event_type,
            context=context,
            idempotency_key=idempotency_key,
        )

    async def _best_effort_fence_unbound(self, ref, context: RequestContext) -> None:
        try:
            snapshot = await self.sandbox_provider.inspect(ref)
            await self.sandbox_provider.release(
                SandboxReleaseRequest(
                    ref=ref,
                    disposition=SandboxReleaseDisposition.TERMINATE,
                    reason="binding_commit_failed",
                    expected_revision=snapshot.revision,
                    idempotency_key=f"sandbox-fence-unbound:{ref.sandbox_id}",
                ),
                context,
            )
        except Exception:
            pass

    async def metrics_snapshot(self) -> ExecutionLifecycleMetrics:
        records = await self.session_store.list_execution_resources()
        now = self._clock()
        latencies = [
            (record.released_at - record.release_requested_at).total_seconds()
            for record in records
            if record.released_at is not None
            and record.release_requested_at is not None
            and record.released_at >= record.release_requested_at
        ]
        blocked_ages = [
            max(0.0, (now - record.updated_at).total_seconds())
            for record in records
            if record.state == ExecutionResourceState.RELEASE_BLOCKED
        ]
        pending = {
            ExecutionResourceState.RELEASE_BLOCKED,
            ExecutionResourceState.RELEASE_REQUESTED,
            ExecutionResourceState.RELEASE_FAILED,
        }
        return ExecutionLifecycleMetrics(
            active_sandboxes=sum(
                record.state == ExecutionResourceState.ACTIVE for record in records
            ),
            retained_sandboxes=sum(
                record.state == ExecutionResourceState.RELEASE_BLOCKED
                for record in records
            ),
            pending_releases=sum(record.state in pending for record in records),
            release_failure_count=sum(
                record.state == ExecutionResourceState.RELEASE_FAILED
                for record in records
            ),
            release_retry_count=sum(record.retry_count for record in records),
            max_blocked_age_seconds=max(blocked_ages, default=0.0),
            average_release_latency_seconds=(
                sum(latencies) / len(latencies) if latencies else 0.0
            ),
        )

    async def _blocking_child_runs(self, session_id: str) -> tuple[str, ...]:
        blocked: list[str] = []
        for session in await self.session_store.list_descendant_sessions(session_id):
            for run in await self.session_store.list_session_runs(session.session_id):
                resource = await self.session_store.get_execution_resource(run.run_id)
                if resource is not None and resource.state != ExecutionResourceState.RELEASED:
                    blocked.append(run.run_id)
        return tuple(sorted(blocked))

    @staticmethod
    def _validate_policy(
        record: ExecutionResourceRecord,
        spec: ResolvedSandboxSpec,
        run_resolved_spec_hash: str,
    ) -> None:
        if (
            record.sandbox_spec.spec_hash != spec.spec_hash
            or record.sandbox_spec.policy_hash != spec.policy_hash
            or record.run_resolved_spec_hash != run_resolved_spec_hash
        ):
            raise ExecutionBindingLifecycleCoordinator._error(
                "sandbox.policy_stale",
                ErrorCategory.CONFLICT,
                "sandbox or Run policy changed while execution was suspended",
            )

    @staticmethod
    def _release_key(record: ExecutionResourceRecord, suspension_id: str) -> str:
        digest = hashlib.sha256(
            f"{record.run_id}\0{record.generation}\0{suspension_id}".encode()
        ).hexdigest()
        return f"sandbox_release_{digest}"

    @staticmethod
    def _error(
        code: str,
        category: ErrorCategory,
        message: str,
        *,
        retryable: bool = False,
    ) -> SageV2Error:
        return SageV2Error(
            RuntimeErrorInfo(
                code=code,
                category=category,
                message=message,
                retryable=retryable,
                safe_to_resume=retryable,
            )
        )


__all__ = ["ExecutionBindingLifecycleCoordinator"]

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from sagents.v2.contracts.checkpoint import (
    Checkpoint,
    Suspension,
    SuspensionReason,
)
from sagents.v2.contracts.commands import InputItem, ResumeRun, StartRun
from sagents.v2.contracts.events import RunEventData
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.jobs import (
    JobCompletion,
    JobExecutionAffinity,
    JobPauseBehavior,
    JobSpec,
)
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.contracts.run_state import RunState
from sagents.v2.contracts.common import utc_now
from sagents.v2.runtime.execution import (
    ExecutionBindingLifecycleCoordinator,
    ExecutionResourceState,
)
from sagents.v2.runtime.execution.jobs import InMemoryJobRuntime
from sagents.v2.runtime.execution.sandbox import (
    FileOperation,
    FileSystemPolicy,
    InMemorySandboxProvider,
    LifecyclePolicy,
    ResolvedSandboxSpec,
    SandboxDurability,
    SandboxGrantIssuer,
    SandboxReleaseDisposition,
    SandboxState,
)
from sagents.v2.runtime.session import EventDraft
from sagents.v2.runtime.session.state import SessionStoreCoordinator


CONTEXT = RequestContext(
    actor=ActorRef(
        principal_id="lifecycle-user",
        principal_type=PrincipalType.USER,
        tenant_id="tenant",
    )
)
RUN_SPEC_HASH = "sha256:run-spec"


class _MutableClock:
    def __init__(self):
        self.now = utc_now()

    def __call__(self):
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


class _FailOnceReleaseProvider(InMemorySandboxProvider):
    def __init__(self, verification_key, **kwargs):
        super().__init__(verification_key, **kwargs)
        self.failures_remaining = 1

    async def release(self, request, context):
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise OSError("transient release failure")
        return await super().release(request, context)


def sandbox_spec(
    disposition: SandboxReleaseDisposition = (
        SandboxReleaseDisposition.SNAPSHOT_AND_TERMINATE
    ),
) -> ResolvedSandboxSpec:
    return ResolvedSandboxSpec(
        spec_hash="sha256:sandbox-spec",
        architecture="portable",
        filesystem=FileSystemPolicy(
            allowed_operations=frozenset(FileOperation),
        ),
        lifecycle=LifecyclePolicy(
            durability=SandboxDurability.SNAPSHOTABLE,
            safe_pause_behavior=disposition,
            unsafe_pause_behavior=SandboxReleaseDisposition.DETACH,
        ),
        policy_hash="sha256:sandbox-policy",
    )


async def create_running_run(store: SessionStoreCoordinator) -> str:
    created = await store.create_run(
        StartRun(
            agent_id="agent",
            input=(InputItem(role="user", content=(TextBlock(text="run"),)),),
            resolved_spec_hash=RUN_SPEC_HASH,
            idempotency_key="start",
        ),
        CONTEXT,
    )
    await store.commit_run(
        run_id=created.handle.run_id,
        expected_revision=0,
        expected_states={RunState.QUEUED},
        new_state=RunState.RUNNING,
        drafts=(
            EventDraft(type="run.started", data=RunEventData(state="running")),
        ),
        context=CONTEXT,
        idempotency_key="running",
    )
    return created.handle.run_id


async def suspend_run(
    store: SessionStoreCoordinator,
    run_id: str,
    reason: SuspensionReason = SuspensionReason.APPROVAL_REQUIRED,
) -> Suspension:
    run = await store.get_run(run_id)
    checkpoint = Checkpoint(
        checkpoint_id=f"checkpoint_{run_id}",
        checkpoint_codec_version="test/v1",
        session_id=run.session_id,
        run_id=run_id,
        run_sequence=run.last_run_sequence,
        session_revision=run.accepted_session_revision,
        state={"tool_call_id": "tool_1", "policy_decision": "approval"},
        resolved_spec_hash=RUN_SPEC_HASH,
        created_at=utc_now(),
    )
    suspension = Suspension(
        suspension_id=f"suspension_{run_id}",
        run_id=run_id,
        reason=reason,
        blocking_scope="run",
        checkpoint_id=checkpoint.checkpoint_id,
        checkpoint_sequence=run.last_run_sequence,
        resume_policy="explicit",
        requested_at=utc_now(),
    )
    await store.commit_run(
        run_id=run_id,
        expected_revision=run.revision,
        expected_states={RunState.RUNNING},
        new_state=RunState.SUSPENDED,
        drafts=(
            EventDraft(
                type="run.suspended",
                data=RunEventData(state="suspended", reason=reason.value),
            ),
        ),
        context=CONTEXT,
        idempotency_key=f"suspend:{run_id}",
        checkpoint=checkpoint,
        suspension=suspension,
    )
    return suspension


async def lifecycle_fixture(disposition=SandboxReleaseDisposition.SNAPSHOT_AND_TERMINATE):
    store = SessionStoreCoordinator()
    run_id = await create_running_run(store)
    issuer = SandboxGrantIssuer(b"test-key-32-bytes-minimum-length!!")
    provider = InMemorySandboxProvider(issuer.verification_key)
    jobs = InMemoryJobRuntime({})
    coordinator = ExecutionBindingLifecycleCoordinator(
        sandbox_provider=provider,
        session_store=store,
        job_runtime=jobs,
    )
    spec = sandbox_spec(disposition)
    handle = await provider.provision(spec, CONTEXT, run_id=run_id)
    await coordinator.bind_provisioned(
        run_id=run_id,
        handle=handle,
        spec=spec,
        run_resolved_spec_hash=RUN_SPEC_HASH,
        context=CONTEXT,
    )
    return store, provider, jobs, coordinator, spec, handle


@pytest.mark.asyncio
async def test_safe_approval_pause_snapshots_terminates_and_restores():
    store, provider, _jobs, coordinator, spec, old_handle = await lifecycle_fixture()
    run_id = old_handle.ref.owner_run_id
    await suspend_run(store, run_id)

    released = await coordinator.suspend(run_id=run_id, context=CONTEXT)

    assert released is not None
    assert released.state == ExecutionResourceState.RELEASED
    assert released.compute_released is True
    assert released.sandbox_checkpoint is not None
    assert (await provider.inspect(old_handle.ref)).state == SandboxState.TERMINATED

    run = await store.get_run(run_id)
    suspension = await store.get_suspension(run.suspension_id)
    resumed = await store.request_resume(
        ResumeRun(
            run_id=run_id,
            suspension_id=suspension.suspension_id,
            expected_suspension_revision=suspension.expected_revision,
            expected_revision=run.revision,
            idempotency_key="resume",
        ),
        CONTEXT,
    )
    assert resumed.run.state == RunState.RESUMING

    restored = await coordinator.acquire(
        run_id=run_id,
        spec=spec,
        run_resolved_spec_hash=RUN_SPEC_HASH,
        context=CONTEXT,
    )
    record = await store.get_execution_resource(run_id)
    assert (await restored.status()).state == SandboxState.READY
    assert record is not None and record.state == ExecutionResourceState.ACTIVE
    assert record.generation == 2


@pytest.mark.asyncio
async def test_sandbox_bound_detached_job_blocks_then_auto_reconciles_release():
    gate = asyncio.Event()

    async def runner(_spec, _emit, _cancel):
        await gate.wait()
        return JobCompletion()

    store, provider, jobs, coordinator, _spec, handle = await lifecycle_fixture()
    jobs.register_runner("background", runner)
    job = await jobs.submit(
        JobSpec(
            owner_run_id=handle.ref.owner_run_id,
            kind="background",
            pause_behavior=JobPauseBehavior.DETACH,
            execution_affinity=JobExecutionAffinity.SANDBOX,
            idempotency_key="background",
        )
    )
    await suspend_run(store, handle.ref.owner_run_id)

    blocked = await coordinator.suspend(
        run_id=handle.ref.owner_run_id, context=CONTEXT
    )
    assert blocked is not None
    assert blocked.state == ExecutionResourceState.RELEASE_BLOCKED
    assert blocked.blocking_job_ids == (job.job_id,)
    assert (await provider.inspect(handle.ref)).state == SandboxState.READY

    gate.set()
    await jobs.wait(job.job_id)
    released = await coordinator.reconcile_run(
        run_id=handle.ref.owner_run_id, context=CONTEXT
    )
    assert released is not None and released.state == ExecutionResourceState.RELEASED
    assert (await provider.inspect(handle.ref)).state == SandboxState.TERMINATED


@pytest.mark.asyncio
async def test_external_job_does_not_block_safe_release():
    gate = asyncio.Event()

    async def runner(_spec, _emit, _cancel):
        await gate.wait()
        return JobCompletion()

    store, provider, jobs, coordinator, _spec, handle = await lifecycle_fixture()
    jobs.register_runner("external", runner)
    job = await jobs.submit(
        JobSpec(
            owner_run_id=handle.ref.owner_run_id,
            kind="external",
            pause_behavior=JobPauseBehavior.CONTINUE,
            execution_affinity=JobExecutionAffinity.EXTERNAL,
            idempotency_key="external",
        )
    )
    await suspend_run(store, handle.ref.owner_run_id)
    released = await coordinator.suspend(
        run_id=handle.ref.owner_run_id, context=CONTEXT
    )
    assert released is not None and released.state == ExecutionResourceState.RELEASED
    assert (await provider.inspect(handle.ref)).state == SandboxState.TERMINATED
    assert (await jobs.inspect(job.job_id)).state not in {
        "completed",
        "failed",
        "killed",
    }
    gate.set()
    await jobs.wait(job.job_id)


@pytest.mark.asyncio
async def test_policy_hold_detaches_without_claiming_compute_release():
    store, provider, _jobs, coordinator, _spec, handle = await lifecycle_fixture()
    await suspend_run(store, handle.ref.owner_run_id, SuspensionReason.POLICY_HOLD)
    retained = await coordinator.suspend(
        run_id=handle.ref.owner_run_id, context=CONTEXT
    )
    assert retained is not None
    assert retained.state == ExecutionResourceState.RELEASE_BLOCKED
    assert retained.release_disposition == SandboxReleaseDisposition.DETACH
    assert retained.compute_released is False
    assert (await provider.inspect(handle.ref)).state == SandboxState.READY


@pytest.mark.asyncio
async def test_release_failure_keeps_approval_suspended_and_retries_durably():
    clock = _MutableClock()
    store = SessionStoreCoordinator(clock=clock)
    run_id = await create_running_run(store)
    issuer = SandboxGrantIssuer(
        b"test-key-32-bytes-minimum-length!!", clock=clock
    )
    provider = _FailOnceReleaseProvider(issuer.verification_key, clock=clock)
    jobs = InMemoryJobRuntime({}, clock=clock)
    coordinator = ExecutionBindingLifecycleCoordinator(
        sandbox_provider=provider,
        session_store=store,
        job_runtime=jobs,
        clock=clock,
    )
    spec = sandbox_spec()
    handle = await provider.provision(spec, CONTEXT, run_id=run_id)
    await coordinator.bind_provisioned(
        run_id=run_id,
        handle=handle,
        spec=spec,
        run_resolved_spec_hash=RUN_SPEC_HASH,
        context=CONTEXT,
    )
    await suspend_run(store, run_id)

    failed = await coordinator.suspend(run_id=run_id, context=CONTEXT)
    assert failed is not None
    assert failed.state == ExecutionResourceState.RELEASE_FAILED
    assert failed.retry_count == 1
    assert (await store.get_run(run_id)).state == RunState.SUSPENDED

    clock.advance(1)
    released = await coordinator.reconcile_run(run_id=run_id, context=CONTEXT)
    assert released is not None and released.state == ExecutionResourceState.RELEASED
    assert (await provider.inspect(handle.ref)).state == SandboxState.TERMINATED

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timedelta, timezone

import pytest

from sagents.v2.contracts.commands import InputItem, StartRun
from sagents.v2.contracts.events import RunEventData
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.jobs import JobCompletion, JobSpec
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.contracts.run_state import RunState, SessionConcurrencyMode
from sagents.v2.runtime.execution.jobs import InMemoryJobRuntime
from sagents.v2.runtime.execution.sandbox import (
    FileOperation,
    FileSystemPolicy,
    InMemorySandboxProvider,
    ResolvedSandboxSpec,
    SandboxGrantIssuer,
)
from sagents.v2.runtime.session import EphemeralSessionStore, EventDraft


SOAK_SECONDS = float(os.environ.get("SAGE_V2_SOAK_SECONDS", "0"))


@pytest.mark.skipif(SOAK_SECONDS <= 0, reason="set SAGE_V2_SOAK_SECONDS to run soak")
@pytest.mark.timeout(420)
@pytest.mark.asyncio
async def test_one_hundred_concurrent_sessions_remain_ordered_and_bounded():
    store = EphemeralSessionStore()
    context = RequestContext(
        actor=ActorRef(
            principal_id="soak",
            principal_type=PrincipalType.SERVICE,
            tenant_id="soak-tenant",
        )
    )
    deadline = asyncio.get_running_loop().time() + SOAK_SECONDS
    run_ids: list[str] = []
    run_ids_lock = asyncio.Lock()

    async def session_worker(index: int) -> None:
        iteration = 0
        session_id = f"soak-session-{index:03d}"
        while asyncio.get_running_loop().time() < deadline:
            created = await store.create_run(
                StartRun(
                    agent_id="soak-agent",
                    session_id=session_id,
                    session_concurrency_mode=SessionConcurrencyMode.SNAPSHOT_ISOLATED,
                    input=(
                        InputItem(
                            role="user",
                            content=(TextBlock(text=f"{index}:{iteration}"),),
                        ),
                    ),
                    resolved_spec_hash="sha256:single-process-soak",
                    idempotency_key=f"soak-{index}-{iteration}",
                ),
                context,
            )
            running = await store.commit_run(
                run_id=created.handle.run_id,
                expected_revision=0,
                expected_states={RunState.QUEUED},
                new_state=RunState.RUNNING,
                drafts=(
                    EventDraft(
                        type="run.started", data=RunEventData(state="running")
                    ),
                ),
                context=context,
                idempotency_key=f"running-{index}-{iteration}",
            )
            await store.commit_run(
                run_id=created.handle.run_id,
                expected_revision=running.run.revision,
                expected_states={RunState.RUNNING},
                new_state=RunState.COMPLETED,
                drafts=(
                    EventDraft(
                        type="run.completed", data=RunEventData(state="completed")
                    ),
                ),
                context=context,
                idempotency_key=f"completed-{index}-{iteration}",
            )
            async with run_ids_lock:
                run_ids.append(created.handle.run_id)
            iteration += 1
            await asyncio.sleep(2)

    wall_started = time.monotonic()
    cpu_started = time.process_time()
    await asyncio.gather(*(session_worker(index) for index in range(100)))
    wall_elapsed = time.monotonic() - wall_started
    cpu_elapsed = time.process_time() - cpu_started

    for index in range(100):
        events = await store.read_session_events(f"soak-session-{index:03d}")
        assert [event.session_sequence for event in events] == list(
            range(1, len(events) + 1)
        )
    for run_id in run_ids:
        assert (await store.get_run(run_id)).state == RunState.COMPLETED
    # One busy-looping core approaches 1.0. The workload intentionally sleeps
    # between turns, so this generous ceiling still detects quota-style spin.
    assert cpu_elapsed / max(wall_elapsed, 0.001) < 0.8

    now = datetime(2026, 9, 1, tzinfo=timezone.utc)

    def clock():
        return now

    async def runner(spec, emit, cancelled):
        del spec, emit, cancelled
        return JobCompletion()

    jobs = InMemoryJobRuntime(
        {"probe": runner},
        clock=clock,
        terminal_ttl_seconds=1,
        max_retained_terminal_jobs=32,
        max_retained_output_bytes=1024,
        output_reconnect_window_seconds=0,
    )
    for index in range(100):
        handle = await jobs.submit(
            JobSpec(
                owner_run_id=f"soak-owner-{index}",
                kind="probe",
                idempotency_key=f"soak-job-{index}",
            )
        )
        await jobs.wait(handle.job_id)
        now += timedelta(microseconds=1)
    assert len(jobs._rows) <= 32

    issuer = SandboxGrantIssuer(b"soak-sandbox-key-32-bytes-long!!", clock=clock)
    sandboxes = InMemorySandboxProvider(
        issuer.verification_key,
        clock=clock,
        terminal_ttl_seconds=1,
        max_retained_terminal_items=32,
    )
    sandbox_spec = ResolvedSandboxSpec(
        spec_hash="sha256:soak-sandbox",
        architecture="portable",
        filesystem=FileSystemPolicy(
            allowed_operations=frozenset(FileOperation),
        ),
        policy_hash="sha256:soak-sandbox-policy",
    )
    for index in range(100):
        handle = await sandboxes.provision(
            sandbox_spec, context, run_id=f"soak-sandbox-run-{index}"
        )
        await handle.destroy()
    assert len(sandboxes._rows) <= 32

    now += timedelta(seconds=2)
    trigger = await sandboxes.provision(
        sandbox_spec, context, run_id="soak-sandbox-trigger"
    )
    assert len(sandboxes._rows) == 1
    await trigger.destroy()

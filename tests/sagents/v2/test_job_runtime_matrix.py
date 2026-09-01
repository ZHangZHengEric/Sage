from __future__ import annotations

import asyncio

import pytest

from sagents.v2.runtime.execution.jobs.memory import InMemoryJobRuntime
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.jobs import (
    JobCompletion,
    JobCursor,
    JobPauseBehavior,
    JobSpec,
    JobState,
)


async def echo_runner(spec, emit, cancelled):
    for part in spec.payload.get("parts", []):
        await emit("stdout", part.encode())
        await asyncio.sleep(0)
    return JobCompletion(exit_code=spec.payload.get("exit_code", 0))


async def error_runner(spec, emit, cancelled):
    await emit("stderr", b"before-error")
    raise RuntimeError("runner exploded")


async def blocking_runner(spec, emit, cancelled):
    await emit("progress", b"started")
    await asyncio.Event().wait()
    return JobCompletion()


def runtime(max_concurrent=4):
    return InMemoryJobRuntime(
        {
            "echo": echo_runner,
            "error": error_runner,
            "blocking": blocking_runner,
        },
        max_concurrent_jobs=max_concurrent,
    )


def job_spec(
    key,
    *,
    kind="echo",
    run_id="run_1",
    pause_behavior=JobPauseBehavior.DETACH,
    payload=None,
    max_output_bytes=None,
):
    return JobSpec(
        owner_run_id=run_id,
        kind=kind,
        payload=payload or {},
        pause_behavior=pause_behavior,
        idempotency_key=key,
        max_output_bytes=max_output_bytes,
    )


@pytest.mark.asyncio
async def test_capabilities_are_honest_about_memory_and_suspend():
    capabilities = await runtime().capabilities()
    assert capabilities.durable_across_process_restart is False
    assert capabilities.supports_reconnect is False
    assert capabilities.supports_suspend is False
    assert capabilities.supports_output_cursor is True


@pytest.mark.asyncio
async def test_submit_is_idempotent_and_job_completes_with_nonzero_exit_code():
    jobs = runtime()
    spec = job_spec("job_1", payload={"parts": ["hello", " world"], "exit_code": 7})
    first = await jobs.submit(spec)
    duplicate = await jobs.submit(spec)
    completed = await jobs.wait(first.job_id)

    assert duplicate.job_id == first.job_id
    assert completed.state == JobState.COMPLETED
    assert completed.exit_code == 7
    assert completed.error is None


@pytest.mark.asyncio
async def test_run_scoped_runners_do_not_overwrite_each_other():
    jobs = InMemoryJobRuntime({})

    async def first_runner(spec, emit, cancelled):
        del spec, cancelled
        await emit("stdout", b"first")
        return JobCompletion()

    async def second_runner(spec, emit, cancelled):
        del spec, cancelled
        await emit("stdout", b"second")
        return JobCompletion()

    jobs.register_runner("shell", first_runner, owner_run_id="run_1")
    jobs.register_runner("shell", second_runner, owner_run_id="run_2")
    first = await jobs.submit(job_spec("first", kind="shell", run_id="run_1"))
    second = await jobs.submit(job_spec("second", kind="shell", run_id="run_2"))
    await asyncio.gather(jobs.wait(first.job_id), jobs.wait(second.job_id))

    first_output = await jobs.read_output(JobCursor(job_id=first.job_id))
    second_output = await jobs.read_output(JobCursor(job_id=second.job_id))
    assert b"".join(chunk.data for chunk in first_output) == b"first"
    assert b"".join(chunk.data for chunk in second_output) == b"second"


def test_run_scoped_runner_can_be_released_without_removing_replacement():
    jobs = InMemoryJobRuntime({})

    async def first_runner(spec, emit, cancelled):
        del spec, emit, cancelled
        return JobCompletion()

    async def second_runner(spec, emit, cancelled):
        del spec, emit, cancelled
        return JobCompletion()

    jobs.register_runner("shell", first_runner, owner_run_id="run_1")
    jobs.register_runner("shell", second_runner, owner_run_id="run_1")
    jobs.unregister_runner(
        "shell", owner_run_id="run_1", runner=first_runner
    )
    assert jobs._owner_runners[("run_1", "shell")] is second_runner

    jobs.unregister_runner(
        "shell", owner_run_id="run_1", runner=second_runner
    )
    assert jobs._owner_runners == {}


@pytest.mark.asyncio
async def test_output_cursor_is_exact_incremental_and_bounded():
    jobs = runtime()
    handle = await jobs.submit(
        job_spec("job_1", payload={"parts": ["abc", "def", "ghi"]})
    )
    completed = await jobs.wait(handle.job_id)
    assert completed.output_cursor.offset == 9

    first = await jobs.read_output(JobCursor(job_id=handle.job_id), max_bytes=4)
    assert b"".join(chunk.data for chunk in first) == b"abcd"
    assert first[0].offset == 0
    cursor = JobCursor(job_id=handle.job_id, offset=first[-1].next_offset)
    second = await jobs.read_output(cursor, max_bytes=10)
    assert b"".join(chunk.data for chunk in second) == b"efghi"
    assert second[-1].next_offset == 9
    assert await jobs.read_output(JobCursor(job_id=handle.job_id, offset=9)) == ()


@pytest.mark.asyncio
async def test_output_limit_truncates_payload_without_failing_job():
    jobs = runtime()
    handle = await jobs.submit(
        job_spec(
            "job_1",
            payload={"parts": ["1234", "5678"]},
            max_output_bytes=5,
        )
    )
    completed = await jobs.wait(handle.job_id)
    chunks = await jobs.read_output(JobCursor(job_id=handle.job_id))
    assert completed.state == JobState.COMPLETED
    assert completed.output_cursor.offset == 5
    assert b"".join(chunk.data for chunk in chunks) == b"12345"


@pytest.mark.asyncio
async def test_runner_exception_is_typed_job_failure_and_keeps_prior_output():
    jobs = runtime()
    handle = await jobs.submit(job_spec("job_1", kind="error"))
    failed = await jobs.wait(handle.job_id)
    output = await jobs.read_output(JobCursor(job_id=handle.job_id))

    assert failed.state == JobState.FAILED
    assert failed.error is not None
    assert failed.error.code == "job.runner_failed"
    assert b"".join(chunk.data for chunk in output) == b"before-error"


@pytest.mark.asyncio
async def test_unsupported_kind_and_suspend_pause_behavior_rejected_at_submit():
    jobs = runtime()
    with pytest.raises(SageV2Error) as unsupported:
        await jobs.submit(job_spec("bad", kind="missing"))
    assert unsupported.value.info.code == "job.kind_unsupported"

    with pytest.raises(SageV2Error) as pause:
        await jobs.submit(job_spec("suspend", pause_behavior=JobPauseBehavior.SUSPEND))
    assert pause.value.info.code == "job.pause_behavior_unsupported"


@pytest.mark.asyncio
async def test_cancel_is_idempotent_and_terminal():
    jobs = runtime()
    handle = await jobs.submit(job_spec("job_1", kind="blocking"))
    await asyncio.sleep(0)
    killed = await jobs.cancel(handle.job_id)
    again = await jobs.cancel(handle.job_id)
    assert killed.state == again.state == JobState.KILLED


@pytest.mark.asyncio
async def test_run_pause_behavior_matrix_cancel_vs_continue_and_detach():
    jobs = runtime()
    handles = {}
    for behavior in (
        JobPauseBehavior.CANCEL,
        JobPauseBehavior.CONTINUE,
        JobPauseBehavior.DETACH,
    ):
        handles[behavior] = await jobs.submit(
            job_spec(
                f"job_{behavior.value}",
                kind="blocking",
                pause_behavior=behavior,
            )
        )
    await asyncio.sleep(0)
    snapshots = await jobs.handle_run_pause("run_1")
    states = {snapshot.pause_behavior: snapshot.state for snapshot in snapshots}
    assert states[JobPauseBehavior.CANCEL] == JobState.KILLED
    assert states[JobPauseBehavior.CONTINUE] == JobState.RUNNING
    assert states[JobPauseBehavior.DETACH] == JobState.RUNNING
    await jobs.close()


@pytest.mark.asyncio
async def test_orphan_adoption_validates_owner_and_state():
    jobs = runtime()
    handle = await jobs.submit(job_spec("job_1", kind="blocking"))
    await asyncio.sleep(0)
    orphaned = await jobs.mark_orphaned(handle.job_id)
    assert orphaned.state == JobState.ORPHANED
    with pytest.raises(SageV2Error) as owner:
        await jobs.adopt(handle.job_id, owner_run_id="run_other")
    assert owner.value.info.code == "job.owner_conflict"
    adopted = await jobs.adopt(handle.job_id, owner_run_id="run_1")
    assert adopted.state == JobState.RUNNING
    with pytest.raises(SageV2Error) as state:
        await jobs.adopt(handle.job_id, owner_run_id="run_1")
    assert state.value.info.code == "job.invalid_transition"
    await jobs.close()


@pytest.mark.asyncio
async def test_concurrency_limit_bounds_active_runners():
    active = 0
    maximum = 0
    release = asyncio.Event()

    async def measured_runner(spec, emit, cancelled):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await release.wait()
        active -= 1
        return JobCompletion()

    jobs = InMemoryJobRuntime({"measured": measured_runner}, max_concurrent_jobs=2)
    handles = [
        await jobs.submit(job_spec(f"job_{index}", kind="measured"))
        for index in range(6)
    ]
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert maximum == 2
    release.set()
    snapshots = await asyncio.gather(*(jobs.wait(handle.job_id) for handle in handles))
    assert all(snapshot.state == JobState.COMPLETED for snapshot in snapshots)


@pytest.mark.asyncio
async def test_close_rejects_new_work_and_kills_active_jobs():
    jobs = runtime()
    handle = await jobs.submit(job_spec("job_1", kind="blocking"))
    await asyncio.sleep(0)
    await jobs.close()
    assert (await jobs.inspect(handle.job_id)).state == JobState.KILLED
    with pytest.raises(SageV2Error) as closed:
        await jobs.submit(job_spec("job_2"))
    assert closed.value.info.code == "job.runtime_closed"

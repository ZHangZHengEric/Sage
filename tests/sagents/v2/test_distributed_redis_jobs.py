"""Shared Job contracts at the Redis and asynchronous runner boundaries.

The in-memory matrix covers local lifecycle and bounds. These cases protect
the distributed plugin's shared visibility, idempotency, quotas, remote
cancellation and refusal to publish after a local worker loses its lease.
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import fakeredis
import fakeredis.aioredis
import pytest
import pytest_asyncio

from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.jobs import JobCompletion, JobCursor, JobSpec, JobState
from sagents.v2.runtime.execution.jobs.plugins.redis_distributed import RedisDistributedJobRuntime


def spec(key="start", *, owner="run-a", payload=None, max_output_bytes=None):
    return JobSpec(owner_run_id=owner, kind="test", idempotency_key=key,
                   payload=payload or {}, max_output_bytes=max_output_bytes)


@pytest_asyncio.fixture
async def jobs_pair():
    server = fakeredis.FakeServer()
    pairs = []

    def create(runner_a, runner_b=None, *, key_prefix=None, **options):
        values = []
        options = {"lease_seconds": 1, "poll_interval_seconds": 0.01, **options}
        for runner in (runner_a, runner_b or runner_a):
            value = RedisDistributedJobRuntime(
                {"test": runner}, redis_url="redis://unused/0",
                key_prefix=key_prefix or f"job-test-{len(pairs)}", **options)
            value._redis = fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)
            value._redis.info = AsyncMock(return_value={"maxmemory_policy": "noeviction", "aof_enabled": 1})
            values.append(value)
        pairs.append(values)
        return tuple(values)

    yield create
    for values in pairs:
        for value in values:
            await value.close()


async def output(jobs, job_id, *, offset=0, max_bytes=65536):
    chunks = await jobs.read_output(JobCursor(job_id=job_id, offset=offset), max_bytes=max_bytes)
    return chunks, b"".join(chunk.data for chunk in chunks)


@pytest.mark.asyncio
async def test_remote_inspect_binary_output_cursor_and_wait(jobs_pair):
    started, finish = asyncio.Event(), asyncio.Event()

    async def runner(spec, emit, cancelled):
        await emit("stdout", b"\x00\xffab")
        await emit("stderr", b"\x80cd")
        started.set()
        await finish.wait()
        return JobCompletion(exit_code=7)

    first, second = jobs_pair(runner)
    handle = await first.submit(spec())
    await asyncio.wait_for(started.wait(), 2)
    snapshot = await second.inspect(handle.job_id)
    assert snapshot.state == JobState.RUNNING
    assert snapshot.output_cursor.offset == 7
    initial, initial_bytes = await output(second, handle.job_id, max_bytes=3)
    assert initial_bytes == b"\x00\xffa"
    assert initial[0].offset == 0 and initial[-1].next_offset == 3
    suffix, suffix_bytes = await output(second, handle.job_id, offset=initial[-1].next_offset)
    assert suffix_bytes == b"b\x80cd"
    assert [chunk.stream for chunk in suffix] == ["stdout", "stderr"]
    assert suffix[-1].next_offset == 7
    assert await second.read_output(JobCursor(job_id=handle.job_id, offset=7)) == ()
    waiter = asyncio.create_task(second.wait(handle.job_id))
    finish.set()
    completed = await asyncio.wait_for(waiter, 2)
    assert completed.state == JobState.COMPLETED
    assert completed.exit_code == 7 and completed.error is None
    assert (await first.inspect(handle.job_id)).state == JobState.COMPLETED


@pytest.mark.asyncio
async def test_remote_cancel_actually_stops_the_originating_runner(jobs_pair):
    started, stopped = asyncio.Event(), asyncio.Event()

    async def runner(spec, emit, cancelled):
        try:
            await emit("progress", b"running")
            started.set()
            await asyncio.Event().wait()
        finally:
            stopped.set()

    first, second = jobs_pair(runner)
    handle = await first.submit(spec())
    await asyncio.wait_for(started.wait(), 2)
    killed = await asyncio.wait_for(second.cancel(handle.job_id, force=True), 2)
    await asyncio.wait_for(stopped.wait(), 1)
    assert killed.state == JobState.KILLED
    assert (await first.inspect(handle.job_id)).state == JobState.KILLED
    assert (await second.wait(handle.job_id)).state == JobState.KILLED
    assert (await output(second, handle.job_id))[1] == b"running"


@pytest.mark.asyncio
async def test_owner_scoped_start_idempotency_is_global_and_conflicting_payload_is_rejected(jobs_pair):
    started, finish = asyncio.Event(), asyncio.Event()
    executions = []

    async def runner(request, emit, cancelled):
        executions.append(request.owner_run_id)
        started.set()
        await finish.wait()
        return JobCompletion()

    first, second = jobs_pair(runner)
    one, duplicate = await asyncio.gather(first.submit(spec()), second.submit(spec()))
    assert one.job_id == duplicate.job_id
    await asyncio.wait_for(started.wait(), 2)
    with pytest.raises(SageV2Error) as conflict:
        await second.submit(spec(payload={"command": "different"}))
    assert conflict.value.info.code == "job.idempotency_conflict"
    assert executions == ["run-a"]
    assert [job.job_id for job in await second.list_run_jobs("run-a")] == [one.job_id]
    another_owner = await second.submit(spec(owner="run-b"))
    assert another_owner.job_id != one.job_id
    finish.set()
    completed = await asyncio.wait_for(asyncio.gather(
        first.wait(one.job_id), second.wait(another_owner.job_id)), 2)
    assert all(job.state == JobState.COMPLETED for job in completed)
    assert sorted(executions) == ["run-a", "run-b"]


@pytest.mark.asyncio
async def test_global_concurrency_limit_serializes_runners_from_different_nodes(jobs_pair):
    started = {owner: asyncio.Event() for owner in ("run-a", "run-b")}
    finish = {owner: asyncio.Event() for owner in started}
    active, peak = 0, 0

    async def runner(request, emit, cancelled):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            started[request.owner_run_id].set()
            await finish[request.owner_run_id].wait()
            return JobCompletion()
        finally:
            active -= 1

    first, second = jobs_pair(runner, max_concurrent_jobs=1)
    a = await first.submit(spec())
    await asyncio.wait_for(started["run-a"].wait(), 2)
    b = await second.submit(spec(owner="run-b"))
    assert (await first.inspect(b.job_id)).state == JobState.CREATED
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(started["run-b"].wait(), 0.08)
    finish["run-a"].set()
    await asyncio.wait_for(first.wait(a.job_id), 2)
    await asyncio.wait_for(started["run-b"].wait(), 2)
    finish["run-b"].set()
    assert (await asyncio.wait_for(first.wait(b.job_id), 2)).state == JobState.COMPLETED
    assert peak == 1


@pytest.mark.asyncio
async def test_global_admission_limit_rejects_remote_overflow_without_running_it(jobs_pair):
    started = asyncio.Event()
    executions = []

    async def runner(request, emit, cancelled):
        executions.append(request.owner_run_id)
        started.set()
        await asyncio.Event().wait()

    first, second = jobs_pair(runner, max_admitted_jobs=1)
    await first.submit(spec())
    await asyncio.wait_for(started.wait(), 2)
    with pytest.raises(SageV2Error) as full:
        await second.submit(spec(owner="run-b"))
    assert full.value.info.code == "job.queue_full"
    assert await second.list_run_jobs("run-b") == ()
    assert executions == ["run-a"]


@pytest.mark.asyncio
@pytest.mark.parametrize("bounds,expected", [
    ({"max_job_output_bytes": 5}, b"12345"),
    ({"max_job_output_chunks": 1}, b"1234"),
], ids=["job-bytes", "job-chunks"])
async def test_output_limits_remain_visible_and_exact_on_another_node(jobs_pair, bounds, expected):
    async def runner(request, emit, cancelled):
        await emit("stdout", b"1234")
        await emit("stdout", b"5678")
        return JobCompletion()

    first, second = jobs_pair(runner, **bounds)
    handle = await first.submit(spec())
    completed = await asyncio.wait_for(second.wait(handle.job_id), 2)
    chunks, data = await output(second, handle.job_id)
    assert completed.state == JobState.COMPLETED
    assert completed.output_truncated
    assert data == expected
    assert completed.output_cursor.offset == len(expected)
    assert chunks[-1].next_offset == len(expected)


@pytest.mark.asyncio
@pytest.mark.parametrize("bounds,expected_second", [
    ({"max_buffered_output_bytes": 5}, b"1"),
    ({"max_buffered_output_chunks": 1}, b""),
], ids=["shared-bytes", "shared-chunks"])
async def test_buffered_output_capacity_is_shared_between_nodes(jobs_pair, bounds, expected_second):
    async def runner(request, emit, cancelled):
        await emit("stdout", b"1234")
        return JobCompletion()

    first, second = jobs_pair(runner, **bounds)
    a = await first.submit(spec())
    await asyncio.wait_for(second.wait(a.job_id), 2)
    b = await second.submit(spec(owner="run-b"))
    completed = await asyncio.wait_for(first.wait(b.job_id), 2)
    assert completed.output_truncated
    assert (await output(second, a.job_id))[1] == b"1234"
    assert (await output(first, b.job_id))[1] == expected_second


@pytest.mark.asyncio
async def test_close_stops_only_jobs_owned_by_the_closing_node(jobs_pair):
    started = {owner: asyncio.Event() for owner in ("run-a", "run-b")}
    stopped = {owner: asyncio.Event() for owner in started}
    finish = asyncio.Event()

    async def runner(request, emit, cancelled):
        try:
            started[request.owner_run_id].set()
            await finish.wait()
            return JobCompletion()
        finally:
            stopped[request.owner_run_id].set()

    first, second = jobs_pair(runner)
    a = await first.submit(spec())
    b = await second.submit(spec(owner="run-b"))
    await asyncio.wait_for(asyncio.gather(*(event.wait() for event in started.values())), 2)
    await first.close()
    await asyncio.wait_for(stopped["run-a"].wait(), 1)
    assert (await second.inspect(a.job_id)).state == JobState.KILLED
    assert (await second.inspect(b.job_id)).state == JobState.RUNNING
    assert not stopped["run-b"].is_set()
    finish.set()
    assert (await asyncio.wait_for(second.wait(b.job_id), 2)).state == JobState.COMPLETED


@pytest.mark.asyncio
async def test_expired_owner_cannot_append_or_complete_and_another_node_does_not_replay_it(jobs_pair):
    started, continue_runner, stopped = asyncio.Event(), asyncio.Event(), asyncio.Event()
    executions = []

    async def runner(request, emit, cancelled):
        executions.append("owner")
        try:
            await emit("stdout", b"before")
            started.set()
            await continue_runner.wait()
            try:
                await emit("stdout", b"stale-after")
            except SageV2Error:
                pass
            return JobCompletion()
        finally:
            stopped.set()

    async def remote_runner(request, emit, cancelled):
        executions.append("replayed")
        return JobCompletion()

    first, second = jobs_pair(runner, remote_runner)
    handle = await first.submit(spec())
    await asyncio.wait_for(started.wait(), 2)
    state_key = first.key_prefix + ":state"
    state = json.loads(await second._redis.get(state_key))
    state["rows"][handle.job_id]["lease_until"] = 0
    await second._redis.set(state_key, json.dumps(state))
    continue_runner.set()
    failed = await asyncio.wait_for(second.wait(handle.job_id), 2)
    await asyncio.wait_for(stopped.wait(), 2)
    assert failed.state == JobState.FAILED
    assert failed.error is not None and failed.error.code == "job.worker_lost"
    assert (await output(second, handle.job_id))[1] == b"before"
    assert (await second.inspect(handle.job_id)).state == JobState.FAILED
    assert executions == ["owner"]


@pytest.mark.asyncio
@pytest.mark.parametrize("cleanup_wait,lease_seconds", [(0.08, 1), (0.8, 0.5)],
                         ids=["within-lease", "cleanup-outlives-lease"])
async def test_remote_cancel_waits_for_runner_cleanup_and_stopping_job_keeps_its_global_slot(
    jobs_pair, cleanup_wait, lease_seconds
):
    started, cleanup_started, finish_cleanup, cleanup_done = (
        asyncio.Event() for _ in range(4))
    next_started, finish_next = asyncio.Event(), asyncio.Event()

    async def runner(request, emit, cancelled):
        if request.owner_run_id == "run-b":
            next_started.set()
            await finish_next.wait()
            return JobCompletion()
        try:
            await emit("stdout", b"before-cleanup")
            started.set()
            await asyncio.Event().wait()
        finally:
            cleanup_started.set()
            await finish_cleanup.wait()
            cleanup_done.set()

    first, second = jobs_pair(runner, max_concurrent_jobs=1, lease_seconds=lease_seconds)
    handle = await first.submit(spec())
    await asyncio.wait_for(started.wait(), 2)
    cancelling = asyncio.create_task(second.cancel(handle.job_id, force=True))
    try:
        await asyncio.wait_for(cleanup_started.wait(), 2)
        assert not cleanup_done.is_set()
        assert (await second.inspect(handle.job_id)).state == JobState.STOPPING
        assert not cancelling.done(), "cancel must await the remote runner's cleanup"
        assert (await output(second, handle.job_id))[1] == b"before-cleanup"
        following = await second.submit(spec(owner="run-b"))
        assert (await first.inspect(following.job_id)).state == JobState.CREATED
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(next_started.wait(), cleanup_wait)
        assert (await second.inspect(handle.job_id)).state == JobState.STOPPING
        assert not cancelling.done()
        finish_cleanup.set()
        killed = await asyncio.wait_for(cancelling, 2)
        assert cleanup_done.is_set()
        assert killed.state == JobState.KILLED
        assert (await output(second, handle.job_id))[1] == b"before-cleanup"
        await asyncio.wait_for(next_started.wait(), 2)
        finish_next.set()
        assert (await asyncio.wait_for(first.wait(following.job_id), 2)).state == JobState.COMPLETED
    finally:
        finish_cleanup.set()
        finish_next.set()
        await asyncio.wait_for(asyncio.gather(cancelling, return_exceptions=True), 2)


@pytest.mark.asyncio
async def test_close_immediately_after_submit_leaves_no_unowned_created_job(jobs_pair):
    executions = []

    async def runner(request, emit, cancelled):
        executions.append(request.owner_run_id)
        await asyncio.Event().wait()

    first, second = jobs_pair(runner)
    handle = await first.submit(spec())
    await first.close()
    snapshot = await second.inspect(handle.job_id)
    assert snapshot.state == JobState.KILLED
    assert (await second.wait(handle.job_id)).state == JobState.KILLED
    assert len(executions) <= 1


async def completed_output_runner(request, emit, cancelled):
    await emit("stdout", b"\xffold")
    return JobCompletion()


@pytest.mark.asyncio
async def test_explicit_purge_deletes_shared_metadata_and_output_in_one_redis_transaction(jobs_pair):
    first, second = jobs_pair(completed_output_runner)
    removed = await first.submit(spec())
    kept = await second.submit(spec(owner="run-b"))
    await asyncio.wait_for(asyncio.gather(first.wait(removed.job_id), second.wait(kept.job_id)), 2)
    original_pipeline = second._redis.pipeline
    transactions = []

    def observed_pipeline(*args, **kwargs):
        pipe = original_pipeline(*args, **kwargs)
        execute = pipe.execute

        async def observed_execute(*args, **kwargs):
            transactions.append([command for command, _ in pipe.command_stack])
            return await execute(*args, **kwargs)

        pipe.execute = observed_execute
        return pipe

    second._redis.pipeline = observed_pipeline
    try:
        assert await second.purge_terminal(owner_run_id="run-a") == 1
    finally:
        second._redis.pipeline = original_pipeline
    state_key = first.key_prefix + ":state"
    output_key = first.key_prefix + ":output:" + removed.job_id
    assert any(
        any(command[0] == "SET" and command[1] == state_key for command in transaction)
        and any(command[0] == "DEL" and output_key in command[1:] for command in transaction)
        for transaction in transactions
    ), "purge must publish row removal and output removal in the same EXEC"
    assert not await first._redis.exists(output_key)
    assert not await first._redis.exists(first.key_prefix + ":worker:" + removed.job_id)
    with pytest.raises(SageV2Error) as missing:
        await first.inspect(removed.job_id)
    assert missing.value.info.code == "job.not_found"
    assert (await output(first, kept.job_id))[1] == b"\xffold"


def use_redis_clock(nodes):
    seconds = [1_800_000_000]

    async def current_time():
        return seconds[0], 0

    for node in nodes:
        node._redis.time = current_time
    return seconds


@pytest.mark.asyncio
async def test_reconnect_window_preserves_output_but_applies_finite_admission_and_count_retention(jobs_pair):
    first, second = jobs_pair(completed_output_runner, max_admitted_jobs=1,
                             max_retained_terminal_jobs=1, output_reconnect_window_seconds=10)
    clock = use_redis_clock((first, second))
    oldest = await first.submit(spec("old"))
    await asyncio.wait_for(second.wait(oldest.job_id), 2)
    clock[0] += 1
    newest = await second.submit(spec("new"))
    await asyncio.wait_for(first.wait(newest.job_id), 2)
    assert (await output(second, oldest.job_id))[1] == b"\xffold"
    assert len(await first.list_run_jobs("run-a")) == 2
    with pytest.raises(SageV2Error) as full:
        await first.submit(spec("overflow"))
    assert full.value.info.code == "job.queue_full"
    clock[0] += 11
    retained = await second.list_run_jobs("run-a")
    assert [job.job_id for job in retained] == [newest.job_id]
    assert not await first._redis.exists(first.key_prefix + ":output:" + oldest.job_id)
    assert (await output(first, newest.job_id))[1] == b"\xffold"


@pytest.mark.asyncio
async def test_retained_output_byte_limit_discards_oldest_terminal_output(jobs_pair):
    first, second = jobs_pair(completed_output_runner, max_retained_output_bytes=5,
                             output_reconnect_window_seconds=0)
    clock = use_redis_clock((first, second))
    oldest = await first.submit(spec("old"))
    await asyncio.wait_for(second.wait(oldest.job_id), 2)
    clock[0] += 1
    newest = await second.submit(spec("new"))
    await asyncio.wait_for(first.wait(newest.job_id), 2)
    assert [job.job_id for job in await first.list_run_jobs("run-a")] == [newest.job_id]
    assert not await first._redis.exists(first.key_prefix + ":output:" + oldest.job_id)
    assert (await output(second, newest.job_id))[1] == b"\xffold"


@pytest.mark.asyncio
async def test_terminal_ttl_cannot_remove_output_before_its_reconnect_window(jobs_pair):
    first, second = jobs_pair(completed_output_runner, terminal_ttl_seconds=5,
                             output_reconnect_window_seconds=10)
    clock = use_redis_clock((first, second))
    handle = await first.submit(spec())
    await asyncio.wait_for(second.wait(handle.job_id), 2)
    clock[0] += 9
    assert (await output(second, handle.job_id))[1] == b"\xffold"
    clock[0] += 2
    assert await first.list_run_jobs("run-a") == ()
    assert not await second._redis.exists(second.key_prefix + ":output:" + handle.job_id)


@pytest.mark.asyncio
async def test_same_spec_with_different_dictionary_order_has_one_idempotent_job(jobs_pair):
    first, second = jobs_pair(completed_output_runner)
    a = spec(payload={"command": "echo", "options": {"a": 1, "b": 2}})
    b = spec(payload={"options": {"b": 2, "a": 1}, "command": "echo"})
    handles = await asyncio.gather(first.submit(a), second.submit(b))
    assert handles[0].job_id == handles[1].job_id
    assert (await asyncio.wait_for(second.wait(handles[0].job_id), 2)).state == JobState.COMPLETED


@pytest.mark.asyncio
async def test_new_client_reconnects_to_terminal_job_and_closed_nodes_cannot_overwrite_it(jobs_pair):
    first, second = jobs_pair(completed_output_runner)
    handle = await first.submit(spec())
    completed = await asyncio.wait_for(second.wait(handle.job_id), 2)
    prefix = first.key_prefix
    await first.close()
    await second.close()
    reconnected, _ = jobs_pair(completed_output_runner, key_prefix=prefix)
    assert await reconnected.inspect(handle.job_id) == completed
    assert (await output(reconnected, handle.job_id))[1] == b"\xffold"
    assert (await reconnected.submit(spec())).job_id == handle.job_id


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["await_shell", "kill_shell"])
async def test_shell_tools_refuse_another_runs_remote_job_before_output_or_cancellation(jobs_pair, method):
    from sagents.v2.runtime.execution.sandbox import SandboxGrantIssuer
    from sagents.v2.tool.official.runtime import OfficialToolRuntime

    started, stopped = asyncio.Event(), asyncio.Event()

    async def runner(request, emit, cancelled):
        try:
            await emit("stdout", b"private-run-output")
            started.set()
            await asyncio.Event().wait()
        finally:
            stopped.set()

    first, second = jobs_pair(runner)
    handle = await first.submit(spec())
    await asyncio.wait_for(started.wait(), 2)
    forbidden = OfficialToolRuntime(SimpleNamespace(ref=SimpleNamespace(owner_run_id="run-b")),
                                    SandboxGrantIssuer(), job_runtime=second)
    original_read = second._redis.lrange
    reads = []

    async def observed_read(*args, **kwargs):
        reads.append(args)
        return await original_read(*args, **kwargs)

    second._redis.lrange = observed_read
    with pytest.raises(SageV2Error) as denied:
        if method == "await_shell":
            await forbidden.await_shell(handle.job_id, block_until_ms=0)
        else:
            await forbidden.kill_shell(handle.job_id)
    assert denied.value.info.code == "job.owner_conflict"
    assert denied.value.info.metadata["side_effect_state"] == "not_applied"
    assert reads == []
    second._redis.lrange = original_read
    assert not stopped.is_set()
    assert (await first.inspect(handle.job_id)).state == JobState.RUNNING
    authorized = OfficialToolRuntime(SimpleNamespace(ref=SimpleNamespace(owner_run_id="run-a")),
                                     SandboxGrantIssuer(), job_runtime=second)
    running = await authorized.await_shell(handle.job_id, block_until_ms=0)
    assert running["status"] == "running" and running["stdout"] == "private-run-output"
    killed = await asyncio.wait_for(authorized.kill_shell(handle.job_id), 2)
    assert killed["status"] == "terminated" and killed["stdout"] == "private-run-output"
    assert stopped.is_set()


@pytest.mark.asyncio
async def test_submit_exec_racing_close_cannot_leave_a_created_job_or_live_runner(jobs_pair):
    entered, finish_exec = asyncio.Event(), asyncio.Event()
    active = 0

    async def runner(request, emit, cancelled):
        nonlocal active
        active += 1
        try:
            await asyncio.Event().wait()
        finally:
            active -= 1

    first, second = jobs_pair(runner)
    redis = first._redis
    original_pipeline = redis.pipeline
    paused = False

    def pausing_pipeline(*args, **kwargs):
        pipe = original_pipeline(*args, **kwargs)
        execute = pipe.execute

        async def pausing_execute(*args, **kwargs):
            nonlocal paused
            if not paused and any(command[0] == "SET" and command[1] == first.key_prefix + ":state"
                                  for command, _ in pipe.command_stack):
                paused = True
                entered.set()
                await finish_exec.wait()
            return await execute(*args, **kwargs)

        pipe.execute = pausing_execute
        return pipe

    first._redis.pipeline = pausing_pipeline
    submitting = asyncio.create_task(first.submit(spec()))
    closing = None
    try:
        await asyncio.wait_for(entered.wait(), 2)
        closing = asyncio.create_task(first.close())
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(closing), 0.05)
        finish_exec.set()
        handle, _ = await asyncio.wait_for(asyncio.gather(submitting, closing), 2)
        assert active == 0
        assert (await second.inspect(handle.job_id)).state == JobState.KILLED
        assert all(job.state == JobState.KILLED for job in await second.list_run_jobs("run-a"))
    finally:
        finish_exec.set()
        redis.pipeline = original_pipeline
        await asyncio.gather(submitting, *([closing] if closing else []), return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("cleanup_wait,lease_seconds", [(0.08, 1), (0.8, 0.5)],
                         ids=["within-lease", "cleanup-outlives-lease"])
async def test_cancelling_a_close_caller_does_not_cancel_actual_runner_cleanup(
    jobs_pair, cleanup_wait, lease_seconds
):
    started, cleaning, finish_cleanup, cleaned = (asyncio.Event() for _ in range(4))

    async def runner(request, emit, cancelled):
        try:
            started.set()
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await finish_cleanup.wait()
            cleaned.set()

    first, second = jobs_pair(runner, lease_seconds=lease_seconds)
    handle = await first.submit(spec())
    await asyncio.wait_for(started.wait(), 2)
    closing = asyncio.create_task(first.close())
    try:
        await asyncio.wait_for(cleaning.wait(), 2)
        closing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await closing
        assert not cleaned.is_set()
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(cleaned.wait(), cleanup_wait)
        assert (await second.inspect(handle.job_id)).state in {JobState.RUNNING, JobState.STOPPING}
        finish_cleanup.set()
        await asyncio.wait_for(first.close(), 2)
        assert cleaned.is_set()
        assert (await second.inspect(handle.job_id)).state == JobState.KILLED
    finally:
        finish_cleanup.set()
        await asyncio.gather(closing, return_exceptions=True)
        await first.close()

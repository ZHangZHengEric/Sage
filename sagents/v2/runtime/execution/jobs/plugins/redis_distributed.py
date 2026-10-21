"""Redis Job registry with node-owned runners and fenced output publication.

Jobs remain on the node that owns their sandbox. Other nodes can observe and
cancel them. An expired owner fails the Job; arbitrary commands are never replayed.
"""
from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
import hashlib
import json
import uuid

from sagents.v2.contracts.common import new_id
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.jobs import (
    JobCursor, JobHandle, JobOutputChunk, JobPauseBehavior, JobSnapshot, JobState,
)
from sagents.v2.runtime.execution.jobs.plugins._shared.runtime import JobRuntimeState, TERMINAL_JOB_STATES
from sagents.v2.runtime.distributed.redis_coordination import active_worker_fence, watch_fence


class RedisDistributedJobRuntime(JobRuntimeState):
    plugin_id = "sage.job.redis-distributed"
    name = "Redis distributed Job runtime"
    description = "Shared Job state, byte output, global quotas and remote cancellation."

    def __init__(self, runners=None, *, redis_url, key_prefix="sage:jobs:{distributed}",
                 lease_seconds=30, poll_interval_seconds=0.05, **limits):
        super().__init__(runners or {}, **limits)
        if not redis_url or not key_prefix or min(lease_seconds, poll_interval_seconds) <= 0:
            raise ValueError("Redis URL, prefix and positive Job lease/poll interval are required")
        self.redis_url, self.key_prefix = redis_url, key_prefix
        self.lease_seconds, self.poll_interval_seconds = lease_seconds, poll_interval_seconds
        self._redis = None
        self._redis_ready = False
        self._redis_init_lock = asyncio.Lock()
        self._admission_lock = asyncio.Lock()
        self._local_jobs = {}
        self._local_tokens = {}
        self._node = uuid.uuid4().hex
        self._close_task = None
        self._transport_closed = False

    async def _client(self):
        async with self._redis_init_lock:
            if self._transport_closed:
                raise self._error("job.runtime_closed", ErrorCategory.CANCELLED, "Job runtime is closed")
            if self._redis is None:
                from redis.asyncio import Redis
                self._redis = Redis.from_url(self.redis_url, decode_responses=True,
                    socket_connect_timeout=5, socket_timeout=5)
            if not self._redis_ready:
                memory = await self._redis.info("memory")
                persistence = await self._redis.info("persistence")
                if memory.get("maxmemory_policy") != "noeviction" or not persistence.get("aof_enabled"):
                    raise ValueError("Distributed Jobs require Redis noeviction and AOF persistence")
                self._redis_ready = True
        return self._redis

    async def capabilities(self):
        return (await super().capabilities()).model_copy(update={
            "durable_across_process_restart": True, "supports_reconnect": True,
            "supports_adoption": False, "multi_process_writes": True,
            "supports_remote_cancel": True})

    async def start(self, context, dependencies):
        await self._mutate(lambda rows, now: (None, None))
        return {"execution.job-runtime": self}

    def _output_key(self, job_id):
        return self.key_prefix + ":output:" + job_id

    def _limits(self):
        return [self._max_concurrent, self._max_admitted, self._max_job_output_bytes,
            self._max_job_output_chunks, self._max_buffered_output_bytes,
            self._max_buffered_output_chunks, self._terminal_ttl.total_seconds(),
            self._max_retained_terminal_jobs, self._max_retained_output_bytes,
            self._output_reconnect_window.total_seconds(), self.lease_seconds]

    async def _mutate(self, operation, *, admission=False):
        from redis.exceptions import WatchError
        redis = await self._client()
        key = self.key_prefix + ":state"
        for _ in range(100):
            async with redis.pipeline() as pipe:
                try:
                    await pipe.watch(key)
                    if admission and (fence := active_worker_fence.get()) is not None:
                        if fence.redis_url != self.redis_url:
                            raise ValueError("Job and worker fencing must use the same Redis URL")
                        await watch_fence(pipe, fence)
                    raw = await pipe.get(key)
                    state = json.loads(raw) if raw else {"format_version": "sage.redis-jobs/v1", "limits": self._limits(), "rows": {}}
                    if state.get("format_version") != "sage.redis-jobs/v1":
                        raise ValueError("Unsupported distributed Job state format")
                    if state["limits"] != self._limits():
                        raise ValueError("Distributed Job instances must use identical shared limits")
                    seconds, micros = await redis.time()
                    now = seconds + micros / 1e6
                    rows = state["rows"]
                    occupied = sum(row["state"] in {JobState.RUNNING, JobState.STOPPING} for row in rows.values())
                    original_rows = {job_id: (row["owner"], row["state"], row["lease_until"])
                                     for job_id, row in rows.items()}
                    removed = self._sweep(rows, now)
                    operation_error = None
                    try:
                        result, output = operation(rows, now)
                    except Exception as exc:
                        if raw is None:
                            raise
                        # Persist expiration even when the requested Job has
                        # just expired. Roll back any partial operation first.
                        state = json.loads(raw)
                        rows = state["rows"]
                        removed = self._sweep(rows, now)
                        result, output, operation_error = None, None, exc
                    removed.extend(set(original_rows).difference(rows).difference(removed))
                    encoded = json.dumps(state, separators=(",", ":"), sort_keys=True)
                    if encoded != raw or output or removed:
                        pipe.multi()
                        pipe.set(key, encoded)
                        updated_occupied = sum(row["state"] in {JobState.RUNNING, JobState.STOPPING}
                                               for row in rows.values())
                        if raw is None or updated_occupied != occupied:
                            pipe.set(self.key_prefix + ":occupied", updated_occupied)
                        for job_id in removed:
                            pipe.delete(self._output_key(job_id))
                            pipe.delete(self.key_prefix + ":worker:" + job_id)
                        for job_id, row in rows.items():
                            if original_rows.get(job_id) != (row["owner"], row["state"], row["lease_until"]):
                                pipe.set(self.key_prefix + ":worker:" + job_id, json.dumps({
                                    "owner": row["owner"], "state": row["state"], "lease_until": row["lease_until"]}))
                        if output:
                            job_id, chunk = output
                            pipe.rpush(self._output_key(job_id), json.dumps(chunk, separators=(",", ":")))
                        await pipe.execute()
                    if operation_error is not None:
                        raise operation_error
                    return result
                except WatchError:
                    continue
        raise SageV2Error(RuntimeErrorInfo(code="job.coordination_busy", category=ErrorCategory.CONFLICT,
            message="Job registry is busy; retry", retryable=True, safe_to_resume=True))

    def _sweep(self, rows, now):
        for row in rows.values():
            if row["state"] not in TERMINAL_JOB_STATES and row["lease_until"] <= now:
                row.update(state=JobState.FAILED.value, updated_at=self._date(now),
                    error=RuntimeErrorInfo(code="job.worker_lost", category=ErrorCategory.RESOURCE_LOST,
                        message="Job worker lease expired; the command was not replayed",
                        safe_to_resume=False).model_dump(mode="json"))
        terminal = sorted((r for r in rows.values() if r["state"] in TERMINAL_JOB_STATES),
            key=lambda r: (r["updated_at"], r["job_id"]))
        retained_count = len(terminal)
        retained_bytes = sum(r["output_cursor"]["offset"] for r in terminal)
        removed = []
        for row in terminal:
            age = now - datetime.fromisoformat(row["updated_at"]).timestamp()
            if age < self._output_reconnect_window.total_seconds():
                continue
            if (age >= self._terminal_ttl.total_seconds()
                    or retained_count > self._max_retained_terminal_jobs
                    or retained_bytes > self._max_retained_output_bytes):
                removed.append(row["job_id"])
                retained_count -= 1
                retained_bytes -= row["output_cursor"]["offset"]
        for job_id in removed:
            del rows[job_id]
        return removed

    @staticmethod
    def _date(now):
        return datetime.fromtimestamp(now, timezone.utc).isoformat()

    def _get(self, rows, job_id):
        if job_id not in rows:
            raise self._error("job.not_found", ErrorCategory.VALIDATION, f"Job {job_id!r} was not found")
        return rows[job_id]

    @staticmethod
    def _snapshot_record(row):
        return JobSnapshot.model_validate({key: value for key, value in row.items()
            if key in JobSnapshot.model_fields})

    async def submit(self, spec):
        async with self._admission_lock:
            return await self._submit(spec)

    async def _submit(self, spec):
        self._ensure_open()
        runner = self._owner_runners.get((spec.owner_run_id, spec.kind)) or self._runners.get(spec.kind)
        token, job_id = uuid.uuid4().hex, new_id("job")
        fingerprint = hashlib.sha256(json.dumps(spec.model_dump(mode="json"), sort_keys=True,
                                               separators=(",", ":")).encode()).hexdigest()
        def admit(rows, now):
            for row in rows.values():
                if row["spec"]["owner_run_id"] == spec.owner_run_id and row["spec"]["idempotency_key"] == spec.idempotency_key:
                    if row["spec"]["fingerprint"] != fingerprint:
                        raise self._error("job.idempotency_conflict", ErrorCategory.CONFLICT, "Job idempotency key has different input")
                    return self._snapshot_record(row), None
            if runner is None:
                raise self._error("job.kind_unsupported", ErrorCategory.VALIDATION, f"No runner registered for {spec.kind!r}")
            if spec.pause_behavior == JobPauseBehavior.SUSPEND:
                raise self._error("job.pause_behavior_unsupported", ErrorCategory.VALIDATION, "Local commands cannot be frozen across nodes")
            if (sum(r["state"] not in TERMINAL_JOB_STATES for r in rows.values()) >= self._max_admitted
                    or len(rows) >= self._max_admitted + self._max_retained_terminal_jobs):
                raise SageV2Error(RuntimeErrorInfo(code="job.queue_full", category=ErrorCategory.RATE_LIMITED,
                    message="Shared Job admission capacity is full", retryable=True, safe_to_resume=True))
            row = JobSnapshot(job_id=job_id, owner_run_id=spec.owner_run_id, kind=spec.kind,
                state=JobState.CREATED, pause_behavior=spec.pause_behavior,
                execution_affinity=spec.execution_affinity,
                output_cursor=JobCursor(job_id=job_id), created_at=self._date(now), updated_at=self._date(now)).model_dump(mode="json")
            row.update(spec={"owner_run_id": spec.owner_run_id, "idempotency_key": spec.idempotency_key,
                             "fingerprint": fingerprint}, owner=token, node=self._node,
                lease_until=now + self.lease_seconds, chunks=0)
            rows[job_id] = row
            return self._snapshot_record(row), None
        snapshot = await self._mutate(admit, admission=True)
        if snapshot.job_id == job_id:
            task = asyncio.create_task(self._execute_shared(job_id, token, spec, runner), name=f"sage-redis-job:{job_id}")
            self._local_jobs[job_id] = task
            self._local_tokens[job_id] = token
            def settled(done):
                self._local_jobs.pop(job_id, None)
                self._local_tokens.pop(job_id, None)
            task.add_done_callback(settled)
        return JobHandle.model_validate(snapshot.model_dump(include=set(JobHandle.model_fields)))

    def _owned(self, rows, job_id, token, now):
        row = self._get(rows, job_id)
        if row["owner"] != token or row["lease_until"] <= now or row["state"] in TERMINAL_JOB_STATES:
            raise self._error("job.fence_rejected", ErrorCategory.RESOURCE_LOST, "Job worker no longer owns publication")
        return row

    async def _execute_shared(self, job_id, token, spec, runner):
        cancel_event = asyncio.Event()
        stop_requested = asyncio.Event()
        runner_task = None
        final_update = None
        async def heartbeat():
            next_renewal = 0
            while True:
                await asyncio.sleep(min(self.poll_interval_seconds, self.lease_seconds / 3))
                # A small per-Job signal avoids polling the full bounded registry
                # for every running process. The CAS registry remains authoritative.
                signal = await (await self._client()).get(self.key_prefix + ":worker:" + job_id)
                status = json.loads(signal) if signal else None
                if status is None or status["owner"] != token:
                    cancel_event.set()
                    raise asyncio.CancelledError
                if status["state"] == JobState.STOPPING:
                    cancel_event.set()
                    stop_requested.set()
                loop_time = asyncio.get_running_loop().time()
                if loop_time < next_renewal:
                    continue
                def renew(rows, now):
                    row = self._owned(rows, job_id, token, now)
                    row["lease_until"] = now + self.lease_seconds
                    return True, None
                if not await self._mutate(renew):
                    cancel_event.set()
                    raise asyncio.CancelledError
                next_renewal = loop_time + self.lease_seconds / 3
        monitor = asyncio.create_task(heartbeat())
        stop_waiter = asyncio.create_task(stop_requested.wait())
        try:
            while True:
                if stop_requested.is_set():
                    raise asyncio.CancelledError
                occupied = await (await self._client()).get(self.key_prefix + ":occupied")
                if occupied is not None and int(occupied) >= self._max_concurrent:
                    if monitor.done():
                        await monitor
                    await asyncio.sleep(self.poll_interval_seconds)
                    continue
                def claim(rows, now):
                    row = self._owned(rows, job_id, token, now)
                    if row["state"] == JobState.STOPPING:
                        return "cancel", None
                    if sum(r["state"] in {JobState.RUNNING, JobState.STOPPING} for r in rows.values()
                           if r["job_id"] != job_id) >= self._max_concurrent:
                        return "wait", None
                    row.update(state=JobState.RUNNING.value, updated_at=self._date(now))
                    return "start", None
                decision = await self._mutate(claim)
                if decision == "cancel":
                    raise asyncio.CancelledError
                if decision == "start":
                    break
                if monitor.done():
                    await monitor
                await asyncio.sleep(self.poll_interval_seconds)
            async def emit(stream, data):
                if stream not in {"stdout", "stderr", "progress"} or not isinstance(data, bytes):
                    raise ValueError("Job output requires a supported stream and bytes")
                def append(rows, now):
                    row = self._owned(rows, job_id, token, now)
                    if row["state"] == JobState.STOPPING:
                        raise asyncio.CancelledError
                    size = row["output_cursor"]["offset"]
                    available = max(0, min(spec.max_output_bytes or self._max_job_output_bytes,
                        self._max_job_output_bytes) - size)
                    available = min(available, max(0, self._max_buffered_output_bytes - sum(r["output_cursor"]["offset"] for r in rows.values())))
                    if row["chunks"] >= self._max_job_output_chunks or sum(r["chunks"] for r in rows.values()) >= self._max_buffered_output_chunks:
                        available = 0
                    accepted = data[:available]
                    row["output_truncated"] |= len(accepted) < len(data)
                    row.update(updated_at=self._date(now))
                    if not accepted:
                        return None, None
                    row["output_cursor"]["offset"] += len(accepted)
                    row["chunks"] += 1
                    return None, (job_id, dict(job_id=job_id, stream=stream, offset=size,
                        next_offset=size+len(accepted), data=base64.b64encode(accepted).decode(), occurred_at=self._date(now)))
                await self._mutate(append)
            runner_task = asyncio.ensure_future(runner(spec, emit, cancel_event))
            done, _ = await asyncio.wait({runner_task, monitor, stop_waiter}, return_when=asyncio.FIRST_COMPLETED)
            if monitor in done:
                await monitor
                raise RuntimeError("Job heartbeat stopped")
            if stop_waiter in done:
                raise asyncio.CancelledError
            completion = await runner_task
            def complete(row):
                row.update(state=JobState.COMPLETED.value, exit_code=completion.exit_code,
                    usage=completion.usage.model_dump(mode="json"))
            final_update = complete
        except asyncio.CancelledError:
            def final_update(row):
                row.update(state=JobState.KILLED.value)
        except Exception as exc:
            error = exc.info if hasattr(exc, "info") else RuntimeErrorInfo(
                code="job.runner_failed", category=ErrorCategory.PROVIDER_PERMANENT, message=str(exc), safe_to_resume=False)
            def final_update(row):
                row.update(state=JobState.FAILED.value, error=error.model_dump(mode="json"))
        finally:
            cancel_event.set()
            async def cleanup():
                # Keep renewing while the actual process is reaped. STOPPING
                # still occupies a slot even when cleanup exceeds one lease.
                if runner_task is not None:
                    runner_task.cancel()
                    await asyncio.gather(runner_task, return_exceptions=True)
                monitor.cancel()
                stop_waiter.cancel()
                await asyncio.gather(monitor, stop_waiter, return_exceptions=True)
                if final_update is not None:
                    await self._finish(job_id, token, final_update)
            cleanup_task = asyncio.create_task(cleanup())
            while not cleanup_task.done():
                try:
                    await asyncio.shield(cleanup_task)
                except asyncio.CancelledError:
                    continue
            await cleanup_task

    async def _finish(self, job_id, token, update):
        def finish(rows, now):
            row = rows.get(job_id)
            if row and row["owner"] == token and row["lease_until"] > now and row["state"] not in TERMINAL_JOB_STATES:
                update(row)
                if row["state"] == JobState.COMPLETED and row.pop("cancel_requested", False):
                    row["state"] = JobState.KILLED.value
                row["updated_at"] = self._date(now)
            return None, None
        try:
            await self._mutate(finish)
        except Exception:
            # Do not regain ownership after a failed write; readers expire this lease.
            return

    async def inspect(self, job_id):
        return await self._mutate(lambda rows, now: (self._snapshot_record(self._get(rows, job_id)), None))

    async def wait(self, job_id):
        while True:
            snapshot = await self.inspect(job_id)
            if snapshot.state in TERMINAL_JOB_STATES:
                return snapshot
            await asyncio.sleep(self.poll_interval_seconds)

    async def cancel(self, job_id, *, force=False):
        def request(rows, now):
            row = self._get(rows, job_id)
            if row["state"] not in TERMINAL_JOB_STATES:
                row.update(state=JobState.STOPPING.value, cancel_requested=True, updated_at=self._date(now))
            return self._snapshot_record(row), None
        snapshot = await self._mutate(request)
        if snapshot.state in TERMINAL_JOB_STATES:
            return snapshot
        return await self.wait(job_id)

    async def read_output(self, cursor, *, max_bytes=65536):
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        snapshot = await self.inspect(cursor.job_id)
        values = await (await self._client()).lrange(self._output_key(cursor.job_id), 0, -1)
        chunks, remaining = [], max_bytes
        for value in values:
            chunk = json.loads(value)
            if chunk["next_offset"] <= cursor.offset or chunk["offset"] >= snapshot.output_cursor.offset:
                continue
            start = max(0, cursor.offset - chunk["offset"])
            data = base64.b64decode(chunk["data"])[start:start+remaining]
            if data:
                chunk.update(offset=chunk["offset"]+start, data=data)
                chunk["next_offset"] = chunk["offset"] + len(data)
                chunks.append(JobOutputChunk.model_validate(chunk))
                remaining -= len(data)
            if not remaining:
                break
        return tuple(chunks)

    async def list_run_jobs(self, run_id):
        return await self._mutate(lambda rows, now: (tuple(self._snapshot_record(r) for r in rows.values()
            if r["owner_run_id"] == run_id), None))

    async def handle_run_pause(self, run_id):
        jobs = await self.list_run_jobs(run_id)
        for job in jobs:
            if job.state not in TERMINAL_JOB_STATES and job.pause_behavior == JobPauseBehavior.CANCEL:
                await self.cancel(job.job_id)
        return await self.list_run_jobs(run_id)

    async def mark_orphaned(self, job_id):
        raise self._error("job.adoption_unsupported", ErrorCategory.VALIDATION, "Local processes cannot move between nodes")

    async def adopt(self, job_id, *, owner_run_id):
        raise self._error("job.adoption_unsupported", ErrorCategory.VALIDATION, "Local processes cannot move between nodes")

    async def purge_terminal(self, *, owner_run_id):
        def purge(rows, now):
            ids = [j for j, r in rows.items() if r["owner_run_id"] == owner_run_id and r["state"] in TERMINAL_JOB_STATES]
            for job_id in ids:
                del rows[job_id]
            return len(ids), None
        return await self._mutate(purge)

    async def close(self):
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close_owned())
        await asyncio.shield(self._close_task)

    async def _close_owned(self):
        async with self._admission_lock:
            self._closed = True
            tasks = tuple(self._local_jobs.values())
            tokens = dict(self._local_tokens)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        def settle(rows, now):
            for row in rows.values():
                if (row["owner"] == tokens.get(row["job_id"])
                        and row["state"] not in TERMINAL_JOB_STATES):
                    row.update(state=JobState.KILLED.value, updated_at=self._date(now))
            return None, None
        try:
            if self._redis is not None:
                await self._mutate(settle)
        finally:
            self._transport_closed = True
            if self._redis is not None:
                await self._redis.aclose()
                self._redis = None

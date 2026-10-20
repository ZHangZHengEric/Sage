"""Shared Scheduler using Redis CAS and short per-Run mutation guards.

The bounded queue reuses the reference scheduling rules. A revisioned Redis
snapshot makes admission, quotas, claims and monotonic fence allocation atomic
across processes. No process owns the namespace for its lifetime.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import heapq
import json
import time

from sagents.v2.runtime.plugins._shared.redis_coordination import (
    RedisGuard, RedisMutationFence, active_worker_fence, coordination_error,
    watch_fence,
)
from sagents.v2.runtime.execution.scheduler.plugins._shared.queue import (
    SchedulerQueue, SchedulerQuotaGroup,
)


class RedisDistributedScheduler:
    default_lease_seconds = 30
    plugin_id = "sage.scheduler.redis-distributed"
    name = "Redis distributed scheduler"
    description = "Shared admission, priority, quotas, worker leases and fencing."

    def __init__(self, *, redis_url, key_prefix="sage:scheduler:{distributed}",
                 max_pending_items=1024, max_retained_terminal_items=4096,
                 max_concurrent_runs=8, max_concurrent_runs_per_tenant=2,
                 coordination_ttl_seconds=30, poll_seconds=0.05, queue_id="default"):
        if not redis_url or not key_prefix or min(max_pending_items, max_concurrent_runs,
                max_concurrent_runs_per_tenant, coordination_ttl_seconds, poll_seconds) <= 0:
            raise ValueError("Redis URL, prefix and positive Scheduler limits are required")
        if max_retained_terminal_items < 0:
            raise ValueError("Terminal retention must be nonnegative")
        self.redis_url, self.key_prefix = redis_url, key_prefix
        self.max_pending_items = max_pending_items
        self.max_retained_terminal_items = max_retained_terminal_items
        self.max_concurrent_runs = max_concurrent_runs
        self.max_concurrent_runs_per_tenant = max_concurrent_runs_per_tenant
        self.coordination_ttl_seconds, self.poll_seconds = coordination_ttl_seconds, poll_seconds
        self.queue_id = queue_id
        self._redis = None
        self._closed = False

    async def _client(self):
        if self._closed:
            raise SchedulerQueue._error("scheduler.closed", self._cancelled_category(), "Scheduler is closed")
        if self._redis is None:
            from redis.asyncio import Redis
            self._redis = Redis.from_url(self.redis_url, decode_responses=True,
                socket_connect_timeout=5, socket_timeout=5)
        return self._redis

    @staticmethod
    def _cancelled_category():
        from sagents.v2.contracts.errors import ErrorCategory
        return ErrorCategory.CANCELLED

    def _guard_key(self, run_id):
        return self.key_prefix + ":mutation:" + run_id

    def _reference(self, now, state):
        group = SchedulerQuotaGroup(self.max_concurrent_runs,
            self.max_concurrent_runs_per_tenant, self.max_pending_items)
        value = SchedulerQueue(max_pending_items=self.max_pending_items,
            max_retained_terminal_items=self.max_retained_terminal_items,
            quota_group=group, clock=lambda: now)
        if state is not None:
            value._load_state(state)
        return value

    async def _mutate(self, operation, *, blocked_run=None, blocked_work=None, claim_queue=False, submitted_work=None):
        from redis.exceptions import WatchError
        redis = await self._client()
        state_key = self.key_prefix + ":state"
        collisions = 0
        while collisions < 100:
            blocked = False
            async with redis.pipeline() as pipe:
                try:
                    await pipe.watch(state_key)
                    raw = await pipe.get(state_key)
                    state = json.loads(raw) if raw else None
                    limits = [self.max_pending_items, self.max_retained_terminal_items,
                              self.max_concurrent_runs, self.max_concurrent_runs_per_tenant]
                    if state is not None and state.get("_limits", limits) != limits:
                        raise ValueError("Distributed Scheduler instances must use identical shared limits")
                    queues = dict(state.get("_queues", {})) if state else {}
                    seconds, microseconds = await redis.time()
                    now = datetime.fromtimestamp(seconds + microseconds / 1e6, timezone.utc)
                    reference = self._reference(now, state)
                    runs = {lease.work.run_id for lease in reference._leases.values()}
                    if blocked_run:
                        runs.add(blocked_run)
                    if blocked_work and blocked_work in reference._items:
                        blocked_run = reference._items[blocked_work].run_id
                        runs.add(blocked_run)
                    keys = [self._guard_key(rid) for rid in sorted(runs)]
                    if keys:
                        await pipe.watch(*keys)
                        guards = await pipe.mget(keys)
                        reference._fenced_runs = {rid for rid, guard in zip(sorted(runs), guards) if guard}
                    if blocked_run and blocked_run in reference._fenced_runs:
                        blocked = True
                    else:
                        other_queues = []
                        if claim_queue:
                            reference._reap_expired_locked()
                            other_queues = [entry for entry in reference._pending
                                if queues.get(entry[3], "default") != self.queue_id]
                            reference._pending = [entry for entry in reference._pending
                                if queues.get(entry[3], "default") == self.queue_id]
                            heapq.heapify(reference._pending)
                        result = await operation(reference)
                        if submitted_work is not None and result:
                            queues[submitted_work.work_id] = self.queue_id
                        for entry in other_queues:
                            heapq.heappush(reference._pending, entry)
                        snapshot = reference._dump_state_locked()
                        snapshot["_queues"] = {wid: queue for wid, queue in queues.items() if wid in reference._items}
                        snapshot["_limits"] = limits
                        if state == snapshot:
                            return result
                        encoded = json.dumps(snapshot, separators=(",", ":"))
                        pipe.multi()
                        pipe.set(state_key, encoded)
                        await pipe.execute()
                        return result
                except WatchError:
                    pass
            if blocked:
                await asyncio.sleep(self.poll_seconds)
            else:
                collisions += 1
                await asyncio.sleep(0)
            if self._closed:
                await self._client()
        raise coordination_error("Distributed scheduler was repeatedly modified; retry the operation",
            code="scheduler.busy", retryable=True)

    async def capabilities(self):
        value = self._reference(datetime.now(timezone.utc), None)
        original = await value.capabilities()
        return original.model_copy(update={"durable_across_process_restart": True,
            "supports_distributed_claims": True})

    async def start(self, context, dependencies):
        redis = await self._client()
        await redis.ping()
        memory, persistence = await asyncio.gather(redis.info("memory"), redis.info("persistence"))
        if memory.get("maxmemory_policy") != "noeviction" or not persistence.get("aof_enabled"):
            raise ValueError("Distributed Scheduler requires Redis noeviction and AOF persistence")
        return {"execution.scheduler": self}

    async def submit(self, work):
        return await self._mutate(lambda value: value.submit(work), submitted_work=work)

    async def claim(self, worker_id, *, lease_duration, policy=None, wait_timeout=None):
        if wait_timeout is not None and wait_timeout < 0:
            raise ValueError("wait_timeout must be nonnegative")
        deadline = None if wait_timeout is None else time.monotonic() + wait_timeout
        while True:
            result = await self._mutate(lambda value: value.claim(worker_id,
                lease_duration=lease_duration, policy=policy, wait_timeout=0), claim_queue=True)
            if result is not None or (deadline is not None and time.monotonic() >= deadline):
                return result
            delay = self.poll_seconds if deadline is None else min(self.poll_seconds, max(0, deadline - time.monotonic()))
            await asyncio.sleep(delay)

    async def renew(self, lease, *, lease_duration):
        return await self._mutate(lambda value: value.renew(lease, lease_duration=lease_duration))

    async def release(self, lease, reason, *, requeue=False, available_at=None):
        return await self._mutate(lambda value: value.release(lease, reason,
            requeue=requeue, available_at=available_at), blocked_run=lease.work.run_id)

    async def assert_fence(self, lease):
        return await self._mutate(lambda value: value.assert_fence(lease))

    async def execute_fenced(self, lease, operation):
        redis = await self._client()
        await self.assert_fence(lease)
        async with RedisGuard(redis, self._guard_key(lease.work.run_id),
                ttl_seconds=self.coordination_ttl_seconds) as guard:
            async def validate(value):
                current = value._assert_fence_locked(lease)
                if current.expires_at <= value._clock():
                    raise coordination_error("Worker lease expired before entering a mutation")
            await self._mutate(validate)
            fence = RedisMutationFence(self.redis_url, guard.key, guard.token)
            token = active_worker_fence.set(fence)
            try:
                result = await operation()
                # A backend must also check this fence inside its actual write
                # transaction. The distributed SessionStore does so via _owned.
                async with redis.pipeline() as pipe:
                    await watch_fence(pipe, fence)
                return result
            finally:
                active_worker_fence.reset(token)

    async def reschedule_pending(self, work_id, available_at):
        return await self._mutate(lambda value: value.reschedule_pending(work_id, available_at))

    async def cancel(self, work_id):
        return await self._mutate(lambda value: value.cancel(work_id), blocked_work=work_id)

    async def pending_count(self):
        return await self._mutate(lambda value: value.pending_count())

    async def reap_expired(self):
        return await self._mutate(lambda value: value.reap_expired())

    async def close(self):
        if self._closed:
            return
        self._closed = True
        if self._redis is not None:
            await self._redis.aclose()

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
import random
import time
import uuid

from sagents.v2.runtime.distributed.redis_coordination import (
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
        self._mutation_lock = asyncio.Lock()

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

    @property
    def _limits(self):
        return [self.max_pending_items, self.max_retained_terminal_items,
                self.max_concurrent_runs, self.max_concurrent_runs_per_tenant]

    @staticmethod
    def _claim_prefix(epoch):
        return '{"claim_epoch":"' + epoch + '",'

    def _claim_head_key(self):
        return self.key_prefix + ":claim-head:v1"

    def _claim_due_key(self, queue):
        return self.key_prefix + ":claim-due:v1:" + queue

    @staticmethod
    def _pending_scores(state):
        if state is None:
            return {}
        queues = state.get("_queues", {})
        leased = {row["work"]["work_id"] for row in state["leases"]}
        pending = {row["work_id"] for row in state["items"]} - leased - set(state["cancelled"])
        result = {}
        for timestamp, _, _, work_id in state["pending"]:
            if work_id in pending:
                bucket = result.setdefault(queues.get(work_id, "default"), {})
                bucket[work_id] = min(timestamp, bucket.get(work_id, float("inf")))
        return result

    def _publish_claim_index(self, pipe, reference, before, snapshot, epoch, *, indexed, prior_counts):
        previous = self._pending_scores(before) if indexed else {}
        current = self._pending_scores(snapshot)
        for queue in set(previous) | set(current) | set(prior_counts) | {self.queue_id}:
            key = self._claim_due_key(queue)
            old, new = previous.get(queue, {}), current.get(queue, {})
            if not indexed:
                pipe.delete(key)
            elif removed := old.keys() - new.keys():
                pipe.zrem(key, *removed)
            if changed := {wid: score for wid, score in new.items() if score != old.get(wid)}:
                pipe.zadd(key, changed)
        expiry = min((lease.expires_at.timestamp() for lease in reference._leases.values()),
                     default=float("inf"))
        counts = {queue: len(scores) for queue, scores in current.items()}
        pipe.set(self._claim_head_key(), json.dumps([epoch, self._limits, counts, len(reference._leases), str(expiry)]))

    async def _may_claim(self):
        redis = await self._client()
        due_key = self._claim_due_key(self.queue_id)
        prefix_len = len(self._claim_prefix("0" * 32))
        async with redis.pipeline(transaction=True) as pipe:
            pipe.getrange(self.key_prefix + ":state", 0, prefix_len - 1)
            pipe.get(self._claim_head_key())
            pipe.zrange(due_key, 0, 0, withscores=True)
            pipe.zcard(due_key)
            pipe.time()
            prefix, head, earliest, count, (seconds, micros) = await pipe.execute()
        if not head:
            return True
        epoch, limits, counts, leased, expiry = json.loads(head)
        if prefix != self._claim_prefix(epoch) or count != counts.get(self.queue_id, 0):
            return True
        if limits != self._limits:
            raise ValueError("Distributed Scheduler instances must use identical shared limits")
        now = seconds + micros / 1e6
        return now >= float(expiry) or (leased < self.max_concurrent_runs and bool(earliest) and earliest[0][1] <= now)

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
        async def attempt():
            nonlocal blocked_run
            # Serialize snapshot writers so a burst of workers does not copy
            # the same large snapshot and repeatedly lose their EXEC.
            async with (
                self._mutation_lock,
                RedisGuard(redis, self.key_prefix + ":queue-updates",
                           ttl_seconds=self.coordination_ttl_seconds) as writer,
                redis.pipeline() as pipe,
            ):
                if claim_queue and not await self._may_claim():
                    return False, None
                await watch_fence(pipe, writer)
                await pipe.watch(state_key)
                raw = await pipe.get(state_key)
                large = raw is not None and len(raw) > 256 * 1024
                state = (await asyncio.to_thread(json.loads, raw) if large else json.loads(raw)) if raw else None
                limits = self._limits
                epoch = state.pop("claim_epoch", "") if state is not None else ""
                head = await pipe.get(self._claim_head_key())
                due_key = self._claim_due_key(self.queue_id)
                indexed, counts, next_expiry = False, {}, float("inf")
                if head:
                    head_epoch, _, counts, _, expiry = json.loads(head)
                    if (epoch == head_epoch and raw and raw.startswith(self._claim_prefix(epoch))
                            and await pipe.zcard(due_key) == counts.get(self.queue_id, 0)):
                        indexed, next_expiry = True, float(expiry)
                if state is not None and state.get("_limits", limits) != limits:
                    raise ValueError("Distributed Scheduler instances must use identical shared limits")
                queues = dict(state.get("_queues", {})) if state else {}
                seconds, microseconds = await redis.time()
                now = datetime.fromtimestamp(seconds + microseconds / 1e6, timezone.utc)
                narrowed = claim_queue and indexed and now.timestamp() < next_expiry
                untouched = []
                loaded_state = state
                if narrowed:
                    candidates = set(await pipe.zrangebyscore(due_key, "-inf", now.timestamp()))
                    candidates_pending = []
                    for entry in state["pending"]:
                        (candidates_pending if entry[3] in candidates else untouched).append(entry)
                    retained = candidates | {row["work"]["work_id"] for row in state["leases"]}
                    loaded_state = state | {
                        "pending": candidates_pending,
                        "items": [row for row in state["items"] if row["work_id"] in retained],
                    }
                reference = (await asyncio.to_thread(self._reference, now, loaded_state)
                             if large and not narrowed else self._reference(now, loaded_state))
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
                    return True, None
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
                if narrowed:
                    # No expiry occurred, so a claim can only change the due
                    # heap and leases. Keep the other work rows byte-for-byte.
                    snapshot["items"] = state["items"]
                    snapshot["pending"].extend(untouched)
                    heapq.heapify(snapshot["pending"])
                item_ids = {row["work_id"] for row in snapshot["items"]}
                snapshot["_queues"] = {wid: queue for wid, queue in queues.items() if wid in item_ids}
                snapshot["_limits"] = limits
                if indexed and (state == snapshot or (narrowed and result is None)):
                    return False, result
                epoch = uuid.uuid4().hex
                if large:
                    body = await asyncio.to_thread(json.dumps, snapshot, separators=(",", ":"))
                else:
                    body = json.dumps(snapshot, separators=(",", ":"))
                encoded = self._claim_prefix(epoch) + body[1:]
                pipe.multi()
                pipe.set(state_key, encoded)
                self._publish_claim_index(pipe, reference, state, snapshot, epoch, indexed=indexed, prior_counts=counts)
                await pipe.execute()
                return False, result

        collisions = 0
        while collisions < 100:
            try:
                blocked, result = await attempt()
            except WatchError:
                collisions += 1
                await asyncio.sleep(random.uniform(0, min(0.025, collisions * 0.001)))
            else:
                if not blocked:
                    return result
                await asyncio.sleep(self.poll_seconds)
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

    async def existing_work_ids(self):
        redis = await self._client()
        raw = await redis.get(self.key_prefix + ":state")
        if not raw:
            return frozenset()

        def identities():
            state = json.loads(raw)
            return frozenset(item["work_id"] for item in state["items"]) | frozenset(state.get("cancelled", ()))

        return await asyncio.to_thread(identities)

    async def restore_queued(self, work):
        return await self._mutate(lambda value: value.restore_queued(work), submitted_work=work)

    async def claim(self, worker_id, *, lease_duration, policy=None, wait_timeout=None):
        if lease_duration.total_seconds() <= 0:
            raise ValueError("lease_duration must be positive")
        if wait_timeout is not None and wait_timeout < 0:
            raise ValueError("wait_timeout must be nonnegative")
        deadline = None if wait_timeout is None else time.monotonic() + wait_timeout
        while True:
            result = None
            if await self._may_claim():
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

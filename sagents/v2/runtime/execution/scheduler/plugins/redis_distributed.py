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
from weakref import WeakValueDictionary

from sagents.v2.runtime.distributed.redis_coordination import (
    RedisGuard, RedisMutationFence, active_worker_fence, coordination_error,
    watch_fence,
)
from sagents.v2.runtime.execution.scheduler.plugins._shared.queue import (
    SchedulerQueue, SchedulerQuotaGroup,
)


# Several worker pools can share a Redis namespace in one event loop.
# Queue their local transactions fairly before contending for the Redis CAS.
_NAMESPACE_LOCKS = WeakValueDictionary()


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
        self._namespace_lock = None

    @property
    def _mutation_lock(self):
        if self._namespace_lock is None:
            key = (asyncio.get_running_loop(), self.redis_url, self.key_prefix)
            self._namespace_lock = _NAMESPACE_LOCKS.setdefault(key, asyncio.Lock())
        return self._namespace_lock

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

    @staticmethod
    def _decode_state(raw):
        # Each appended receipt is an atomic claim of a previously pending
        # item. The next ordinary mutation folds receipts into the snapshot.
        base, *receipts = raw.split("\x1e")
        state = json.loads(base)
        for encoded in receipts:
            receipt = json.loads(encoded)
            lease = receipt["lease"]
            if expired := receipt.get("expired"):
                state["leases"] = [row for row in state["leases"] if row["lease_id"] not in expired]
                retries = receipt["retries"]
                state["items"] = [retries.get(row["work_id"], row) for row in state["items"]]
                state["pending"].extend(receipt["pending"])
                state["sequence"] = receipt["sequence"]
            state["leases"].append(lease)
            state["fence_sequence"] = lease["fencing_token"]
            # Before another receipt can requeue an expired item, remove
            # the pending entry consumed by its original claim.
            state["pending"] = [entry for entry in state["pending"] if entry[3] != lease["work"]["work_id"]]
        return state

    def _encode_layout(self, snapshot, epoch):
        # ASCII JSON makes string positions equal Redis byte offsets. Old
        # workers read the exact same v1 object through their normal decoder.
        tail_keys = ("leases", "fence_sequence", "sequence", "terminal_idempotency_keys", "cancelled")
        fixed = {k: v for k, v in snapshot.items() if k not in {"items", "pending", "idempotency", *tail_keys}}
        chunks = [self._claim_prefix(epoch), json.dumps(fixed, separators=(",", ":"))[1:-1], ',"idempotency":{']
        offset = sum(map(len, chunks))
        layout = {}
        positions = {"item": {}, "receipt": {}}
        for index, (key, wid) in enumerate(snapshot["idempotency"].items()):
            entry = json.dumps({key: wid}, separators=(",", ":"))[1:-1]
            if index:
                chunks.append(",")
                offset += 1
            positions["receipt"][key] = offset
            layout["receipt:" + key] = json.dumps([offset, offset + len(entry) - 1, wid])
            chunks.append(entry)
            offset += len(entry)
        chunks.append('},"items":[')
        offset += len(chunks[-1])
        spans = {}
        for index, item in enumerate(snapshot["items"]):
            raw = json.dumps(item, separators=(",", ":")) + " " * 32
            if index:
                chunks.append(",")
                offset += 1
            spans[item["work_id"]] = [offset, offset + len(raw) - 1]
            chunks.append(raw)
            offset += len(raw)
        separator = '],"pending":['
        chunks.append(separator)
        offset += len(separator)
        pending = [(entry[3], entry) for entry in snapshot["pending"] if entry[3] in spans]
        pending_ids = {wid for wid, _ in pending}
        # A queue rewrite may take place while a lease is active. Reserve
        # that work's retry slot too, including space for its escaped ID.
        for lease in snapshot["leases"]:
            wid = lease["work"]["work_id"]
            if wid in spans and wid not in pending_ids:
                pending.append((wid, None))
        for index, (wid, entry) in enumerate(pending):
            if entry is None:
                raw = '[0,0,0,""]' + " " * (64 + len(json.dumps(wid)))
            else:
                raw = json.dumps(entry, separators=(",", ":")) + " " * 32
            if index:
                chunks.append(",")
                offset += 1
            spans[wid].extend((offset, offset + len(raw) - 1))
            chunks.append(raw)
            offset += len(raw)
        chunks.append("],")
        layout.update({"work:" + wid: json.dumps(span) for wid, span in spans.items() if len(span) == 4})
        for wid, span in spans.items():
            positions["item"][wid] = span[0]
            layout["item:" + wid] = json.dumps([*span[:2], snapshot["_queues"].get(wid, "default")])
        # Claims and heartbeats need only the bounded active lease suffix.
        # Releases can also update the adjacent terminal receipt history.
        history = json.dumps({key: snapshot[key] for key in tail_keys[2:]}, separators=(",", ":"))[1:-1] + ","
        chunks.append(history)
        layout.update({"epoch": epoch, "release-tail": str(offset + 2), "tail": str(offset + 2 + len(history))})
        chunks.append(json.dumps({key: snapshot[key] for key in tail_keys[:2]}, separators=(",", ":"))[1:])
        return "".join(chunks), layout, positions

    async def _indexed_claim(self, pipe, state_key, operation):
        layout_key = self.key_prefix + ":claim-layout"
        redis = await self._client()
        due = self._claim_due_key(self.queue_id)
        async with redis.pipeline(transaction=False) as reads:
            reads.hmget(layout_key, ("epoch", "tail"))
            reads.getrange(state_key, 0, len(self._claim_prefix("0"*32)) - 1)
            reads.get(self._claim_head_key())
            reads.time()
            reads.zcard(due)
            (epoch, tail), prefix, raw_head, (seconds, micros), due_count = await reads.execute()
        if not epoch or tail is None or prefix != self._claim_prefix(epoch):
            return NotImplemented
        if not raw_head:
            return NotImplemented
        version, limits, counts, leased, expiry = json.loads(raw_head)
        now = datetime.fromtimestamp(seconds + micros / 1e6, timezone.utc)
        if version != epoch or limits != self._limits or now.timestamp() >= float(expiry):
            return NotImplemented
        if due_count != counts.get(self.queue_id, 0):
            return NotImplemented
        ids = await pipe.zrangebyscore(due, "-inf", now.timestamp())
        if not ids or leased >= self.max_concurrent_runs:
            return None
        async with redis.pipeline(transaction=False) as reads:
            reads.getrange(state_key, int(tail), -1)
            reads.hmget(layout_key, ["work:" + wid for wid in ids])
            raw_tail, bounds = await reads.execute()
        if "\x1e" in raw_tail:
            return NotImplemented
        active = json.loads("{" + raw_tail)
        if not all(bounds):
            return NotImplemented
        spans = dict(zip(ids, map(json.loads, bounds)))
        async with redis.pipeline(transaction=False) as reads:
            for start, end, entry_start, entry_end in spans.values():
                reads.getrange(state_key, start, end)
                reads.getrange(state_key, entry_start, entry_end)
            parts = await reads.execute()
        # A legacy writer can replace the layout between range reads. Check
        # WATCH before interpreting those potentially unrelated byte ranges.
        if await pipe.getrange(state_key, 0, len(prefix) - 1) != prefix:
            from redis.exceptions import WatchError
            raise WatchError()
        rows = [json.loads(value) for value in parts[::2]]
        pending = [json.loads(value) for value in parts[1::2]]
        if any(row["work_id"] != wid or entry[3] != wid for wid, row, entry in zip(ids, rows, pending, strict=True)):
            return NotImplemented
        reference = self._reference(now, {**active, "format": "sage.scheduler-state/v1",
                                           "items": rows, "pending": pending})
        lease = await operation(reference)
        if lease is None:
            return None
        wid = lease.work.work_id
        start, end = spans[wid][2:]
        # An unresolvable heap entry is discarded by all v1 queue readers.
        empty = '[0,0,0,""]'.ljust(end - start + 1)
        active["leases"].append(lease.model_dump(mode="json"))
        active["fence_sequence"] = lease.fencing_token
        encoded_tail = json.dumps(active, separators=(",", ":"))[1:]
        counts[self.queue_id] -= 1
        head = [epoch, limits, counts, leased + 1, str(min(float(expiry), lease.expires_at.timestamp()))]
        pipe.multi()
        pipe.setrange(state_key, start, empty)
        pipe.setrange(state_key, int(tail), encoded_tail.ljust(len(raw_tail)))
        pipe.zrem(due, wid)
        pipe.set(self._claim_head_key(), json.dumps(head))
        await pipe.execute()
        return lease

    async def _try_claim(self, operation):
        from redis.exceptions import WatchError

        redis = await self._client()
        state_key = self.key_prefix + ":state"
        # Indexed claims change only a few byte ranges. CAS coordinates them
        # with older workers and with the slower snapshot writer.
        for _ in range(16):
            async with self._mutation_lock, redis.pipeline() as pipe:
                try:
                    await pipe.watch(state_key)
                    try:
                        result = await self._indexed_claim(pipe, state_key, operation)
                        if result is NotImplemented:
                            pipe.multi()
                            pipe.ping()
                            await pipe.execute()
                        return result
                    except (ValueError, IndexError, KeyError, TypeError):
                        # A concurrent full write can move a range between
                        # reads. Distinguish that race from a broken index.
                        pipe.multi()
                        pipe.ping()
                        await pipe.execute()
                        return NotImplemented
                except WatchError:
                    await asyncio.sleep(random.uniform(0.001, 0.01))
        return NotImplemented

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
                if claim_queue:
                    lease = await self._indexed_claim(pipe, state_key, operation)
                    if lease is not NotImplemented:
                        return False, lease
                raw = await pipe.get(state_key)
                large = raw is not None and len(raw) > 256 * 1024
                state = (await asyncio.to_thread(self._decode_state, raw) if large else self._decode_state(raw)) if raw else None
                limits = self._limits
                epoch = state.pop("claim_epoch", "") if state is not None else ""
                head = await pipe.get(self._claim_head_key())
                due_key = self._claim_due_key(self.queue_id)
                indexed, counts = False, {}
                if head:
                    head_epoch, _, counts, _, _ = json.loads(head)
                    if (epoch == head_epoch and raw and raw.startswith(self._claim_prefix(epoch))
                            and await pipe.zcard(due_key) == counts.get(self.queue_id, 0)):
                        indexed = True
                if state is not None and state.get("_limits", limits) != limits:
                    raise ValueError("Distributed Scheduler instances must use identical shared limits")
                queues = dict(state.get("_queues", {})) if state else {}
                seconds, microseconds = await redis.time()
                now = datetime.fromtimestamp(seconds + microseconds / 1e6, timezone.utc)
                reference = (await asyncio.to_thread(self._reference, now, state)
                             if large else self._reference(now, state))
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
                item_ids = {row["work_id"] for row in snapshot["items"]}
                snapshot["_queues"] = {wid: queue for wid, queue in queues.items() if wid in item_ids}
                snapshot["_limits"] = limits
                if indexed and state == snapshot and "\x1e" not in raw and await pipe.hget(self.key_prefix + ":claim-layout", "epoch") == epoch:
                    return False, result
                epoch = uuid.uuid4().hex
                if large:
                    encoded, layout, positions = await asyncio.to_thread(self._encode_layout, snapshot, epoch)
                else:
                    encoded, layout, positions = self._encode_layout(snapshot, epoch)
                pipe.multi()
                layout_key = self.key_prefix + ":claim-layout"
                pipe.delete(layout_key)
                pipe.hset(layout_key, mapping=layout)
                for name, scores in positions.items():
                    order_key = self.key_prefix + ":" + name + "-positions"
                    pipe.delete(order_key)
                    if scores:
                        pipe.zadd(order_key, scores)
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
        await self._mutate(lambda queue: queue.pending_count())
        return {"execution.scheduler": self}

    async def submit(self, work):
        return await self._mutate(lambda value: value.submit(work), submitted_work=work)

    async def existing_work_ids(self):
        redis = await self._client()
        raw = await redis.get(self.key_prefix + ":state")
        if not raw:
            return frozenset()

        def identities():
            state = json.loads(raw.partition("\x1e")[0])
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
                def select(queue):
                    return queue.claim(worker_id, lease_duration=lease_duration, policy=policy, wait_timeout=0)
                result = await self._try_claim(select)
                if result is NotImplemented:
                    result = await self._mutate(select, claim_queue=True)
            if result is not None or (deadline is not None and time.monotonic() >= deadline):
                return result
            delay = self.poll_seconds if deadline is None else min(self.poll_seconds, max(0, deadline - time.monotonic()))
            await asyncio.sleep(delay)

    @staticmethod
    def _erase_json_entry(patches, key, start, end, first):
        # Erase one adjacent comma too, keeping the array/object valid even
        # after neighboring entries were previously blanked in place.
        if first[0][0] != key:
            start -= 1
        elif len(first) > 1:
            patches.append((int(first[1][1]) - 1, " "))
        patches.append((start, " " * (end - start + 1)))

    async def _update_lease(self, lease, operation, *, release=False, requeue=False):
        """Patch the v1 document under the same fence used by snapshot writers."""
        from redis.exceptions import WatchError

        redis = await self._client()
        state_key = self.key_prefix + ":state"
        layout = self.key_prefix + ":claim-layout"
        positions = self.key_prefix + ":item-positions"
        wid = lease.work.work_id
        guard = self._guard_key(lease.work.run_id)
        for _ in range(32):
            async with self._mutation_lock, redis.pipeline() as pipe:
                try:
                    await pipe.watch(state_key, guard)
                    offset_field = "release-tail" if release else "tail"
                    epoch, tail, item, pending = await pipe.hmget(layout, ("epoch", offset_field, "item:" + wid, "work:" + wid))
                    if not item or not epoch or tail is None:
                        return NotImplemented
                    prefix = self._claim_prefix(epoch)
                    async with redis.pipeline(transaction=True) as reads:
                        reads.getrange(state_key, 0, len(prefix) - 1)
                        reads.getrange(state_key, int(tail), -1)
                        reads.get(self._claim_head_key())
                        reads.exists(guard)
                        reads.time()
                        if release and not requeue:
                            reads.zrange(positions, 0, 1, withscores=True)
                        actual, raw, head, guarded, (seconds, micros), *order = await reads.execute()
                    if actual != prefix:
                        return NotImplemented
                    # Validate reads before decoding variable offsets.
                    expected_start = '"sequence":' if release else '"leases":'
                    if not raw.startswith(expected_start) or "\x1e" in raw or not head:
                        return NotImplemented
                    active = json.loads("{" + raw)
                    version, limits, counts, _, _ = json.loads(head)
                    if version != epoch or limits != self._limits:
                        return NotImplemented
                    if guarded and release:
                        return NotImplemented
                    now = datetime.fromtimestamp(seconds + micros / 1e6, timezone.utc)
                    reference = self._reference(now, {**active, "format": "sage.scheduler-state/v1"})
                    if guarded:
                        reference._fenced_runs.add(lease.work.run_id)
                    result = await operation(reference)
                    patches = []
                    removed_receipt = None
                    start, end, queue = json.loads(item)
                    if release and requeue:
                        if not pending:
                            return NotImplemented
                        _, _, low, high = json.loads(pending)
                        retry = reference._items[wid]
                        entry = reference._pending[0]
                        for a, b, value in ((start, end, retry.model_dump(mode="json")), (low, high, entry)):
                            encoded = json.dumps(value, separators=(",", ":"))
                            if len(encoded) > b - a + 1:
                                return NotImplemented
                            patches.append((a, encoded.ljust(b - a + 1)))
                        counts[queue] = counts.get(queue, 0) + 1
                    elif release:
                        first = order[0]
                        if not first:
                            return NotImplemented
                        self._erase_json_entry(patches, wid, start, end, first)
                        keys = active["terminal_idempotency_keys"]
                        if len(keys) >= self.max_retained_terminal_items:
                            retired = keys[0] if keys else lease.work.idempotency_key
                            receipt = await pipe.hget(layout, "receipt:" + retired)
                            if receipt is None:
                                return NotImplemented
                            low, high, prior_wid = json.loads(receipt)
                            if prior_wid == wid or not await pipe.hexists(layout, "item:" + prior_wid):
                                earliest = await pipe.zrange(self.key_prefix + ":receipt-positions", 0, 1, withscores=True)
                                if not earliest:
                                    return NotImplemented
                                self._erase_json_entry(patches, retired, low, high, earliest)
                                reference._cancelled.discard(prior_wid)
                                removed_receipt = retired
                    updated = reference._dump_state_locked()
                    lease_tail = json.dumps({key: updated[key] for key in ("leases", "fence_sequence")},
                                            separators=(",", ":"))[1:]
                    history = ""
                    if release:
                        history = json.dumps({key: updated[key] for key in ("sequence", "terminal_idempotency_keys", "cancelled")},
                                             separators=(",", ":"))[1:-1] + ","
                    encoded = history + lease_tail
                    expiry = min((row.expires_at.timestamp() for row in reference._leases.values()), default=float("inf"))
                    pipe.multi()
                    for offset, value in patches:
                        pipe.setrange(state_key, offset, value)
                    pipe.setrange(state_key, int(tail), encoded.ljust(len(raw)))
                    if release:
                        pipe.hset(layout, "tail", int(tail) + len(history))
                    pipe.set(self._claim_head_key(), json.dumps([epoch, limits, counts, len(updated["leases"]), str(expiry)]))
                    if removed_receipt is not None:
                        pipe.zrem(self.key_prefix + ":receipt-positions", removed_receipt)
                        pipe.hdel(layout, "receipt:" + removed_receipt)
                    if release and requeue:
                        pipe.zadd(self._claim_due_key(queue), {wid: entry[0]})
                    elif release:
                        pipe.zrem(positions, wid)
                        pipe.hdel(layout, "item:" + wid, "work:" + wid)
                    await pipe.execute()
                    return result
                except WatchError:
                    continue
        return NotImplemented

    async def renew(self, lease, *, lease_duration):
        def update(value):
            return value.renew(lease, lease_duration=lease_duration)
        result = await self._update_lease(lease, update)
        return await self._mutate(update) if result is NotImplemented else result

    async def release(self, lease, reason, *, requeue=False, available_at=None):
        def update(value):
            return value.release(lease, reason, requeue=requeue, available_at=available_at)
        result = await self._update_lease(lease, update, release=True, requeue=requeue)
        if result is NotImplemented:
            await self._mutate(update, blocked_run=lease.work.run_id)

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

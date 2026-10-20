"""Multi-instance Redis execution state with existing MySQL archival.

Short per-Session guards serialize state-machine mutations. Every Redis write
watches those guards and the executing worker's fence. Reads refresh cached
aggregates under their local lock; subscriptions replay shared canonical data.
"""
from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
from contextvars import ContextVar
import hashlib
import json
import uuid

from sagents.v2.contracts.common import new_id
from sagents.v2.contracts.events import (
    EventDurability,
    EventSource,
    EventSourceType,
    ProtocolEventData,
    RuntimeEvent,
)
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.runtime.plugins._shared.redis_coordination import (
    RedisGuard,
    active_worker_fence,
    coordination_error,
    watch_fence,
)
from .state import _MysqlSessionState, _json
from .redis import _RedisMysqlSessionState
from .distributed_archive import DistributedMysqlSessionArchive


class _DistributedRedisMysqlState(_RedisMysqlSessionState):
    cache_read_projections = False
    def __init__(self, *args, coordination_ttl_seconds=30, coordination_wait_seconds=10,
                 event_poll_seconds=0.1, max_preview_events=2048, preview_retention_seconds=300, **kwargs):
        explicit_prefix = kwargs.get("key_prefix")
        super().__init__(*args, **kwargs)
        self._archive = DistributedMysqlSessionArchive(self.dsn, table_prefix=self.table_prefix)
        if not explicit_prefix:
            self.key_prefix += ":distributed"
        if min(coordination_ttl_seconds, coordination_wait_seconds, event_poll_seconds) <= 0:
            raise ValueError("Distributed coordination and event intervals must be positive")
        self.coordination_ttl_seconds = coordination_ttl_seconds
        self.coordination_wait_seconds = coordination_wait_seconds
        self.event_poll_seconds = event_poll_seconds
        if min(max_preview_events, preview_retention_seconds) < 1:
            raise ValueError("Preview bounds must be positive")
        self.max_preview_events, self.preview_retention_seconds = max_preview_events, preview_retention_seconds
        self._guards = ContextVar("distributed_session_guards", default=())
        self._publication_epoch = ContextVar("distributed_preview_epoch", default=None)

    @property
    def capabilities(self):
        return {**super().capabilities, "multi_process_writes": True,
                "cross_process_subscribe": True, "atomic_worker_fence": True}

    def composition_identity(self):
        return {**super().composition_identity(), "plugin": DistributedRedisMysqlSessionStore.plugin_id}

    async def _ensure_ready(self):
        if self._closed:
            raise self._storage_error("Distributed Redis SessionStore is closed")
        if self._redis_ready:
            return
        async with self._redis_init_lock:
            if self._redis_ready:
                return
            if self._redis is None:
                from redis.asyncio import Redis
                self._redis = Redis.from_url(self.redis_url, decode_responses=True,
                    socket_connect_timeout=5, socket_timeout=5)
            await self._redis.ping()
            memory = await self._redis.info("memory")
            persistence = await self._redis.info("persistence")
            if memory.get("maxmemory_policy") != "noeviction" or not persistence.get("aof_enabled"):
                raise self._storage_error("Redis execution state requires noeviction and AOF persistence")
            self._redis_ready = True
            self._worker = asyncio.create_task(self._archive_loop())

    @asynccontextmanager
    async def _guard(self, identity):
        await self._ensure_ready()
        key = self._key("guard:" + identity)
        if any(guard.key == key for guard in self._guards.get()):
            yield
            return
        async with RedisGuard(self._redis, key, ttl_seconds=self.coordination_ttl_seconds,
                              wait_seconds=self.coordination_wait_seconds) as guard:
            token = self._guards.set((*self._guards.get(), guard))
            try:
                yield
            finally:
                self._guards.reset(token)

    async def _owned(self, pipe):
        for guard in self._guards.get():
            await watch_fence(pipe, guard)
        fence = active_worker_fence.get()
        if fence is not None:
            if fence.redis_url != self.redis_url:
                raise coordination_error("Scheduler and SessionStore must share the same Redis URL")
            await watch_fence(pipe, fence)

    @asynccontextmanager
    async def _session_operation(self, *session_ids):
        async with AsyncExitStack() as stack:
            for sid in sorted(set(session_ids)):
                await stack.enter_async_context(self._guard("session:" + sid))
            async with super()._session_operation(*session_ids):
                yield

    async def _prepare_session_access(self, session_id):
        await self._ensure_ready()
        revision, deleted = await self._redis.hmget(self._session_key(session_id), "revision", "deleted")
        local = self._persisted_session_revisions.get(session_id)
        if session_id in self._recovery_required or deleted == "1" or revision != (str(local) if local is not None else None):
            await self._reload_session_from_storage_locked(session_id)
            self._recovery_required.discard(session_id)
        if deleted == "1":
            raise self._not_found("session.not_found", session_id)

    @asynccontextmanager
    async def _run_session_read(self, run_id):
        try:
            async with super()._run_session_read(run_id):
                yield
        except SageV2Error as exc:
            if exc.info.code == "session.not_found":
                raise self._not_found("run.not_found", run_id) from exc
            raise

    async def create_run(self, command, context):
        scope = (context.actor.tenant_id, context.actor.principal_type,
                 context.actor.principal_id, command.idempotency_key)
        identity = hashlib.sha256(_json(scope).encode()).hexdigest()
        async with AsyncExitStack() as stack:
            if command.parent_run_id or command.session_concurrency_mode.value == "fork":
                await stack.enter_async_context(self._guard("topology"))
            await stack.enter_async_context(self._guard("start:" + identity))
            # Admission's key is global to the actor, including requests which
            # have not chosen a Session yet. Session revision CAS alone cannot
            # deduplicate two independently generated Session identities.
            lookup = await self._read_start_lookup(command, context)
            previous = self._start_idempotency.get(scope)
            cached = self._runs.get(previous)
            if cached is not None:
                try:
                    async with self._session_read(cached.session_id):
                        pass
                except SageV2Error as exc:
                    if exc.info.code != "session.not_found":
                        raise
            if lookup is not None:
                await self._ensure_session_loaded(lookup)
                async with self._session_read(lookup):
                    pass
            if command.session_id is not None:
                async with self._session_read(command.session_id):
                    pass
            return await super().create_run(command, context)

    async def delete_session(self, session_id):
        async with self._guard("topology"):
            return await super().delete_session(session_id)

    async def _ensure_session_loaded(self, sid, *, missing_ok=False):
        # Refresh only under the local Session lock, never evict a mutation
        # which another task on this instance is still publishing.
        await _MysqlSessionState._ensure_session_loaded(self, sid, missing_ok=missing_ok)

    async def list_dispatchable_runs(self):
        from sagents.v2.runtime.session.state import SessionStoreCoordinator
        await self._ensure_ready()
        resident = set(await self._redis.smembers(self._key("resident")))
        for sid in sorted(resident):
            try:
                await self.get_session(sid)
            except SageV2Error as exc:
                if exc.info.code != "session.not_found":
                    raise
        return tuple(intent for intent in await SessionStoreCoordinator.list_dispatchable_runs(self)
                     if intent.run.session_id in resident)

    async def has_nonterminal_runs(self):
        from sagents.v2.contracts.run_state import TERMINAL_RUN_STATES
        await self._ensure_ready()
        resident, suspended = await asyncio.gather(self._redis.smembers(self._key("resident")),
                                                  self._redis.smembers(self._key("suspended")))
        rows, _ = await self._run_metadata_batch(tuple(set(resident) | set(suspended)))
        return any(row.state not in TERMINAL_RUN_STATES for row in rows)

    async def _ensure_resource_loaded(self, collection, identity_key, identity):
        try:
            await super()._ensure_resource_loaded(collection, identity_key, identity)
        except SageV2Error as exc:
            if exc.info.code == "session.not_found":
                kind = {"runs": "run", "checkpoints": "checkpoint", "suspensions": "suspension",
                        "interactions": "interaction", "session_commit_proposals": "session.commit_proposal"}[collection]
                raise self._not_found(kind + ".not_found", identity) from exc
            raise

    async def get_derived_state(self, sid, namespace, key):
        await self.get_session(sid)
        return await super().get_derived_state(sid, namespace, key)

    async def _write_derived(self, sid, namespace, key, value, *, delete=False):
        await self._ensure_session_loaded(sid)
        async with self._session_operation(sid):
            async def write():
                async with self._redis.pipeline() as pipe:
                    await self._owned(pipe)
                    pipe.multi()
                    if delete:
                        pipe.hdel(self._key(f"derived:{sid}"), self._lookup_key((namespace, key)))
                    else:
                        pipe.hset(self._key(f"derived:{sid}"), self._lookup_key((namespace, key)), _json(value))
                    await pipe.execute()
            await self._retry_transaction(write)

    async def put_derived_state(self, sid, namespace, key, value):
        await self._write_derived(sid, namespace, key, value)

    async def delete_derived_state(self, sid, namespace, key):
        await self._write_derived(sid, namespace, key, None, delete=True)

    async def forget_session(self, sid):
        from sagents.v2.runtime.session.state import SessionStoreCoordinator
        await self._ensure_session_loaded(sid)
        async with self._session_operation(sid):
            await SessionStoreCoordinator.forget_session(self, sid)
            async def write():
                async with self._redis.pipeline() as pipe:
                    await self._owned(pipe)
                    pipe.multi()
                    pipe.delete(self._key(f"derived:{sid}"))
                    await pipe.execute()
            await self._retry_transaction(write)

    async def _archive_session(self, sid, *, prefetched=None):
        # Share the Session guard with mutations, deletion and compaction.
        # Read after claiming it: prefetched state may precede another writer.
        async with self._guard("session:" + sid):
            if not await self._redis.sismember(self._key("pending"), sid):
                return
            async with self._archive.session_guard(sid):
                async with self._redis.pipeline() as pipe:
                    await self._owned(pipe)
                await super()._archive_session(sid)
                if await self._redis.hget(self._session_key(sid), "deleted") == "1":
                    # Never reload a deleted identity from an older archive.
                    await self._redis.persist(self._session_key(sid))

    def _preview_epoch_for_run(self, run_id):
        return self._publication_epoch.get() or self._preview_epoch

    async def publish_stream_preview(self, *, run_id, **options):
        run = await self.get_run(run_id)
        async with self._guard("session:" + run.session_id):
            key = self._key("previews:" + run_id)
            fields = await self._redis.hgetall(key)
            epoch = fields.get("epoch") or uuid.uuid4().hex
            self._preview_sequences[run_id] = int(fields.get("sequence", 0))
            self._stream_previews[run_id] = [RuntimeEvent.model_validate(row)
                for row in json.loads(fields.get("events", "[]"))]
            token = self._publication_epoch.set(epoch)
            try:
                result = await super().publish_stream_preview(run_id=run_id, **options)
            finally:
                self._publication_epoch.reset(token)
            events = self._stream_previews.get(run_id, ())[-self.max_preview_events:]
            encoded = _json([event.model_dump(mode="json") for event in events])
            async def write():
                async with self._redis.pipeline() as pipe:
                    await self._owned(pipe)
                    pipe.multi()
                    pipe.hset(key, mapping={"epoch": epoch,
                        "sequence": self._preview_sequences[run_id], "events": encoded})
                    pipe.expire(key, self.preview_retention_seconds)
                    await pipe.execute()
            await self._retry_transaction(write)
            return result

    async def read_stream_previews(self, run_id, *, after_preview_sequence=0):
        from sagents.v2.contracts.run_state import TERMINAL_RUN_STATES
        run = await self.get_run(run_id)
        if run.state in TERMINAL_RUN_STATES:
            return ()
        raw = await self._redis.hget(self._key("previews:" + run_id), "events")
        events = tuple(RuntimeEvent.model_validate(row) for row in json.loads(raw or "[]"))
        completed = {event.item_id for event in await self.read_events(run_id)
            if event.type in {"message.completed", "reasoning.completed", "item.completed"}}
        return tuple(event for event in events if (event.preview_sequence or 0) > after_preview_sequence
                     and event.item_id not in completed)

    async def _preview_gap(self, run_id, epoch, previous_sequence, state, run_sequence):
        run = await self.get_run(run_id)
        context = await self.get_run_context(run_id)
        return RuntimeEvent(event_id=new_id("event"), type="stream.gap", occurred_at=self._clock(),
            durability=EventDurability.REPLAY_BUFFERED, session_id=run.session_id, run_id=run_id,
            run_sequence=run_sequence, preview_sequence=max(previous_sequence, 1), preview_epoch=epoch,
            actor=context.actor, source=EventSource(source_type=EventSourceType.PROTOCOL),
            data=ProtocolEventData(state=state, from_sequence=previous_sequence,
                to_sequence=previous_sequence, partial_items={}))

    async def subscribe_events(self, cursor):
        # Canonical events are the replay authority. Polling is deliberately
        # independent of Pub/Sub delivery, reconnects and process-local queues.
        sequence = cursor.run_sequence
        preview_sequence, epoch = cursor.preview_sequence, cursor.preview_epoch
        while not self._closed:
            events = await self.read_events(cursor.run_id, after_sequence=sequence, limit=self._subscriber_queue_size)
            for event in events:
                if event.run_sequence > sequence:
                    sequence = event.run_sequence
                    yield event
            if len(events) >= self._subscriber_queue_size:
                continue  # Drain the durable backlog before live previews.
            current_epoch = await self._redis.hget(self._key("previews:" + cursor.run_id), "epoch")
            current_epoch = current_epoch or "empty-" + hashlib.sha256(self.key_prefix.encode()).hexdigest()[:24]
            previews = await self.read_stream_previews(cursor.run_id,
                after_preview_sequence=preview_sequence if epoch == current_epoch else 0)
            if previews:
                current_epoch = previews[0].preview_epoch
            if epoch != current_epoch:
                if epoch is not None and preview_sequence and not previews:
                    yield await self._preview_gap(cursor.run_id, current_epoch, preview_sequence, "preview_epoch_changed", sequence)
                epoch, preview_sequence = current_epoch, 0
            if previews and preview_sequence and (previews[0].preview_sequence or 0) > preview_sequence + 1:
                yield await self._preview_gap(cursor.run_id, current_epoch, preview_sequence, "preview_buffer_overflow", sequence)
            for event in previews:
                if event.run_sequence <= sequence and (event.preview_sequence or 0) > preview_sequence:
                    preview_sequence = event.preview_sequence or 0
                    yield event
            await asyncio.sleep(self.event_poll_seconds)

    async def close(self):
        if self._closed:
            return
        if self._worker is not None:
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
        if self._redis_ready:
            try:
                await asyncio.wait_for(self.archive_pending(), timeout=5)
            except Exception:
                pass
        if self._redis is not None:
            await self._redis.aclose()
        await self._archive.close()
        self._closed = True


class DistributedRedisMysqlSessionStore:
    plugin_id = "sage.session.redis-mysql-distributed"
    name = "Distributed Redis + MySQL SessionStore"
    description = "Multi-instance Session state, subscriptions and MySQL archival."

    def __init__(self, *args, **kwargs):
        object.__setattr__(self, "_coordinator", _DistributedRedisMysqlState(*args, **kwargs))

    async def start(self, context, dependencies):
        await self._coordinator._ensure_ready()
        await self._coordinator.list_dispatchable_runs()
        return {"session.store": self}

    def __getattr__(self, name):
        return getattr(self._coordinator, name)

    def __setattr__(self, name, value):
        setattr(self._coordinator, name, value)

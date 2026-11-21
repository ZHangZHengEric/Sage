"""SQL-independent multi-instance coordination for Redis Session stores."""

from __future__ import annotations

import asyncio
from bisect import bisect_left
from contextlib import AsyncExitStack, asynccontextmanager
from contextvars import ContextVar
from copy import deepcopy
import hashlib
import json
import time
import uuid
from operator import attrgetter

from sagents.v2.contracts.common import new_id
from sagents.v2.contracts.events import (
    EventDurability,
    EventSource,
    EventSourceType,
    ProtocolEventData,
    RuntimeEvent,
)
from sagents.v2.contracts.errors import ErrorCategory, SageV2Error
from sagents.v2.runtime.distributed.redis_coordination import (
    RedisGuard,
    active_worker_fence,
    coordination_error,
)
from sagents.v2.runtime.observability.logs import get_logger

from sagents.v2.contracts.run_state import TERMINAL_RUN_STATES

from .aggregate import _json
from .cache import cached_session_operation
from .loading import DurableSessionLoading


_PREVIEW_HEADER = ("epoch", "sequence", "indexed_sequence")
_COMPLETION_TYPES = {"message.completed", "reasoning.completed", "item.completed"}
_RUN_SEQUENCE = attrgetter("run_sequence")


class RedisSessionCoordination:
    def __init__(
        self,
        *args,
        coordination_ttl_seconds=30,
        coordination_wait_seconds=10,
        event_poll_seconds=0.1,
        max_preview_events=2048,
        preview_retention_seconds=300,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        if (
            min(coordination_ttl_seconds, coordination_wait_seconds, event_poll_seconds)
            <= 0
        ):
            raise ValueError(
                "Distributed coordination and event intervals must be positive"
            )
        self.coordination_ttl_seconds = coordination_ttl_seconds
        self.coordination_wait_seconds = coordination_wait_seconds
        self._durable_polls = {}
        self._edge_watch = None
        self._edge_lock = asyncio.Lock()
        self.event_poll_seconds = event_poll_seconds
        if min(max_preview_events, preview_retention_seconds) < 1:
            raise ValueError("Preview bounds must be positive")
        self.max_preview_events, self.preview_retention_seconds = (
            max_preview_events,
            preview_retention_seconds,
        )
        self._guards: ContextVar[tuple[RedisGuard, ...]] = ContextVar(
            "distributed_session_guards", default=()
        )
        self._publication_epoch: ContextVar[str | None] = ContextVar(
            "distributed_preview_epoch", default=None
        )
        self._backup_restores = ContextVar(
            "redis_explicit_backup_restores", default=frozenset()
        )

    @property
    def capabilities(self):
        return {
            **super().capabilities,
            "multi_process_writes": True,
            "cross_process_subscribe": True,
            "atomic_worker_fence": True,
        }

    async def _ensure_ready(self):
        if self._closed:
            raise self._storage_error("Redis SessionStore is closed")
        if self._redis_ready:
            return
        async with self._redis_init_lock:
            if self._redis_ready:
                return
            if self._redis is None:
                from redis.asyncio import Redis

                self._redis = Redis.from_url(
                    self.redis_url,
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=5,
                )
            await self._redis.ping()
            memory = await self._redis.info("memory")
            persistence = await self._redis.info("persistence")
            if memory.get("maxmemory_policy") != "noeviction" or not persistence.get(
                "aof_enabled"
            ):
                raise self._storage_error(
                    "Redis execution state requires noeviction and AOF persistence"
                )
            self._redis_ready = True
            self._worker = asyncio.create_task(self._archive_loop())

    @asynccontextmanager
    async def _guard(self, identity):
        await self._ensure_ready()
        key = self._key("guard:" + identity)
        if any(guard.key == key for guard in self._guards.get()):
            yield
            return
        async with RedisGuard(
            self._redis,
            key,
            ttl_seconds=self.coordination_ttl_seconds,
            wait_seconds=self.coordination_wait_seconds,
        ) as guard:
            token = self._guards.set((*self._guards.get(), guard))
            try:
                yield
            finally:
                self._guards.reset(token)

    async def _owned(self, pipe, *write_keys):
        fences = self._guards.get()
        worker = active_worker_fence.get()
        if worker is not None:
            if worker.redis_url != self.redis_url:
                raise coordination_error(
                    "Scheduler and SessionStore must share the same Redis URL"
                )
            fences = (*fences, worker)
        keys = tuple(fence.key for fence in fences)
        if keys or write_keys:
            await pipe.watch(*keys, *write_keys)
        if keys and await pipe.mget(keys) != [fence.token for fence in fences]:
            raise coordination_error("Distributed mutation ownership expired or was replaced")

    @asynccontextmanager
    async def _session_operation(self, *session_ids):
        async with AsyncExitStack() as stack:
            for sid in sorted(set(session_ids)):
                await stack.enter_async_context(self._guard("session:" + sid))
            async with super()._session_operation(*session_ids):
                yield

    async def _prepare_session_access(self, session_id):
        await self._ensure_ready()
        revision, deleted = await self._redis.hmget(
            self._session_key(session_id), "revision", "deleted"
        )
        local = self._persisted_session_revisions.get(session_id)
        if (
            session_id in self._recovery_required
            or deleted == "1"
            or revision != (str(local) if local is not None else None)
        ):
            await self._reload_session_from_storage_locked(session_id)
            self._recovery_required.discard(session_id)
        if deleted == "1" and session_id not in self._backup_restores.get():
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
        scope = (
            context.actor.tenant_id,
            context.actor.principal_type,
            context.actor.principal_id,
            command.idempotency_key,
        )
        identity = hashlib.sha256(_json(scope).encode()).hexdigest()
        async with AsyncExitStack() as stack:
            if (
                command.parent_run_id
                or command.session_concurrency_mode.value == "fork"
            ):
                await stack.enter_async_context(self._guard("topology"))
            await stack.enter_async_context(self._guard("start:" + identity))
            # Admission's key is global to the actor, including requests which
            # have not chosen a Session yet. Session revision CAS alone cannot
            # deduplicate two independently generated Session identities.
            lookup = await self._read_start_lookup(command, context)
            previous = self._start_idempotency.get(scope)
            cached = self._runs.get(previous) if previous is not None else None
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

    async def authorize_session_actor(self, session_id, context):
        from sagents.v2.contracts.principals import ActorRef

        await self._ensure_ready()
        revision, indexed, owner, deleted, commit, activity = await self._redis.hmget(
            self._session_key(session_id), ("revision", "run_metadata_revision", "run_metadata_owner", "deleted", "commit_id", "activity_commit"))
        if deleted == "1":
            raise self._not_found("session.not_found", session_id)
        if revision and indexed == revision and commit and commit == activity and owner is not None:
            self._authorize_session_owner(None if owner == "null" else ActorRef.model_validate_json(owner), context)
            return
        if revision is None and callable(getattr(self._archive, "archived_cleanup_head", None)):
            async with self._guard("session:" + session_id):
                if not await self._redis.exists(self._session_key(session_id)) and not await self._redis.sismember(self._key("resident"), session_id):
                    async with self._archive.session_guard(session_id):
                        head = await self._archive.archived_cleanup_head(session_id)
                    if head is not None and head[0] is not None:
                        self._authorize_session_owner(ActorRef.model_validate(head[0]), context)
                        return
        await super().authorize_session_actor(session_id, context)

    async def delete_session(self, session_id):
        async with self._guard("topology"):
            ids = sorted(await self._collect_session_tree((session_id,)))
            if await self._delete_indexed_tree(session_id, ids):
                return
            return await super().delete_session(session_id)

    async def _delete_indexed_tree(self, root, ids):
        from .redis_metadata import _read_redis_fields_batched

        # Use the same Redis-then-local lock order as a Run commit. A
        # restore or admission cannot invalidate these reads before the
        # tombstone transaction. Legacy and externally hosted data continue
        # through the coordinator's full cleanup protocol.
        async with AsyncExitStack() as stack:
            for sid in ids:
                await stack.enter_async_context(self._guard("session:" + sid))
            fields = ("revision", "cleanup_revision", "cleanup_lookups", "deleted", "commit_id", "activity_commit")
            headers = await _read_redis_fields_batched(
                self, [("hmget", self._session_key(sid), fields) for sid in ids])
            lookups = {}
            for sid, (revision, indexed, keys, deleted, commit, activity) in zip(ids, headers, strict=True):
                if deleted == "1" and sid != root:
                    continue
                if revision is None and deleted is None and callable(getattr(self._archive, "archived_cleanup_head", None)):
                    if await self._redis.sismember(self._key("resident"), sid):
                        return False
                    async with self._archive.session_guard(sid):
                        if await self._archive.has_nonterminal_sessions([sid]):
                            return False
                        head = await self._archive.archived_cleanup_head(sid)
                        if head is None or not head[1]:
                            return False
                        lookups[sid] = await self._archive.archived_cleanup_lookups(sid)
                    continue
                if not revision or deleted == "1" or revision != indexed or not keys or not commit or commit != activity:
                    return False
                lookups[sid] = json.loads(keys)
            async with self._lock:
                locks = [self._session_locks.setdefault(sid, asyncio.Lock()) for sid in ids]
            for lock in locks:
                await stack.enter_async_context(lock)
            # Keep both fences until an ambiguous commit and cache invalidation
            # have settled, even if the requesting HTTP connection goes away.
            async def commit():
                await self._delete_storage_locked(root, frozenset(lookups), lookups=lookups)
                async with self._lock:
                    for sid in lookups:
                        if sid in self._sessions:
                            for rid in self._session_run_ids_locked(sid):
                                self._subscribers.pop(rid, None)
                            self._evict_session_locked(sid)
                        self._session_cache.evicted_suspended.discard(sid)
                    self._topology_revision += 1

            task = asyncio.create_task(commit())
            cancelled = False
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    cancelled = True
            task.result()
        async with self._lock:
            for sid, lock in zip(ids, locks, strict=True):
                if self._session_locks.get(sid) is lock and not lock.locked() and not getattr(lock, "_waiters", None) and not self._session_cache.users.get(sid):
                    self._session_locks.pop(sid, None)
        if cancelled:
            raise asyncio.CancelledError
        return True

    async def restore_session_backup(self, backup, *, context):
        # Restoration is an explicit owner-authorized operation. Ordinary stale
        # mutations must continue to reject a permanent deletion tombstone.
        saved = deepcopy(backup)
        entries = [
            self._validate_backup_entry(entry, context)
            for entry in (saved, *saved.get("descendants", ()))
        ]
        from types import SimpleNamespace
        from sagents.v2.contracts.principals import ActorRef, RequestContext

        ids = sorted({entry[0] for entry in entries})
        starts = {}
        for sid, _, probe, _ in entries:
            for scope in probe._start_idempotency:
                identity = hashlib.sha256(_json(scope).encode()).hexdigest()
                starts[identity] = (sid, scope)
        async with self._guard("topology"), AsyncExitStack() as stack:
            # Admission acquires start guards before Session guards. Restoration
            # follows the same order and cannot overwrite a concurrently reused
            # global start key from an otherwise unrelated Session.
            for identity in sorted(starts):
                await stack.enter_async_context(self._guard("start:" + identity))
            for sid in ids:
                await stack.enter_async_context(self._guard("session:" + sid))
            for sid, scope in starts.values():
                tenant_id, principal_type, principal_id, key = scope
                actor = ActorRef(
                    principal_id=principal_id,
                    principal_type=principal_type,
                    tenant_id=tenant_id,
                )
                existing = await self._read_start_lookup(
                    SimpleNamespace(idempotency_key=key), RequestContext(actor=actor)
                )
                if existing is not None and existing != sid:
                    raise self._attachment_error(
                        "session.backup_conflict",
                        "Backup start identities conflict with destination state.",
                    )
            deleted = set()
            for sid in ids:
                if await self._redis.hget(self._session_key(sid), "deleted") == "1":
                    # Retire the old SQL generation while its session lock is
                    # held. This also fences a delayed archive from before delete.
                    async with self._archive.session_guard(sid):
                        await self._archive.delete_archived_sessions((sid,))
                    deleted.add(sid)
            token = self._backup_restores.set(frozenset(deleted))
            try:
                return await super().restore_session_backup(saved, context=context)
            finally:
                self._backup_restores.reset(token)

    async def _ensure_session_loaded(self, sid, *, missing_ok=False):
        # Refresh only under the local Session lock, never evict a mutation
        # which another task on this instance is still publishing.
        await DurableSessionLoading._ensure_session_loaded(
            self, sid, missing_ok=missing_ok
        )

    async def list_dispatchable_runs(self):
        from redis.exceptions import ResponseError
        from sagents.v2.contracts.principals import RequestContext
        from sagents.v2.contracts.run_state import RunSnapshot
        from sagents.v2.runtime.session.contracts import DispatchableRun
        from .redis_metadata import _read_redis_fields_batched

        await self._ensure_ready()
        candidates = sorted(await self._redis.sunion(
            self._key("resident"), self._key("dispatch_sessions"),
        ))
        heads = await _read_redis_fields_batched(self, [
            ("hmget", self._session_key(sid), ("revision", "dispatch_revision", "dispatch_intents", "deleted"))
            for sid in candidates
        ], raise_on_error=False)
        intents = []
        for sid, fields in zip(candidates, heads, strict=True):
            if isinstance(fields, ResponseError):
                if "WRONGTYPE" not in str(fields):
                    raise fields
                get_logger(__name__).warning("scheduler.recovery.session_unreadable",
                    "Isolated unreadable Session during recovery", session_id=sid)
                continue
            revision, indexed, encoded, deleted = fields
            if deleted == "1":
                continue
            if revision is None:
                # A stale index must never make an older SQL checkpoint executable.
                get_logger(__name__).warning("scheduler.recovery.session_missing",
                    "Recovery intent has no hot Session", session_id=sid)
                continue
            if indexed == revision and encoded is not None:
                try:
                    decoded = json.loads(encoded)
                    if not isinstance(decoded, list):
                        raise ValueError("dispatch index must be a list")
                    indexed_intents = tuple(
                        DispatchableRun(run=RunSnapshot.model_validate(row["run"]),
                                        context=RequestContext.model_validate(row["context"]))
                        for row in decoded
                    )
                    if any(intent.run.session_id != sid for intent in indexed_intents):
                        raise ValueError("dispatch index references another Session")
                except (ValueError, TypeError, KeyError):
                    get_logger(__name__).warning("scheduler.recovery.index_invalid",
                        "Reading authoritative Session after invalid recovery index", session_id=sid)
                else:
                    intents.extend(indexed_intents)
                    continue
            try:
                await self.get_session(sid)
                async with self._session_read(sid):
                    intents.extend(
                        DispatchableRun(run=self._run_snapshot(row), context=row.request_context)
                        for rid in self._session_run_ids_locked(sid)
                        if (row := self._runs[rid]).request_context is not None
                        and self._is_dispatchable_run(row)
                    )
            except SageV2Error as exc:
                if exc.info.code == "session.not_found":
                    continue
                if (exc.info.code != "session.revision_conflict"
                        and exc.info.category not in {ErrorCategory.CORRUPT_STATE, ErrorCategory.UNSUPPORTED_SCHEMA}):
                    raise
                get_logger(__name__).warning("scheduler.recovery.session_unreadable",
                    "Isolated unreadable Session during recovery", session_id=sid, error_code=exc.info.code)
            except (ValueError, TypeError, KeyError):
                get_logger(__name__).warning("scheduler.recovery.session_unreadable",
                    "Isolated unreadable Session during recovery", session_id=sid)
        return tuple(sorted(intents, key=lambda intent: (intent.run.created_at, intent.run.run_id)))

    async def has_nonterminal_runs(self):
        from sagents.v2.contracts.run_state import TERMINAL_RUN_STATES

        await self._ensure_ready()
        resident, suspended = await asyncio.gather(
            self._redis.smembers(self._key("resident")),
            self._redis.smembers(self._key("suspended")),
        )
        rows, _ = await self._run_metadata_batch(tuple(set(resident) | set(suspended)))
        return any(row.state not in TERMINAL_RUN_STATES for row in rows)

    async def _ensure_resource_loaded(self, collection, identity_key, identity):
        try:
            await super()._ensure_resource_loaded(collection, identity_key, identity)
        except SageV2Error as exc:
            if exc.info.code == "session.not_found":
                kind = {
                    "runs": "run",
                    "checkpoints": "checkpoint",
                    "suspensions": "suspension",
                    "interactions": "interaction",
                    "session_commit_proposals": "session.commit_proposal",
                }[collection]
                raise self._not_found(kind + ".not_found", identity) from exc
            raise

    async def get_derived_state(self, sid, namespace, key):
        await self._ensure_ready()
        # Check the head and read its derived value in the same Redis snapshot.
        # Only cold Sessions require the normal archive lookup and restoration.
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.hmget(self._session_key(sid), ("revision", "deleted"))
            pipe.hget(self._key(f"derived:{sid}"), self._lookup_key((namespace, key)))
            (revision, deleted), encoded = await pipe.execute()
        if deleted == "1":
            raise self._not_found("session.not_found", sid)
        if revision is not None:
            return json.loads(encoded) if encoded is not None else None
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
                        pipe.hdel(
                            self._key(f"derived:{sid}"),
                            self._lookup_key((namespace, key)),
                        )
                    else:
                        pipe.hset(
                            self._key(f"derived:{sid}"),
                            self._lookup_key((namespace, key)),
                            _json(value),
                        )
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

    async def _archive_session(self, sid):
        started = time.monotonic()
        # Claim SQL serialization under the mutation guard, preserving the lock
        # order used by restoration. Only capture the immutable Redis snapshot
        # under that guard: SQL I/O must not block live Run commits.
        async with AsyncExitStack() as archive_stack:
            async with self._guard("session:" + sid):
                if not await self._redis.sismember(self._key("pending"), sid):
                    return
                await archive_stack.enter_async_context(self._archive.session_guard(sid))
                fields = await self._read_hot(self._session_key(sid))
                if not fields:
                    raise self._storage_error(f"Pending Redis Session data is missing: {sid}")
            get_logger(__name__).info(
                "session.archive.snapshot_captured", "会话归档快照已获取，释放创作状态锁后写入 SQL",
                session_id=sid, revision=fields.get("revision"),
            )
            await self._write_archive_snapshot(sid, fields)
        # Release SQL before taking Redis again, so a concurrent restore which
        # owns Redis and waits for SQL cannot deadlock with acknowledgement.
        async with self._guard("session:" + sid):
            await self._ack_archive_snapshot(sid, fields)
            if await self._redis.hget(self._session_key(sid), "deleted") == "1":
                await self._redis.persist(self._session_key(sid))
        if (fields.get("deleted") != "1" and
            sum(name.startswith("d:") for name in fields) >= self.snapshot_interval):
            # Decode and stage outside the mutation guard. Publication checks the
            # base generation and retains deltas committed after this snapshot.
            await self._compact_hot(sid, fields)
        get_logger(__name__).info(
            "session.archive.finished", "会话后台归档完成", session_id=sid,
            revision=fields.get("revision"),
            duration_ms=round((time.monotonic() - started) * 1000, 3),
        )

    def _preview_epoch_for_run(self, run_id):
        return self._publication_epoch.get() or self._preview_epoch

    @cached_session_operation
    async def publish_stream_preview(self, *, run_id, **options):
        # Only the immutable Session identity is needed to take the guard.
        # The publication below reloads and authorizes the Run under that guard.
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        session_id = self._runs[run_id].session_id
        async with self._guard("session:" + session_id):
            key = self._key("previews:" + run_id)
            index = self._key("preview-events:" + run_id)
            epoch, stored, indexed = await self._redis.hmget(key, _PREVIEW_HEADER)
            rebuild = not epoch or stored != indexed
            migrated = {}
            if rebuild and epoch:
                legacy = await self._redis.hget(key, "events")
                migrated = {
                    _json(row): row["preview_sequence"]
                    for row in json.loads(legacy or "[]")
                    if row.get("preview_epoch") == epoch
                }
            epoch = epoch or uuid.uuid4().hex
            self._preview_sequences[run_id] = int(stored or 0)
            self._stream_previews[run_id] = []
            token = self._publication_epoch.set(epoch)
            try:
                result = await super().publish_stream_preview(run_id=run_id, **options)
            finally:
                self._publication_epoch.reset(token)
            events = self._stream_previews.pop(run_id, ())
            if not events:
                return result
            sequence = events[-1].preview_sequence
            rows = {
                **migrated,
                **{event.model_dump_json(): event.preview_sequence for event in events[-self.max_preview_events:]},
            }

            async def write():
                async with self._redis.pipeline() as pipe:
                    await self._owned(pipe)
                    pipe.multi()
                    if rebuild:
                        pipe.delete(index)
                    pipe.zadd(index, rows)
                    pipe.zremrangebyrank(index, 0, -self.max_preview_events - 1)
                    pipe.hset(key, mapping={"epoch": epoch, "sequence": sequence, "indexed_sequence": sequence})
                    pipe.hdel(key, "events")
                    pipe.expire(index, self.preview_retention_seconds)
                    pipe.expire(key, self.preview_retention_seconds)
                    await pipe.execute()

            await self._retry_transaction(write)
            return result

    async def _read_preview_page(self, run_id, after, *, epoch=None, follow_epoch=False):
        key = self._key("previews:" + run_id)
        index = self._key("preview-events:" + run_id)
        for _ in range(4):
            head = await self._redis.hmget(key, _PREVIEW_HEADER)
            current, sequence, indexed = head
            lower = 0 if follow_epoch and current != epoch else after
            if not current or int(sequence or 0) <= lower:
                return current, ()
            use_index = sequence == indexed
            # Fetch the range and its generation atomically. A concurrent
            # writer can advance the tail, but can't mix epochs with this page.
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.hmget(key, _PREVIEW_HEADER)
                if use_index:
                    pipe.zrangebyscore(index, f"({lower}", "+inf")
                else:
                    pipe.hget(key, "events")  # compatibility with pre-index producers
                verified, rows = await pipe.execute()
            actual_epoch, actual_sequence, actual_index = verified
            if actual_epoch != current or (actual_sequence == actual_index) != use_index:
                continue
            if use_index:
                events = tuple(RuntimeEvent.model_validate_json(row) for row in rows)
            else:
                events = tuple(
                    RuntimeEvent.model_validate(row) for row in json.loads(rows or "[]")
                    if row.get("preview_epoch") == current and (row.get("preview_sequence") or 0) > lower
                )
            return current, events
        # Next poll can retry after concurrent epoch changes settle. Preserve
        # the caller's watermark rather than announcing an unverified gap.
        return epoch, ()

    async def _completed_preview_items(self, run_id, events):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        async with self._run_session_read(run_id):
            if self._runs[run_id].state in TERMINAL_RUN_STATES:
                return None
            # An emitted preview is anchored at the current durable sequence.
            # Only completions at or after the oldest such anchor supersede it.
            history = self._run_events[run_id]
            start = bisect_left(history, min(event.run_sequence for event in events), key=_RUN_SEQUENCE)
            candidates = {event.item_id for event in events}
            return {
                event.item_id for event in history[start:]
                if event.type in _COMPLETION_TYPES and event.item_id in candidates
            }

    async def read_stream_previews(self, run_id, *, after_preview_sequence=0):
        await self._ensure_ready()
        epoch, previews = await self._read_preview_page(run_id, after_preview_sequence)
        if epoch is None:
            await self.get_run(run_id)  # Preserve the missing-Run error without hydrating caught-up readers.
        if not previews:
            return ()
        completed = await self._completed_preview_items(run_id, previews)
        return () if completed is None else tuple(event for event in previews if event.item_id not in completed)

    async def _preview_gap(self, run_id, epoch, previous_sequence, state, run_sequence):
        run = await self.get_run(run_id)
        context = await self.get_run_context(run_id)
        return RuntimeEvent(
            event_id=new_id("event"),
            type="stream.gap",
            occurred_at=self._clock(),
            durability=EventDurability.REPLAY_BUFFERED,
            session_id=run.session_id,
            run_id=run_id,
            run_sequence=run_sequence,
            preview_sequence=max(previous_sequence, 1),
            preview_epoch=epoch,
            actor=context.actor,
            source=EventSource(source_type=EventSourceType.PROTOCOL),
            data=ProtocolEventData(
                state=state,
                from_sequence=previous_sequence,
                to_sequence=previous_sequence,
                partial_items={},
            ),
        )

    async def read_indexed_run_events(self, run_id, session_id, *, after_sequence=0, limit=None):
        """Read the recent committed range; the ledger is the fallback for any gap."""
        from redis.exceptions import ResponseError
        from .redis_persistence import _EVENT_TAIL_ROWS

        if after_sequence < 0 or (limit is not None and limit < 1):
            raise ValueError("invalid event page")
        await self._ensure_ready()
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.hmget(self._session_key(session_id), ("revision", "event_index_revision",
                    "event_index_epoch", "deleted", self._event_head_field(run_id)))
                pipe.zrangebyscore(self._durable_event_tail(run_id), f"({after_sequence}", "+inf",
                                  start=0, num=min(limit or _EVENT_TAIL_ROWS, _EVENT_TAIL_ROWS))
                header, rows = await pipe.execute()
        except ResponseError as exc:
            if "WRONGTYPE" not in str(exc):
                raise
        else:
            revision, indexed, epoch, deleted, head = header
            if deleted == "1":
                raise self._not_found("run.not_found", run_id)
            if revision is not None and indexed == revision and epoch and head:
                stored_epoch, _, offset = head.partition(":")
                if stored_epoch == epoch and offset.isdecimal():
                    remaining = max(0, int(offset) - after_sequence)
                    count = min(remaining, limit) if limit is not None else remaining
                    if count == 0:
                        return ()
                    if count == len(rows):
                        try:
                            events = tuple(RuntimeEvent.model_validate_json(row) for row in rows)
                        except ValueError:
                            pass
                        else:
                            if all(event.run_id == run_id and event.session_id == session_id
                                   and event.run_sequence == sequence and event.preview_sequence is None
                                   for sequence, event in enumerate(events, after_sequence + 1)):
                                return events
        return await self.read_events(run_id, after_sequence=after_sequence, limit=limit)

    async def subscribe_durable_events(self, cursor, session_id):
        sequence = cursor.run_sequence
        key = (session_id, cursor.run_id)
        group = self._durable_polls.setdefault(key, {"users": 0, "reads": {}})
        group["users"] += 1
        reads = group["reads"]
        try:
            while not self._closed:
                task = reads.get(sequence)
                if task is None:
                    task = asyncio.create_task(self.read_indexed_run_events(
                        cursor.run_id, session_id, after_sequence=sequence, limit=self._subscriber_queue_size))
                    reads[sequence] = task
                    # Concurrent readers join the same page. Retain it for one
                    # polling interval so staggered clients share idle reads.
                    def expire(done, offset=sequence):
                        def discard():
                            if reads.get(offset) is done:
                                reads.pop(offset)
                        if done.cancelled() or done.exception() is not None or done.result():
                            discard()
                        else:
                            asyncio.get_running_loop().call_later(self.event_poll_seconds, discard)
                    task.add_done_callback(expire)
                events = await asyncio.shield(task)
                for event in events:
                    sequence = event.run_sequence
                    yield event
                if len(events) < self._subscriber_queue_size:
                    await asyncio.sleep(self.event_poll_seconds)
        finally:
            group["users"] -= 1
            if not group["users"]:
                self._durable_polls.pop(key, None)
                for task in reads.values():
                    if not task.done():
                        task.cancel()
                reads.clear()

    async def subscribe_events(self, cursor):
        # Canonical events are the replay authority. Polling is deliberately
        # independent of Pub/Sub delivery, reconnects and process-local queues.
        sequence = cursor.run_sequence
        preview_sequence, epoch = cursor.preview_sequence, cursor.preview_epoch
        while not self._closed:
            events = await self.read_events(
                cursor.run_id,
                after_sequence=sequence,
                limit=self._subscriber_queue_size,
            )
            for event in events:
                if event.run_sequence > sequence:
                    sequence = event.run_sequence
                    yield event
            if len(events) >= self._subscriber_queue_size:
                continue  # Drain the durable backlog before live previews.
            current_epoch, previews = await self._read_preview_page(
                cursor.run_id, preview_sequence, epoch=epoch, follow_epoch=True,
            )
            current_epoch = (
                current_epoch
                or "empty-" + hashlib.sha256(self.key_prefix.encode()).hexdigest()[:24]
            )
            completed = await self._completed_preview_items(cursor.run_id, previews) if previews else ()
            if epoch != current_epoch:
                if epoch is not None and preview_sequence and not previews:
                    yield await self._preview_gap(
                        cursor.run_id,
                        current_epoch,
                        preview_sequence,
                        "preview_epoch_changed",
                        sequence,
                    )
                epoch, preview_sequence = current_epoch, 0
            if (
                previews
                and preview_sequence
                and (previews[0].preview_sequence or 0) > preview_sequence + 1
            ):
                yield await self._preview_gap(
                    cursor.run_id,
                    current_epoch,
                    preview_sequence,
                    "preview_buffer_overflow",
                    sequence,
                )
            for event in previews:
                if (
                    event.run_sequence <= sequence
                    and (event.preview_sequence or 0) > preview_sequence
                ):
                    preview_sequence = event.preview_sequence or 0
                    if completed is not None and event.item_id not in completed:
                        yield event
            await asyncio.sleep(self.event_poll_seconds)

    async def close(self):
        if self._closed:
            return
        async with self._edge_lock:
            if self._edge_watch is not None:
                await self._edge_watch.reset()
                self._edge_watch = None
        await self._session_cache.close()
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

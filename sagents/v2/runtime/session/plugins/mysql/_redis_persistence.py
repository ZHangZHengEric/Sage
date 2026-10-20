"""Private Redis persistence and MySQL archival for the unified SessionStore.

Redis requires AOF persistence and noeviction. Active, unarchived state has no TTL.
Coordination and subscriptions are provided by the public Redis/MySQL plugin.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import time
import uuid
from typing import Any

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.run_state import RunState, TERMINAL_RUN_STATES
from sagents.v2.runtime.observability.logs import get_logger
from .state import _MysqlSessionState, _json, parse_mysql_dsn
from .distributed_archive import DistributedMysqlSessionArchive
from .child_heads import RedisManagedSessionHeads


LOGGER = get_logger(__name__)
_STOPPED = TERMINAL_RUN_STATES | {RunState.SUSPENDED}


class _RedisMysqlPersistence(RedisManagedSessionHeads, _MysqlSessionState):
    format_version = "sage.session.redis-mysql/v2"
    durable_history_pages = False
    archive_batch_rows = 32
    archive_batch_bytes = 256 * 1024
    snapshot_chunk_chars = 16 * 1024

    def __init__(self, dsn, *, redis_url, table_prefix=None, key_prefix=None,
                 archive_interval_seconds=1.0, retention_seconds=3600, **kwargs):
        if not redis_url or archive_interval_seconds <= 0 or retention_seconds < 1:
            raise ValueError("Redis URL, positive archive interval and retention are required")
        super().__init__(dsn, table_prefix=table_prefix, **kwargs)
        identity = parse_mysql_dsn(dsn)
        identity.pop("password")
        identity["table_prefix"] = self.table_prefix
        digest = hashlib.sha256(_json(identity).encode()).hexdigest()[:24]
        self.key_prefix = key_prefix or f"sage:session:{{{digest}}}:distributed"
        self.redis_url = redis_url
        self.archive_interval_seconds = float(archive_interval_seconds)
        self.retention_seconds = int(retention_seconds)
        # redis-py does not narrow its bytes/str return types for decode_responses;
        # keep the optional transport boundary dynamic, including injected clients.
        self._redis: Any = None
        self._archive = DistributedMysqlSessionArchive(
            dsn, table_prefix=table_prefix,
            max_connections=self._connection_budget.max_connections,
            max_pending_connections=self._connection_budget.max_pending_connections,
            connection_acquire_timeout_seconds=self._connection_budget.connection_acquire_timeout_seconds,
        )
        self._redis_ready = False
        self._redis_init_lock = asyncio.Lock()
        self._archive_lock = asyncio.Lock()
        self._worker = None
        self._wake = asyncio.Event()
        self._recovery_required = set()

    def _key(self, name):
        return f"{self.key_prefix}:{name}"

    def _session_key(self, sid):
        return self._key(f"session:{sid}")

    def composition_identity(self):
        return {"plugin": "sage.session.redis-mysql", "table_prefix": self.table_prefix,
                "key_prefix": self.key_prefix, "format": self.format_version}

    def _storage_error(self, message):
        return SageV2Error(RuntimeErrorInfo(code="session_store.redis_unavailable",
            category=ErrorCategory.RESOURCE_LOST, message=message, safe_to_resume=True))

    @staticmethod
    async def _retry_transaction(operation):
        from redis.exceptions import WatchError
        for attempt in range(5):
            try:
                return await operation()
            except WatchError:
                if attempt == 4:
                    raise

    async def _archive_loop(self):
        while True:
            try:
                await self.archive_pending()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                LOGGER.warning("session.redis.worker_failed", "Session archive worker will retry",
                               attributes=self._failure_attributes(exc))
            try:
                await asyncio.wait_for(self._wake.wait(), self.archive_interval_seconds)
            except TimeoutError:
                pass
            self._wake.clear()

    @staticmethod
    def _failure_attributes(exc):
        info = getattr(exc, "info", None)
        return {"error_type": type(exc).__name__,
                "error_code": getattr(info, "code", None),
                "error_message": getattr(info, "message", str(exc))}

    @staticmethod
    def _lookup_key(values):
        return _json(list(values))

    async def _commit_storage_locked(self, sid):
        await self._ensure_ready()
        started = time.perf_counter()
        mutation = self._session_mutation_locked(sid).model_dump(mode="json", exclude={"kind"})
        head = mutation["upserts"]["sessions"][0]
        revision = int(head["revision"])
        expected = self._persisted_session_revisions.get(sid)
        # A run body can be read from memory after its archived Redis cache expires.
        # Reload the archived base before appending the next delta in that case.
        if expected is not None and not await self._redis.exists(self._session_key(sid)):
            await self._fetch_session(sid)
        # Full snapshots are compacted by the archive worker, never by a Run commit.
        compact = expected is None
        if compact:
            encoded = _json(self._dump_session_state_locked(sid))
        else:
            head["revision_sequences"] = {str(revision): head["last_sequence"]}
            encoded = _json(mutation)
        staged_base = None
        if compact and len(encoded.encode("utf-8")) > self.archive_batch_bytes:
            staged_base = await self._stage_snapshot(encoded)
        rows = self._location_rows_after_mutation(sid, mutation)
        starts = self._start_rows_after_mutation(sid, mutation)
        stopped = any(row["state"] in _STOPPED for row in
                      [*mutation["upserts"].get("runs", ()), *mutation["patches"].get("runs", ())])
        quiescent = all(self._runs[rid].state in _STOPPED for rid in self._session_run_ids_locked(sid))
        suspended = any(self._runs[rid].state == RunState.SUSPENDED for rid in self._session_run_ids_locked(sid))
        attachments = {identity: base64.b64encode(content).decode("ascii")
                       for identity, content in self._pending_attachments(sid)}
        commit_id = uuid.uuid4().hex
        key = self._session_key(sid)
        async def write():
            async with self._redis.pipeline() as pipe:
                await self._owned(pipe)
                await pipe.watch(key)
                previous = await pipe.hget(key, "revision")
                if previous != (str(expected) if expected is not None else None):
                    raise self._conflict("session.revision_conflict", f"Redis Session revision changed for {sid}")
                old_fields = await pipe.hkeys(key) if compact else ()
                snapshot_token = await pipe.hget(key, "base_snapshot")
                if staged_base:
                    token, parts = staged_base
                    staged_key = self._key(f"snapshot:{token}")
                    await pipe.watch(staged_key)
                    if await pipe.hlen(staged_key) != parts:
                        raise self._storage_error("Redis snapshot staging expired before publication")
                pipe.multi()
                if compact:
                    stale = [field for field in old_fields if field.startswith("d:")]
                    if stale:
                        pipe.hdel(key, *stale)
                values = {"revision": revision, "last_sequence": head["last_sequence"],
                          "commit_id": commit_id, "quiescent": "1" if quiescent else "0"}
                if staged_base:
                    token, parts = staged_base
                    values.update(base_snapshot=token, base_parts=parts, base_revision=revision)
                    pipe.persist(self._key(f"snapshot:{token}"))
                else:
                    values["base" if compact else f"d:{revision}"] = encoded
                pipe.hset(key, mapping=values)
                pipe.persist(key)
                if snapshot_token:
                    pipe.persist(self._key(f"snapshot:{snapshot_token}"))
                pipe.sadd(self._key("resident"), sid)
                if suspended:
                    pipe.sadd(self._key("suspended"), sid)
                else:
                    pipe.srem(self._key("suspended"), sid)
                if stopped or quiescent or revision % self.archive_batch_rows == 0:
                    pipe.sadd(self._key("pending"), sid)
                for kind, identity, _ in rows - self._persisted_locations.get(sid, set()):
                    pipe.hset(self._key("locations"), self._lookup_key((kind, identity)), sid)
                for kind, identity, _ in self._persisted_locations.get(sid, set()) - rows:
                    pipe.hdel(self._key("locations"), self._lookup_key((kind, identity)))
                for row in starts - self._persisted_start_keys.get(sid, set()):
                    pipe.hset(self._key("starts"), self._lookup_key(row[:3]), sid)
                for row in self._persisted_start_keys.get(sid, set()) - starts:
                    pipe.hdel(self._key("starts"), self._lookup_key(row[:3]))
                if head.get("parent_session_id"):
                    pipe.hset(self._key("parents"), sid, head["parent_session_id"])
                if attachments:
                    pipe.hset(self._key(f"attachments:{sid}"), mapping=attachments)
                pipe.persist(self._key(f"attachments:{sid}"))
                pipe.persist(self._key(f"derived:{sid}"))
                await pipe.execute()
        try:
            await self._retry_transaction(write)
        except Exception:
            # A lost response may follow a successful EXEC. Resolve the unique
            # commit token before allowing the coordinator to roll back memory.
            self._recovery_required.add(sid)
            if await self._redis.hget(key, "commit_id") != commit_id:
                raise
        self._recovery_required.discard(sid)
        self._remember_persisted_session(sid, revision,
            {rid: len(self._run_events[rid]) for rid in self._session_run_ids_locked(sid)},
            rows, starts, 0 if compact else self._persisted_mutation_counts.get(sid, 0) + 1)
        self._session_cache.touch(sid, charge=4 * len(encoded.encode()))
        self._forget_attachment_bytes(sid)
        if stopped or quiescent or revision % self.archive_batch_rows == 0:
            self._wake.set()
        LOGGER.debug("session.redis.commit", "Redis Session commit completed", session_id=sid,
            revision=revision, payload_bytes=len(encoded.encode()), snapshot=compact,
            duration_ms=round((time.perf_counter() - started) * 1000, 3))

    def _decode_hot(self, fields):
        base = json.loads(fields["base"])
        deltas = sorted((int(field[2:]), value) for field, value in fields.items() if field.startswith("d:"))
        return self._replay_mutations(base, deltas, int(fields["revision"]), int(fields["last_sequence"]))

    async def _read_hash_fields(self, key, names):
        """Pipeline small HMGET commands without accumulating an unbounded reply."""
        values = []
        for batch_start in range(0, len(names), 256):
            async with self._redis.pipeline(transaction=False) as pipe:
                for start in range(batch_start, min(batch_start + 256, len(names)), 8):
                    pipe.hmget(key, names[start:start + 8])
                for rows in await pipe.execute():
                    values.extend(rows)
        return values

    async def _read_hot(self, key):
        """Read an immutable base plus a bounded range of deltas, retrying compaction races."""
        names = ("revision", "last_sequence", "deleted", "base_revision", "base_snapshot", "base_parts")
        for _ in range(5):
            values = await self._redis.hmget(key, names)
            fields = {name: value for name, value in zip(names, values) if value is not None}
            if fields.get("deleted") == "1":
                return fields
            if values[0] is None:
                return {}
            token = fields.get("base_snapshot")
            if token:
                snapshot_key = self._key(f"snapshot:{token}")
                parts = await self._read_hash_fields(snapshot_key,
                    [str(i) for i in range(int(fields["base_parts"]))])
                if any(part is None for part in parts):
                    continue
                fields["base"] = "".join(parts)
            else:
                fields["base"] = await self._redis.hget(key, "base")
                if fields["base"] is None:
                    continue
            if "base_revision" in fields:
                base_revision = int(fields["base_revision"])
            else:
                base_revision = await asyncio.to_thread(lambda: int(json.loads(fields["base"])["sessions"][0]["revision"]))
            keys = [f"d:{i}" for i in range(base_revision + 1, int(fields["revision"]) + 1)]
            rows = await self._read_hash_fields(key, keys)
            missing = any(row is None for row in rows)
            fields.update(zip(keys, rows))
            current = await self._redis.hmget(key, ("base_snapshot", "base_revision", "deleted"))
            if not missing and current == [fields.get("base_snapshot"), fields.get("base_revision"), fields.get("deleted")]:
                return fields
        raise self._conflict("session.revision_conflict", "Redis Session base changed during loading")

    async def _stage_snapshot(self, encoded):
        token = uuid.uuid4().hex
        key = self._key(f"snapshot:{token}")
        count = 0
        batch, size = [], 0

        async def upload():
            async with self._redis.pipeline(transaction=True) as pipe:
                for index, chunk in batch:
                    pipe.hset(key, str(index), chunk)
                pipe.expire(key, max(60, self.retention_seconds))
                await pipe.execute()

        for count, start in enumerate(range(0, len(encoded), self.snapshot_chunk_chars), 1):
            chunk = encoded[start:start + self.snapshot_chunk_chars]
            chunk_size = len(chunk.encode("utf-8"))
            if batch and (len(batch) >= 32 or size + chunk_size > self.archive_batch_bytes):
                await upload()
                batch, size = [], 0
            batch.append((count - 1, chunk))
            size += chunk_size
        if batch:
            await upload()
        return token, count

    async def _fetch_session(self, sid):
        fields = await self._read_hot(self._session_key(sid))
        if fields:
            return None if fields.get("deleted") == "1" else await asyncio.to_thread(self._decode_hot, fields)
        if await self._redis.sismember(self._key("resident"), sid):
            raise self._storage_error(f"Unarchived Redis Session data is missing: {sid}")
        payload = await self._archive._fetch_session(sid)
        if payload is None:
            return None
        return await self._seed_archived_session(sid, payload)

    async def _fetch_sessions(self, session_ids):
        from sagents.v2.runtime.session.plugins.mysql.metadata import read_redis_metadata_batch
        await self._ensure_ready()
        ids = tuple(dict.fromkeys(session_ids))
        result = {}
        for start in range(0, len(ids), 128):
            batch = ids[start:start + 128]
            snapshots = await read_redis_metadata_batch(self, batch)
            absent = [sid for sid, fields in snapshots.items() if not fields]
            if absent:
                resident = await self._redis.smismember(self._key("resident"), absent)
                for sid, hot in zip(absent, resident):
                    if hot:
                        raise self._storage_error(f"Unarchived Redis Session data is missing: {sid}")
            for sid, fields in snapshots.items():
                if fields and fields.get("deleted") != "1":
                    result[sid] = await asyncio.to_thread(self._decode_hot, fields)
            if absent:
                archived = await self._archive._fetch_sessions(absent)
                for sid, payload in archived.items():
                    # A later commit requires a published Redis revision. Reuse
                    # the existing CAS publication, including deletion checks.
                    loaded = await self._seed_archived_session(sid, payload)
                    if loaded is not None:
                        result[sid] = loaded
        return result

    async def _seed_archived_session(self, sid, payload):
        payload.pop("_mutation_count", None)
        key = self._session_key(sid)
        encoded = await asyncio.to_thread(_json, payload)
        token, parts = await self._stage_snapshot(encoded)
        snapshot_key = self._key(f"snapshot:{token}")
        async def seed():
            async with self._redis.pipeline() as pipe:
                await self._owned(pipe)
                await pipe.watch(key)
                await pipe.watch(snapshot_key)
                if await pipe.hlen(snapshot_key) != parts:
                    raise self._storage_error("Redis snapshot staging expired before publication")
                if not await pipe.exists(key):
                    head = payload["sessions"][0]
                    pipe.multi()
                    quiescent = all(row["state"] in _STOPPED for row in payload["runs"])
                    pipe.hset(key, mapping={"base_snapshot": token, "base_parts": parts,
                        "base_revision": head["revision"], "revision": head["revision"],
                        "last_sequence": head["last_sequence"], "archived_revision": head["revision"],
                        "quiescent": "1" if quiescent else "0"})
                    if quiescent:
                        pipe.expire(key, self.retention_seconds)
                        pipe.expire(snapshot_key, self.retention_seconds)
                    else:
                        pipe.sadd(self._key("resident"), sid)
                        pipe.persist(self._key(f"snapshot:{token}"))
                    await pipe.execute()
        await self._retry_transaction(seed)
        fields = await self._read_hot(key)
        return None if not fields or fields.get("deleted") == "1" else await asyncio.to_thread(self._decode_hot, fields)

    async def _ensure_sessions_loaded(self, session_ids):
        await self._ensure_ready()
        ids = tuple(dict.fromkeys(session_ids))
        uncertain = self._recovery_required.intersection(ids)
        if uncertain:
            async with self._lock:
                for sid in uncertain:
                    if sid in self._sessions:
                        self._evict_session_locked(sid)
            self._recovery_required.difference_update(uncertain)
        await super()._ensure_sessions_loaded(ids)

    async def _ensure_resource_loaded(self, collection, identity_key, identity):
        await self._ensure_ready()
        if self._recovery_required and self._resource_is_loaded(collection, identity):
            resource = getattr(self, f"_{collection}")[identity]
            sid = getattr(resource, "session_id", None)
            if sid is None:
                sid = self._runs[resource.run_id].session_id
            if sid in self._recovery_required:
                await self._ensure_session_loaded(sid)
        await super()._ensure_resource_loaded(collection, identity_key, identity)

    async def _locate_session(self, kind, identity):
        await self._ensure_ready()
        sid = await self._redis.hget(self._key("locations"), self._lookup_key((kind, identity)))
        return sid if sid is not None else await self._archive._locate_session(kind, identity)

    async def _read_start_lookup(self, command, context):
        from .state import _principal_lookup_key
        scope = (str(context.actor.tenant_id or ""),
                 _principal_lookup_key(context.actor.principal_type.value, context.actor.principal_id),
                 command.idempotency_key)
        sid = await self._redis.hget(self._key("starts"), self._lookup_key(scope))
        if sid is None:
            sid = await self._archive._read_start_lookup(command, context)
        if sid is not None and await self._redis.hget(self._session_key(sid), "deleted") == "1":
            return None
        return sid

    async def _list_descendant_ids(self, sid):
        parents = await self._redis.hgetall(self._key("parents"))
        found = set(await self._archive._list_descendant_ids(sid))
        frontier = {sid, *found}
        while frontier:
            children = {child for child, parent in parents.items() if parent in frontier and child not in found}
            found.update(children)
            frontier = children
        return sorted(found)

    async def read_session_views(self, session_ids, **options):
        from functools import partial
        from sagents.v2.runtime.session.read_views import (
            validate_view_ids,
            project_view_state,
            apply_view_delta,
            views_from_payload,
        )
        from sagents.v2.runtime.session.plugins.mysql.metadata import (
            read_redis_metadata_batch,
            decode_redis_metadata,
        )
        ids = validate_view_ids(session_ids,options.get('run_ids'))
        await self._ensure_ready()
        result = {}
        missing = ids
        if not missing:
            return result
        fields = await read_redis_metadata_batch(self,missing)
        absent = [sid for sid in missing if not fields.get(sid)]
        if absent:
            resident = await self._redis.smismember(self._key('resident'),absent)
            for sid, hot in zip(absent,resident):
                if hot:
                    raise self._storage_error(f'Unarchived Redis Session data is missing: {sid}')
        replay_options = {key: options[key] for key in ('include_events','run_ids') if key in options}
        for sid, raw in fields.items():
            if not raw or raw.get('deleted') == '1':
                continue
            payload = await asyncio.to_thread(decode_redis_metadata,raw,
                project=partial(project_view_state,**replay_options), apply=partial(apply_view_delta,**replay_options))
            result.update(await asyncio.to_thread(views_from_payload,payload,**options))
        if absent:
            result.update(await self._archive.read_session_views(absent,**options))
        return {sid:result[sid] for sid in ids if sid in result}

    async def _run_metadata_batch(self, session_ids):
        from sagents.v2.runtime.session.run_metadata import metadata_from_payload
        from sagents.v2.runtime.session.plugins.mysql.metadata import (
            decode_redis_metadata,
            read_redis_metadata_batch,
        )
        await self._ensure_ready()
        rows, owners = (), {}
        missing = session_ids
        if not missing:
            return rows, owners
        snapshots = await read_redis_metadata_batch(self, missing)
        absent = [sid for sid, fields in snapshots.items() if not fields]
        if absent:
            resident = await self._redis.smismember(self._key('resident'), absent)
            for sid, hot in zip(absent, resident):
                if hot:
                    raise self._storage_error(f'Unarchived Redis Session data is missing: {sid}')
        cold = []
        result = list(rows)
        for sid, fields in snapshots.items():
            if fields.get('deleted') == '1':
                continue
            if fields:
                payload = await asyncio.to_thread(decode_redis_metadata, fields)
                if payload is not None:
                    current, heads = await asyncio.to_thread(metadata_from_payload, payload)
                    result.extend(current)
                    owners.update(heads)
            else:
                cold.append(sid)
        if cold:
            current, heads = await self._archive._run_metadata_batch(cold)
            result.extend(current)
            owners.update(heads)
        return tuple(result), owners

    async def authorized_run_metadata_page(self, session_ids, context, **options):
        from sagents.v2.runtime.session.run_metadata import RunMetadataQueries
        return await RunMetadataQueries.authorized_run_metadata_page(self, session_ids, context, **options)

    async def has_nonterminal_session_trees(self, session_ids):
        """Redis owns hot state; an asynchronous MySQL archive cannot overrule it."""
        await self._ensure_ready()
        selected = set(session_ids)
        children = {}
        for child, parent in (await self._redis.hgetall(self._key("parents"))).items():
            children.setdefault(parent, []).append(child)
        frontier = set(selected)
        while frontier:
            archived = set(await self._archive.list_workspace_descendant_ids(sorted(frontier)))
            traversal = list(frontier | (archived - selected))
            selected.update(archived)
            frontier = set()
            while traversal:
                for child in children.get(traversal.pop(), ()):
                    if child not in selected:
                        selected.add(child)
                        frontier.add(child)
                        traversal.append(child)
        ids = sorted(selected)
        cold = []
        for offset in range(0, len(ids), 128):
            batch = ids[offset:offset + 128]
            # Acknowledged Redis deletion wins over both the resident queue and
            # a stale SQL archive. Keep traversing its descendants, however.
            async with self._redis.pipeline(transaction=False) as pipe:
                for sid in batch:
                    pipe.hget(self._session_key(sid), 'deleted')
                deleted = await pipe.execute()
            batch = [sid for sid, marker in zip(batch, deleted) if marker != '1']
            if not batch:
                continue
            resident = await self._redis.smismember(self._key("resident"), batch)
            suspended = await self._redis.smismember(self._key("suspended"), batch)
            if any(suspended):
                return True
            hot_ids = [sid for sid, hot in zip(batch, resident) if hot]
            if hot_ids:
                rows, _ = await self._run_metadata_batch(hot_ids)
                if any(row.state not in TERMINAL_RUN_STATES for row in rows):
                    return True
            cold.extend(sid for sid, hot in zip(batch, resident) if not hot)
        # Topology was resolved above. A recursive archive query here would
        # revisit resident descendants and let stale MySQL state overrule Redis.
        return await self._archive.has_nonterminal_sessions(cold) if cold else False

    async def filter_suspended_session_ids(self, session_ids):
        await self._ensure_ready()
        selected = set()
        ids = tuple(session_ids)
        for start in range(0, len(ids), 128):
            batch = ids[start:start + 128]
            async with self._redis.pipeline(transaction=False) as pipe:
                for sid in batch:
                    pipe.hget(self._session_key(sid), "deleted")
                deleted = await pipe.execute()
            batch = [sid for sid, marker in zip(batch, deleted) if marker != "1"]
            if not batch:
                continue
            resident = await self._redis.smismember(self._key("resident"), list(batch))
            waiting = await self._redis.smismember(self._key("suspended"), list(batch))
            selected.update(sid for sid, pending in zip(batch, waiting) if pending)
            cold = [sid for sid, hot, pending in zip(batch, resident, waiting) if not hot and not pending]
            if cold:
                selected.update(await self._archive.filter_suspended_session_ids(cold))
            # Legacy resident data may predate the suspended index. Inspect its
            # metadata in a batch without installing execution/event history.
            hot_ids = [sid for sid, hot, pending in zip(batch, resident, waiting) if hot and not pending]
            if hot_ids:
                rows, _ = await self._run_metadata_batch(hot_ids)
                selected.update(row.session_id for row in rows if row.state == RunState.SUSPENDED)
        return selected

    async def _read_attachment_bytes(self, sid, identity):
        if (sid, identity) in self._attachment_payloads:
            return self._attachment_payloads[(sid, identity)]
        content = await self._redis.hget(self._key(f"attachments:{sid}"), identity)
        return base64.b64decode(content) if content is not None else await self._archive._read_attachment_bytes(sid, identity)

    async def get_derived_state(self, sid, namespace, key):
        await self._ensure_session_loaded(sid)
        value = await self._redis.hget(self._key(f"derived:{sid}"), self._lookup_key((namespace, key)))
        return json.loads(value) if value is not None else None

    async def _delete_storage_locked(self, sid, deleted_session_ids):
        # Tombstones make deletion authoritative before MySQL is reachable.
        delete_id = uuid.uuid4().hex
        async def write():
            async with self._redis.pipeline() as pipe:
                await self._owned(pipe)
                pipe.multi()
                for deleted in deleted_session_ids:
                    pipe.hset(self._session_key(deleted), mapping={"deleted": "1", "delete_id": delete_id})
                    pipe.persist(self._session_key(deleted))
                    pipe.sadd(self._key("pending"), deleted)
                    pipe.sadd(self._key("resident"), deleted)
                    pipe.srem(self._key("suspended"), deleted)
                    for kind, identity, _ in self._persisted_locations.get(deleted, ()):
                        pipe.hdel(self._key("locations"), self._lookup_key((kind, identity)))
                    for row in self._persisted_start_keys.get(deleted, ()):
                        pipe.hdel(self._key("starts"), self._lookup_key(row[:3]))
                await pipe.execute()
        try:
            await self._retry_transaction(write)
        except Exception:
            self._recovery_required.update(deleted_session_ids)
            for deleted in deleted_session_ids:
                if await self._redis.hget(self._session_key(deleted), "delete_id") != delete_id:
                    raise
        self._recovery_required.difference_update(deleted_session_ids)
        for deleted in deleted_session_ids:
            self._forget_persisted_session(deleted)
        self._wake.set()

    async def archive_pending(self):
        await self._ensure_ready()
        async with self._archive_lock:
            pending = sorted(await self._redis.smembers(self._key("pending")))
            for sid in pending:
                try:
                    await self._archive_session(sid)
                except Exception as exc:
                    LOGGER.warning("session.mysql.archive_failed", "MySQL Session archive will retry",
                                   session_id=sid, attributes=self._failure_attributes(exc))

    async def _compact_hot(self, sid, fields):
        """Stage small immutable chunks, then atomically publish the new base."""
        payload = await asyncio.to_thread(self._decode_hot, fields)
        encoded = await asyncio.to_thread(_json, payload)
        token, parts = await self._stage_snapshot(encoded)
        snapshot_key = self._key(f"snapshot:{token}")
        key = self._session_key(sid)
        published = False
        async def publish():
            nonlocal published
            async with self._redis.pipeline() as pipe:
                await self._owned(pipe)
                await pipe.watch(key)
                await pipe.watch(snapshot_key)
                if await pipe.hlen(snapshot_key) != parts:
                    raise self._storage_error("Redis snapshot staging expired before publication")
                if await pipe.hget(key, "base_snapshot") != fields.get("base_snapshot"):
                    return
                if not await pipe.exists(key) or await pipe.hget(key, "deleted") == "1":
                    return
                pipe.multi()
                pipe.persist(snapshot_key)
                pipe.hset(key, mapping={"base_snapshot": token, "base_parts": parts,
                                       "base_revision": fields["revision"]})
                obsolete = ["base", *(name for name in fields if name.startswith("d:"))]
                for start in range(0, len(obsolete), 128):
                    pipe.hdel(key, *obsolete[start:start + 128])
                await pipe.execute()
                published = True
        await self._retry_transaction(publish)
        if published and fields.get("base_snapshot"):
            await self._redis.delete(self._key(f"snapshot:{fields['base_snapshot']}"))
        return payload

    async def _archive_session(self, sid):
        from redis.exceptions import WatchError
        started = time.perf_counter()
        key = self._session_key(sid)
        fields = await self._read_hot(key)
        if not fields:
            raise self._storage_error(f"Pending Redis Session data is missing: {sid}")
        deleted = fields.get("deleted") == "1"
        if deleted:
            await self._archive.delete_archived_sessions((sid,))
        else:
            base = await asyncio.to_thread(json.loads, fields["base"])
            base_revision = int(base["sessions"][0]["revision"])
            previous = await self._archive.revision(sid)
            content = await self._redis.hgetall(self._key(f"attachments:{sid}"))
            attachments = await asyncio.to_thread(lambda: {
                identity: base64.b64decode(value) for identity, value in content.items()})
            if previous is None or previous < base_revision:
                # New sessions have a small initial base. Legacy compact snapshots
                # need a one-time baseline before their retained journal can append.
                await self._archive.archive_session(base, attachments)
                previous = base_revision
            else:
                await self._archive.archive_attachments(sid, attachments)
            batch, size = [], 0
            for revision in range(previous + 1, int(fields["revision"]) + 1):
                encoded = fields[f"d:{revision}"]
                encoded_size = len(encoded.encode("utf-8"))
                if batch and (len(batch) >= self.archive_batch_rows or size + encoded_size > self.archive_batch_bytes):
                    await self._archive.archive_batch(sid, batch)
                    batch, size = [], 0
                    await asyncio.sleep(0)
                batch.append((revision, encoded))
                size += encoded_size
            if batch:
                await self._archive.archive_batch(sid, batch)
            if len([name for name in fields if name.startswith("d:")]) >= self.snapshot_interval:
                await self._compact_hot(sid, fields)
        try:
            async with self._redis.pipeline() as pipe:
                await self._owned(pipe)
                await pipe.watch(key)
                revision, current_deleted, quiescent = await pipe.hmget(key, ("revision", "deleted", "quiescent"))
                if revision != fields.get("revision") or current_deleted != fields.get("deleted"):
                    return
                token = await pipe.hget(key, "base_snapshot")
                pipe.multi()
                pipe.srem(self._key("pending"), sid)
                if deleted:
                    pipe.delete(key, self._key(f"attachments:{sid}"), self._key(f"derived:{sid}"))
                    if token:
                        pipe.delete(self._key(f"snapshot:{token}"))
                    pipe.hset(key, "deleted", "1")
                    pipe.hdel(self._key("parents"), sid)
                else:
                    pipe.hset(key, "archived_revision", fields["revision"])
                if deleted or quiescent == "1":
                    pipe.srem(self._key("resident"), sid)
                    if deleted:
                        pipe.srem(self._key("suspended"), sid)
                    if not deleted:
                        cached_keys = [key, self._key(f"attachments:{sid}"), self._key(f"derived:{sid}")]
                        if token:
                            cached_keys.append(self._key(f"snapshot:{token}"))
                        for cached in cached_keys:
                            pipe.expire(cached, self.retention_seconds)
                await pipe.execute()
        except WatchError:
            return
        LOGGER.debug("session.mysql.archived", "MySQL Session archive completed", session_id=sid,
                     revision=fields.get("revision"), duration_ms=round((time.perf_counter() - started) * 1000, 3))

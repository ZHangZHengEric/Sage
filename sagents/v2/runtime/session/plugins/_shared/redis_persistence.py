"""Redis persistence with a pluggable SQL archive for the unified SessionStore.

Redis requires AOF persistence and noeviction. Active, unarchived state has no TTL.
Coordination and subscriptions are provided by the public Redis/SQL plugin.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import time
import uuid
from typing import Any, TYPE_CHECKING, cast

if TYPE_CHECKING:
    from .redis_session import RedisSessionCoordination
from sagents.v2.runtime.session.run_metadata import RunMetadata

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.run_state import RunState, TERMINAL_RUN_STATES
from sagents.v2.runtime.observability.logs import get_logger
from .aggregate import _json, _principal_lookup_key
from .redis_heads import RedisManagedSessionHeads
from .redis_archive import RedisArchiveProtocol
from .redis_metadata import metadata_index_keys, prepare_run_metadata, publish_run_metadata


LOGGER = get_logger(__name__)
_STOPPED = TERMINAL_RUN_STATES | {RunState.SUSPENDED}
_EVENT_TAIL_ROWS = 256
_EVENT_TAIL_ROW_BYTES = 16 * 1024


class RedisSessionPersistence(RedisArchiveProtocol, RedisManagedSessionHeads):
    durable_history_pages = False
    archive_batch_rows = 32
    archive_batch_bytes = 256 * 1024
    snapshot_chunk_chars = 16 * 1024

    def __init__(
        self,
        dsn,
        *,
        redis_url,
        table_prefix=None,
        key_prefix=None,
        archive_interval_seconds=1.0,
        retention_seconds=3600,
        **kwargs,
    ):
        if not redis_url or archive_interval_seconds <= 0 or retention_seconds < 1:
            raise ValueError(
                "Redis URL, positive archive interval and retention are required"
            )
        super().__init__(dsn, table_prefix=table_prefix, **kwargs)
        identity = self._archive_identity(dsn)
        identity["table_prefix"] = self.table_prefix
        digest = hashlib.sha256(_json(identity).encode()).hexdigest()[:24]
        self.key_prefix = key_prefix or f"sage:session:{{{digest}}}:distributed"
        self.redis_url = redis_url
        self.archive_interval_seconds = float(archive_interval_seconds)
        self.retention_seconds = int(retention_seconds)
        # redis-py does not narrow its bytes/str return types for decode_responses;
        # keep the optional transport boundary dynamic, including injected clients.
        self._redis: Any = None
        self._archive = self._archive_type(
            dsn,
            table_prefix=table_prefix,
            provision_schema=self._provision_schema,
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
        return {
            "plugin": self.redis_plugin_id,
            "table_prefix": self.table_prefix,
            "key_prefix": self.key_prefix,
            "format": self.format_version,
        }

    def _storage_error(self, message):
        return SageV2Error(
            RuntimeErrorInfo(
                code="session_store.redis_unavailable",
                category=ErrorCategory.RESOURCE_LOST,
                message=message,
                safe_to_resume=True,
            )
        )

    @staticmethod
    async def _retry_transaction(operation):
        from redis.exceptions import WatchError

        for attempt in range(5):
            try:
                return await operation()
            except WatchError:
                if attempt == 4:
                    raise

    @staticmethod
    def _lookup_key(values):
        return _json(list(values))

    def _durable_event_tail(self, run_id):
        return self._key("durable-event-tail:" + run_id)

    @staticmethod
    def _event_head_field(run_id):
        return "event_head:" + run_id

    def _event_tail_changes(self, mutation):
        appends = mutation["appends"].get("run_events", {})
        replacements = mutation["replacements"].get("run_events", {})
        changed_runs = {
            row["run_id"]: row["last_run_sequence"]
            for row in (*mutation["upserts"].get("runs", ()), *mutation["patches"].get("runs", ()))
        }
        tails = {}
        for rid, head in changed_runs.items():
            events = replacements.get(rid, appends.get(rid, ()))
            members = {}
            for event in events[-_EVENT_TAIL_ROWS:]:
                raw = _json(event)
                if len(raw.encode("utf-8")) <= _EVENT_TAIL_ROW_BYTES:
                    members[raw] = event["run_sequence"]
            tails[rid] = (head, members, rid in replacements)
        return tails

    async def _commit_storage_locked(self, sid):
        await self._ensure_ready()
        started = time.perf_counter()
        mutation = self._session_mutation_locked(sid).model_dump(
            mode="json", exclude={"kind"}
        )
        head = mutation["upserts"]["sessions"][0]
        revision = int(head["revision"])
        expected = self._persisted_session_revisions.get(sid)
        # A run body can be read from memory after its archived Redis cache expires.
        # Reload the archived base before appending the next delta in that case.
        if expected is not None and not await self._redis.exists(
            self._session_key(sid)
        ):
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
        stopped = any(
            row["state"] in _STOPPED
            for row in [
                *mutation["upserts"].get("runs", ()),
                *mutation["patches"].get("runs", ()),
            ]
        )
        session_runs = tuple(self._runs[rid] for rid in self._session_run_ids_locked(sid))
        quiescent = all(row.state in _STOPPED for row in session_runs)
        suspended = any(row.state == RunState.SUSPENDED for row in session_runs)
        intents = [
            {"run": self._run_snapshot(row).model_dump(mode="json"),
             "context": row.request_context.model_dump(mode="json")}
            for row in session_runs
            if self._is_dispatchable_run(row) and row.request_context is not None
        ]
        attachments = {
            identity: base64.b64encode(content).decode("ascii")
            for identity, content in self._pending_attachments(sid)
        }
        commit_id = uuid.uuid4().hex
        key = self._session_key(sid)
        tails = self._event_tail_changes(mutation)
        deleted_runs = [row[0] for row in mutation["deletes"].get("runs", ())]
        metadata_keys = metadata_index_keys(self, sid)
        metadata_updated = {
            row["run_id"] for row in (
                *mutation["upserts"].get("runs", ()), *mutation["patches"].get("runs", ())
            )
            if "state" in row
        }

        async def write():
            async with self._redis.pipeline() as pipe:
                await cast("RedisSessionCoordination", self)._owned(pipe)
                await pipe.watch(key)
                previous, indexed_revision, index_epoch, metadata_revision = await pipe.hmget(
                    key, ("revision", "event_index_revision", "event_index_epoch", "run_metadata_revision")
                )
                restoring = expected is None and sid in self._backup_restores.get()
                if restoring and await pipe.hget(key, "deleted") == "1":
                    previous = None
                if previous != (str(expected) if expected is not None else None):
                    raise self._conflict(
                        "session.revision_conflict",
                        f"Redis Session revision changed for {sid}",
                    )
                old_fields = await pipe.hkeys(key) if compact else ()
                snapshot_token = await pipe.hget(key, "base_snapshot")
                parent = head.get("parent_session_id")
                old_parent = await pipe.hget(self._key("parents"), sid) if parent else None
                if staged_base:
                    token, parts = staged_base
                    staged_key = self._key(f"snapshot:{token}")
                    await pipe.watch(staged_key)
                    if await pipe.hlen(staged_key) != parts:
                        raise self._storage_error(
                            "Redis snapshot staging expired before publication"
                        )
                # A mixed-version writer can advance the ledger without
                # maintaining the derived tail. Retire those heads on the
                # first subsequent indexed commit.
                if compact or previous != indexed_revision or not index_epoch:
                    index_epoch = commit_id
                fields = [self._event_head_field(rid) for rid in tails]
                old_heads = await pipe.hmget(key, fields) if fields else ()
                rebuild_metadata = compact or metadata_revision != previous
                owner, metadata = prepare_run_metadata(
                    self, sid, session_runs if rebuild_metadata else (
                        self._runs[rid] for rid in metadata_updated
                    )
                )
                metadata_ids = tuple(dict.fromkeys((*metadata, *deleted_runs)))
                old_metadata = (
                    dict(zip(metadata_ids, await pipe.hmget(metadata_keys[1], metadata_ids), strict=True))
                    if not rebuild_metadata and metadata_ids else {}
                )
                pipe.multi()
                if restoring:
                    pipe.hdel(
                        key,
                        "deleted",
                        "delete_id",
                        "archived_revision",
                        "base",
                        "base_snapshot",
                        "base_parts",
                        "base_revision",
                    )
                    if snapshot_token:
                        pipe.delete(self._key(f"snapshot:{snapshot_token}"))
                if compact:
                    stale = [field for field in old_fields if field.startswith("d:")]
                    if stale:
                        pipe.hdel(key, *stale)
                values = {
                    "revision": revision,
                    "last_sequence": head["last_sequence"],
                    "commit_id": commit_id,
                    "quiescent": "1" if quiescent else "0",
                    "activity_revision": revision,
                    "activity_commit": commit_id,
                    "has_nonterminal": int(not quiescent or suspended),
                    "has_suspended": int(suspended),
                    "dispatch_revision": revision,
                    "dispatch_intents": _json(intents),
                    "event_index_revision": revision,
                    "event_index_epoch": index_epoch,
                    "run_metadata_revision": revision,
                    "run_metadata_owner": owner,
                }
                if quiescent and not suspended:
                    from sagents.v2.runtime.artifact.video_storage import VIDEO_COPY_RECEIPT_PREFIX
                    # Hosted copies require external cleanup before references
                    # disappear. Only ordinary terminal trees can be tombstoned
                    # using their reverse lookup fields alone.
                    if not any(a.startswith(VIDEO_COPY_RECEIPT_PREFIX) for a in self._sessions[sid].attachments):
                        values["cleanup_lookups"] = _json([
                            [self._lookup_key((kind, identity)) for kind, identity, _ in rows],
                            [self._lookup_key(row[:3]) for row in starts],
                        ])
                        values["cleanup_revision"] = revision
                    else:
                        values["cleanup_revision"] = ""
                else:
                    values["cleanup_revision"] = ""
                publish_run_metadata(pipe, metadata_keys, rebuild=rebuild_metadata, members=metadata,
                                     previous=old_metadata, deleted=deleted_runs)
                for metadata_key in metadata_keys:
                    pipe.persist(metadata_key)
                for (rid, (event_head, members, replaced)), old_head in zip(tails.items(), old_heads, strict=True):
                    tail = self._durable_event_tail(rid)
                    if replaced or not old_head or old_head.partition(":")[0] != index_epoch:
                        pipe.delete(tail)
                    if members:
                        pipe.zadd(tail, members)
                    pipe.zremrangebyscore(tail, "-inf", event_head - _EVENT_TAIL_ROWS)
                    pipe.expire(tail, min(self.retention_seconds, 300))
                    values[self._event_head_field(rid)] = f"{index_epoch}:{event_head}"
                for rid in deleted_runs:
                    pipe.hdel(key, self._event_head_field(rid))
                    pipe.delete(self._durable_event_tail(rid))
                if staged_base:
                    token, parts = staged_base
                    values.update(
                        base_snapshot=token, base_parts=parts, base_revision=revision
                    )
                    pipe.persist(self._key(f"snapshot:{token}"))
                else:
                    values["base" if compact else f"d:{revision}"] = encoded
                    if compact:
                        values["base_revision"] = revision
                pipe.hset(key, mapping=values)
                pipe.persist(key)
                if snapshot_token and not restoring:
                    pipe.persist(self._key(f"snapshot:{snapshot_token}"))
                pipe.sadd(self._key("resident"), sid)
                if intents:
                    pipe.sadd(self._key("dispatch_sessions"), sid)
                else:
                    pipe.srem(self._key("dispatch_sessions"), sid)
                if suspended:
                    pipe.sadd(self._key("suspended"), sid)
                else:
                    pipe.srem(self._key("suspended"), sid)
                if stopped or quiescent or revision % self.archive_batch_rows == 0:
                    pipe.sadd(self._key("pending"), sid)
                for kind, identity, _ in rows - self._persisted_locations.get(
                    sid, set()
                ):
                    pipe.hset(
                        self._key("locations"), self._lookup_key((kind, identity)), sid
                    )
                for kind, identity, _ in (
                    self._persisted_locations.get(sid, set()) - rows
                ):
                    pipe.hdel(
                        self._key("locations"), self._lookup_key((kind, identity))
                    )
                for row in starts - self._persisted_start_keys.get(sid, set()):
                    pipe.hset(self._key("starts"), self._lookup_key(row[:3]), sid)
                for row in self._persisted_start_keys.get(sid, set()) - starts:
                    pipe.hdel(self._key("starts"), self._lookup_key(row[:3]))
                if parent and parent != old_parent:
                    order = self._key("child-edges:v2")
                    if old_parent is not None:
                        pipe.zrem(order, old_parent + "\0" + sid)
                    pipe.hset(self._key("parents"), sid, parent)
                    pipe.zadd(order, {parent + "\0" + sid: 0})
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
        self._remember_persisted_session(
            sid,
            revision,
            {
                rid: len(self._run_events[rid])
                for rid in self._session_run_ids_locked(sid)
            },
            rows,
            starts,
            0 if compact else self._persisted_mutation_counts.get(sid, 0) + 1,
        )
        self._session_cache.touch(sid, charge=4 * len(encoded.encode()))
        self._forget_attachment_bytes(sid)
        if stopped or quiescent or revision % self.archive_batch_rows == 0:
            self._wake.set()
        LOGGER.debug(
            "session.redis.commit",
            "Redis Session commit completed",
            session_id=sid,
            revision=revision,
            payload_bytes=len(encoded.encode()),
            snapshot=compact,
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
        )

    def _decode_hot(self, fields):
        base = json.loads(fields["base"])
        deltas = sorted(
            (int(field[2:]), value)
            for field, value in fields.items()
            if field.startswith("d:")
        )
        return self._replay_mutations(
            base, deltas, int(fields["revision"]), int(fields["last_sequence"])
        )

    async def _read_hash_fields(self, key, names):
        """Pipeline small HMGET commands without accumulating an unbounded reply."""
        values = []
        for batch_start in range(0, len(names), 256):
            async with self._redis.pipeline(transaction=False) as pipe:
                for start in range(batch_start, min(batch_start + 256, len(names)), 8):
                    pipe.hmget(key, names[start : start + 8])
                for rows in await pipe.execute():
                    values.extend(rows)
        return values

    async def _read_hot(self, key):
        """Read an immutable base plus a bounded range of deltas, retrying compaction races."""
        names = (
            "revision",
            "last_sequence",
            "deleted",
            "base_revision",
            "base_snapshot",
            "base_parts",
        )
        for _ in range(5):
            values = await self._redis.hmget(key, names)
            fields = {
                name: value for name, value in zip(names, values) if value is not None
            }
            if fields.get("deleted") == "1":
                return fields
            if values[0] is None:
                return {}
            token = fields.get("base_snapshot")
            if token:
                snapshot_key = self._key(f"snapshot:{token}")
                parts = await self._read_hash_fields(
                    snapshot_key, [str(i) for i in range(int(fields["base_parts"]))]
                )
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
                base_revision = await asyncio.to_thread(
                    lambda: int(json.loads(fields["base"])["sessions"][0]["revision"])
                )
            keys = [
                f"d:{i}" for i in range(base_revision + 1, int(fields["revision"]) + 1)
            ]
            rows = await self._read_hash_fields(key, keys)
            missing = any(row is None for row in rows)
            fields.update(zip(keys, rows))
            current = await self._redis.hmget(
                key, ("base_snapshot", "base_revision", "deleted")
            )
            if not missing and current == [
                fields.get("base_snapshot"),
                fields.get("base_revision"),
                fields.get("deleted"),
            ]:
                return fields
        raise self._conflict(
            "session.revision_conflict", "Redis Session base changed during loading"
        )

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

        for count, start in enumerate(
            range(0, len(encoded), self.snapshot_chunk_chars), 1
        ):
            chunk = encoded[start : start + self.snapshot_chunk_chars]
            chunk_size = len(chunk.encode("utf-8"))
            if batch and (
                len(batch) >= 32 or size + chunk_size > self.archive_batch_bytes
            ):
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
            return (
                None
                if fields.get("deleted") == "1"
                else await asyncio.to_thread(self._decode_hot, fields)
            )
        if await self._redis.sismember(self._key("resident"), sid):
            raise self._storage_error(
                f"Unarchived Redis Session data is missing: {sid}"
            )
        payload = await self._archive._fetch_session(sid)
        if payload is None:
            return None
        return await self._seed_archived_session(sid, payload)

    async def _fetch_sessions(self, session_ids):
        from sagents.v2.runtime.session.plugins._shared.redis_metadata import (
            read_redis_metadata_batch,
        )

        await self._ensure_ready()
        ids = tuple(dict.fromkeys(session_ids))
        result = {}
        for start in range(0, len(ids), 128):
            batch = ids[start : start + 128]
            snapshots = await read_redis_metadata_batch(self, batch)
            absent = [sid for sid, fields in snapshots.items() if not fields]
            if absent:
                resident = await self._redis.smismember(self._key("resident"), absent)
                for sid, hot in zip(absent, resident):
                    if hot:
                        raise self._storage_error(
                            f"Unarchived Redis Session data is missing: {sid}"
                        )
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
                await cast("RedisSessionCoordination", self)._owned(pipe)
                await pipe.watch(key)
                await pipe.watch(snapshot_key)
                if await pipe.hlen(snapshot_key) != parts:
                    raise self._storage_error(
                        "Redis snapshot staging expired before publication"
                    )
                if not await pipe.exists(key):
                    head = payload["sessions"][0]
                    pipe.multi()
                    quiescent = all(row["state"] in _STOPPED for row in payload["runs"])
                    pipe.hset(
                        key,
                        mapping={
                            "base_snapshot": token,
                            "base_parts": parts,
                            "base_revision": head["revision"],
                            "revision": head["revision"],
                            "last_sequence": head["last_sequence"],
                            "archived_revision": head["revision"],
                            "activity_revision": head["revision"],
                            "activity_commit": token,
                            "commit_id": token,
                            "has_nonterminal": int(any(row["state"] not in TERMINAL_RUN_STATES for row in payload["runs"])),
                            "has_suspended": int(any(row["state"] == RunState.SUSPENDED for row in payload["runs"])),
                            "quiescent": "1" if quiescent else "0",
                        },
                    )
                    if quiescent:
                        pipe.expire(key, self.retention_seconds)
                        pipe.expire(snapshot_key, self.retention_seconds)
                    else:
                        pipe.sadd(self._key("resident"), sid)
                        pipe.persist(self._key(f"snapshot:{token}"))
                    await pipe.execute()

        await self._retry_transaction(seed)
        fields = await self._read_hot(key)
        return (
            None
            if not fields or fields.get("deleted") == "1"
            else await asyncio.to_thread(self._decode_hot, fields)
        )

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
        sid = await self._redis.hget(
            self._key("locations"), self._lookup_key((kind, identity))
        )
        return (
            sid
            if sid is not None
            else await self._archive._locate_session(kind, identity)
        )

    async def _read_start_lookup(self, command, context):
        scope = (
            str(context.actor.tenant_id or ""),
            _principal_lookup_key(
                context.actor.principal_type.value, context.actor.principal_id
            ),
            command.idempotency_key,
        )
        sid = await self._redis.hget(self._key("starts"), self._lookup_key(scope))
        if sid is None:
            sid = await self._archive._read_start_lookup(command, context)
        if (
            sid is not None
            and await self._redis.hget(self._session_key(sid), "deleted") == "1"
        ):
            return None
        return sid

    async def _list_descendant_ids(self, sid):
        return await self.list_workspace_descendant_ids([sid])

    async def read_session_views(self, session_ids, **options):
        from functools import partial
        from sagents.v2.runtime.session.read_views import (
            validate_view_ids,
            project_view_state,
            apply_view_delta,
            views_from_payload,
        )
        from sagents.v2.runtime.session.plugins._shared.redis_metadata import (
            read_redis_metadata_batch,
            decode_redis_metadata,
        )

        ids = validate_view_ids(session_ids, options.get("run_ids"))
        await self._ensure_ready()
        result = {}
        missing = ids
        if not missing:
            return result
        fields = await read_redis_metadata_batch(self, missing)
        absent = [sid for sid in missing if not fields.get(sid)]
        if absent:
            resident = await self._redis.smismember(self._key("resident"), absent)
            for sid, hot in zip(absent, resident):
                if hot:
                    raise self._storage_error(
                        f"Unarchived Redis Session data is missing: {sid}"
                    )
        replay_options = {
            key: options[key] for key in ("include_events", "run_ids") if key in options
        }
        for sid, raw in fields.items():
            if not raw or raw.get("deleted") == "1":
                continue
            payload = await asyncio.to_thread(
                decode_redis_metadata,
                raw,
                project=partial(project_view_state, **replay_options),
                apply=partial(apply_view_delta, **replay_options),
            )
            result.update(
                await asyncio.to_thread(views_from_payload, payload, **options)
            )
        if absent:
            result.update(await self._archive.read_session_views(absent, **options))
        return {sid: result[sid] for sid in ids if sid in result}

    async def report_business_events(self, *, start, end, agent_id="", max_runs=10000, max_events=100000):
        from sagents.v2.runtime.session.reporting import replay_session_views

        await self._ensure_ready()
        keys = self._key("resident"), self._key("pending")
        # Session views accept up to 200 IDs. Report archive-only coverage
        # explicitly when the live cohort exceeds that budget.
        counts = await asyncio.gather(*(self._redis.scard(key) for key in keys))
        hot = tuple(sorted(await self._redis.sunion(*keys))) if max(counts) <= 200 else ()
        options = dict(start=start, end=end, agent_id=agent_id, max_runs=max_runs, max_events=max_events)
        if max(counts) > 200 or len(hot) > 200:
            report = await self._archive.report_business_events(**options)
            report.archive_pending = True
            return report
        report = await self._archive.report_business_events(**options, exclude_sessions=hot)
        if not hot:
            return report
        metadata, _ = await self._run_metadata_batch(hot)
        candidates = sorted(
            ((row.session_id, row.run_id) for row in metadata
             if start <= row.created_at.timestamp() < end and (not agent_id or row.agent_id == agent_id)),
            key=lambda item: item[1], reverse=True,
        )
        remaining = 0 if report.events_truncated else max_events - sum(run.event_count for run in report.runs.values())
        live = await replay_session_views(self, candidates, **{**options, "max_events": remaining})
        report.runs.update(live.runs)
        report.cohort_truncated |= live.cohort_truncated or len(report.runs) > max_runs
        if len(report.runs) > max_runs:
            newest = sorted(report.runs, key=lambda key: key[1], reverse=True)[:max_runs]
            report.runs = {key: report.runs[key] for key in newest}
        return report

    async def _run_metadata_batch(self, session_ids, *, backfill_index=False):
        from sagents.v2.runtime.session.run_metadata import metadata_from_payload
        from sagents.v2.runtime.session.plugins._shared.redis_metadata import (
            backfill_run_metadata,
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
            resident = await self._redis.smismember(self._key("resident"), absent)
            for sid, hot in zip(absent, resident):
                if hot:
                    raise self._storage_error(
                        f"Unarchived Redis Session data is missing: {sid}"
                    )
        cold = []
        result: list[RunMetadata] = list(rows)
        for sid, fields in snapshots.items():
            if fields.get("deleted") == "1":
                continue
            if fields:
                payload = await asyncio.to_thread(decode_redis_metadata, fields)
                if payload is not None:
                    current, heads = await asyncio.to_thread(
                        metadata_from_payload, payload
                    )
                    result.extend(current)
                    owners.update(heads)
                    if backfill_index:
                        await backfill_run_metadata(self, sid, fields, current, heads[sid])
            else:
                cold.append(sid)
        if cold:
            current, heads = await self._archive._run_metadata_batch(cold)
            result.extend(current)
            owners.update(heads)
        return tuple(result), owners

    async def authorized_run_metadata_page(self, session_ids, context, *, after=None, limit=101, agent_id='', states=()):
        from sagents.v2.runtime.session.run_metadata import RunMetadataQueries
        from .redis_metadata import _read_redis_fields_batched, read_authorized_indexed_page

        if not 1 <= limit <= 201 or len(session_ids) > 200:
            raise ValueError('invalid Run metadata page')
        await self._ensure_ready()
        positions = {sid: position for position, sid in enumerate(session_ids)}
        ids = tuple(sorted(positions, key=positions.__getitem__))
        if after is not None:
            ids = ids[ids.index(after[0]):]
        fields = ("revision", "run_metadata_revision", "deleted")
        headers = await _read_redis_fields_batched(
            self, [("hmget", self._session_key(sid), fields) for sid in ids]
        )
        absent = [sid for sid, (revision, _, deleted) in zip(ids, headers, strict=True)
                  if revision is None and deleted != "1"]
        cold = set()
        if absent:
            resident = await self._redis.smismember(self._key("resident"), absent)
            cold = {sid for sid, hot in zip(absent, resident, strict=True) if not hot}
        result = []
        fallback = []

        def cursor_for(sid):
            return after if after is not None and sid == after[0] else None

        async def flush():
            if not fallback:
                return
            options = dict(after=cursor_for(fallback[0]), limit=limit - len(result), agent_id=agent_id, states=states)
            if fallback[0] in cold:
                page = await self._archive.authorized_run_metadata_page(fallback, context, **options)
            else:
                rows, owners = await self._run_metadata_batch(fallback, backfill_index=True)
                page = RunMetadataQueries._authorized_metadata_page(self, fallback, context, rows, owners, **options)
            result.extend(page)
            fallback.clear()

        for sid, (revision, indexed, deleted) in zip(ids, headers, strict=True):
            if deleted == "1":
                continue
            if revision is None or revision != indexed:
                if fallback and ((fallback[0] in cold) != (sid in cold)):
                    await flush()
                    if len(result) == limit:
                        break
                fallback.append(sid)
                continue
            await flush()
            if len(result) == limit:
                break
            rows = await read_authorized_indexed_page(
                self, sid, context, after=cursor_for(sid), limit=limit - len(result),
                agent_id=agent_id, states=states,
            )
            if rows is None:
                fallback.append(sid)
            else:
                result.extend(rows)
            if len(result) == limit:
                break
        await flush()
        return tuple(result)

    async def _activity_batch(self, ids, *, suspended, resident_only):
        from .redis_metadata import _decode_metadata, metadata_index_keys

        field = "has_suspended" if suspended else "has_nonterminal"
        def matches(state):
            return state == RunState.SUSPENDED if suspended else state not in TERMINAL_RUN_STATES

        # Read each revision together with its predicate. Older writers can
        # leave these fields behind while advancing the canonical revision.
        async with self._redis.pipeline(transaction=True) as pipe:
            for sid in ids:
                pipe.hmget(self._session_key(sid), ("revision", "activity_revision", field, "deleted", "commit_id", "activity_commit"))
            pipe.smismember(self._key("resident"), ids)
            pipe.smismember(self._key("suspended"), ids)
            *heads, resident, waiting = await pipe.execute()
        selected = set()
        cold = []
        missing = []
        ambiguous = set()
        for sid, (revision, projected, flag, deleted, commit, indexed_commit), hot, pending in zip(ids, heads, resident, waiting, strict=True):
            if deleted == "1":
                continue
            if pending:
                selected.add(sid)
            elif not hot and (resident_only or revision is None):
                cold.append(sid)
            elif revision and revision == projected and commit and commit == indexed_commit and flag in {"0", "1"}:
                if flag == "1":
                    selected.add(sid)
            else:
                missing.append(sid)
                if revision and revision == projected and commit != indexed_commit:
                    ambiguous.add(sid)
        if missing:
            async with self._redis.pipeline(transaction=True) as pipe:
                for sid in missing:
                    pipe.hmget(self._session_key(sid), ("revision", "run_metadata_revision", "deleted"))
                    pipe.hvals(metadata_index_keys(self, sid)[1])
                results = await pipe.execute()
            legacy = []
            for sid, (revision, indexed, deleted), members in zip(missing, results[::2], results[1::2], strict=True):
                if deleted == "1":
                    continue
                if revision and revision == indexed and members and sid not in ambiguous:
                    if any(matches(_decode_metadata(member).state) for member in members):
                        selected.add(sid)
                else:
                    legacy.append(sid)
            if legacy:
                rows, _ = await self._run_metadata_batch(legacy, backfill_index=True)
                selected.update(row.session_id for row in rows if matches(row.state))
        return selected, cold

    async def _has_nonterminal_batchwise(self, ids, *, resident_only):
        for start in range(0, len(ids), 128):
            active, cold = await self._activity_batch(ids[start:start + 128], suspended=False, resident_only=resident_only)
            if active or (cold and await self._archive.has_nonterminal_sessions(cold)):
                return True
        return False

    async def has_nonterminal_session_trees(self, session_ids):
        ids = sorted(await self._collect_session_tree(session_ids))
        return await self._has_nonterminal_batchwise(ids, resident_only=True)

    async def has_nonterminal_sessions(self, session_ids):
        await self._ensure_ready()
        return await self._has_nonterminal_batchwise(tuple(dict.fromkeys(session_ids)), resident_only=False)

    async def filter_suspended_session_ids(self, session_ids):
        await self._ensure_ready()
        selected = set()
        ids = tuple(session_ids)
        for start in range(0, len(ids), 128):
            hot, cold = await self._activity_batch(ids[start:start + 128], suspended=True, resident_only=True)
            selected.update(hot)
            if cold:
                selected.update(await self._archive.filter_suspended_session_ids(cold))
        return selected

    async def _read_attachment_bytes(self, sid, identity):
        if (sid, identity) in self._attachment_payloads:
            return self._attachment_payloads[(sid, identity)]
        content = await self._redis.hget(self._key(f"attachments:{sid}"), identity)
        return (
            base64.b64decode(content)
            if content is not None
            else await self._archive._read_attachment_bytes(sid, identity)
        )

    async def get_derived_state(self, sid, namespace, key):
        await self._ensure_session_loaded(sid)
        value = await self._redis.hget(
            self._key(f"derived:{sid}"), self._lookup_key((namespace, key))
        )
        return json.loads(value) if value is not None else None

    async def _delete_storage_locked(self, sid, deleted_session_ids, *, lookups=None):
        # Tombstones make deletion authoritative before SQL is reachable.
        delete_id = uuid.uuid4().hex

        async def write():
            async with self._redis.pipeline() as pipe:
                await cast("RedisSessionCoordination", self)._owned(pipe)
                root_key = self._session_key(sid)
                await pipe.watch(root_key)
                first_deletion = await pipe.hget(root_key, "deleted") != "1"
                pipe.multi()
                if first_deletion and sid in deleted_session_ids:
                    # The root tombstone owns the manifest. Old workers may
                    # overwrite or acknowledge it; readers verify delete_id.
                    pipe.hset(root_key, mapping={
                        "delete_manifest_id": delete_id,
                        "delete_members": _json(list(deleted_session_ids)),
                    })
                for deleted in deleted_session_ids:
                    pipe.hset(
                        self._session_key(deleted),
                        mapping={"deleted": "1", "delete_id": delete_id, "delete_root": sid},
                    )
                    pipe.persist(self._session_key(deleted))
                    pipe.sadd(self._key("pending"), deleted)
                    pipe.sadd(self._key("resident"), deleted)
                    pipe.srem(self._key("suspended"), deleted)
                    locations, starts = lookups[deleted] if lookups is not None else (
                        [self._lookup_key((kind, identity)) for kind, identity, _ in self._persisted_locations.get(deleted, ())],
                        [self._lookup_key(row[:3]) for row in self._persisted_start_keys.get(deleted, ())],
                    )
                    if locations:
                        pipe.hdel(self._key("locations"), *locations)
                    if starts:
                        pipe.hdel(self._key("starts"), *starts)
                await pipe.execute()

        try:
            await self._retry_transaction(write)
        except Exception:
            self._recovery_required.update(deleted_session_ids)
            for deleted in deleted_session_ids:
                if (
                    await self._redis.hget(self._session_key(deleted), "delete_id")
                    != delete_id
                ):
                    raise
        self._recovery_required.difference_update(deleted_session_ids)
        for deleted in deleted_session_ids:
            self._forget_persisted_session(deleted)
        self._wake.set()

"""Redis-to-SQL archive batches, compaction and retry acknowledgement."""

from __future__ import annotations

import asyncio
import base64
import json
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from .redis_session import RedisSessionCoordination

from sagents.v2.runtime.observability.logs import get_logger
from .aggregate import _json

LOGGER = get_logger(__name__)


class RedisArchiveProtocol:
    async def _archive_loop(self):
        while True:
            try:
                await self.archive_pending()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                LOGGER.warning(
                    "session.redis.worker_failed",
                    "Session archive worker will retry",
                    attributes=self._failure_attributes(exc),
                )
            try:
                await asyncio.wait_for(self._wake.wait(), self.archive_interval_seconds)
            except TimeoutError:
                pass
            self._wake.clear()

    @staticmethod
    def _failure_attributes(exc):
        info = getattr(exc, "info", None)
        return {
            "error_type": type(exc).__name__,
            "error_code": getattr(info, "code", None),
            "error_message": getattr(info, "message", str(exc)),
        }

    async def archive_pending(self):
        await self._ensure_ready()
        async with self._archive_lock:
            pending = sorted(await self._redis.smembers(self._key("pending")))
            for sid in pending:
                try:
                    await self._archive_session(sid)
                except Exception as exc:
                    LOGGER.warning(
                        f"session.{self.archive_backend}.archive_failed",
                        "SQL Session archive will retry",
                        session_id=sid,
                        attributes=self._failure_attributes(exc),
                    )

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
                await cast("RedisSessionCoordination", self)._owned(pipe)
                await pipe.watch(key)
                await pipe.watch(snapshot_key)
                if await pipe.hlen(snapshot_key) != parts:
                    raise self._storage_error(
                        "Redis snapshot staging expired before publication"
                    )
                if await pipe.hget(key, "base_snapshot") != fields.get("base_snapshot"):
                    return
                if not await pipe.exists(key) or await pipe.hget(key, "deleted") == "1":
                    return
                ttl = await pipe.pttl(key)
                pipe.multi()
                if ttl > 0:
                    pipe.pexpire(snapshot_key, ttl)
                else:
                    pipe.persist(snapshot_key)
                pipe.hset(
                    key,
                    mapping={
                        "base_snapshot": token,
                        "base_parts": parts,
                        "base_revision": fields["revision"],
                    },
                )
                obsolete = ["base", *(name for name in fields if name.startswith("d:"))]
                for start in range(0, len(obsolete), 128):
                    pipe.hdel(key, *obsolete[start : start + 128])
                await pipe.execute()
                published = True

        async with self._guard("session:" + sid):
            await self._retry_transaction(publish)
        if published and fields.get("base_snapshot"):
            await self._redis.delete(self._key(f"snapshot:{fields['base_snapshot']}"))
        return payload

    async def _write_archive_snapshot(self, sid, fields):
        """Write an immutable snapshot while SQL serialization remains held."""
        deleted = fields.get("deleted") == "1"
        if deleted:
            await self._archive.delete_archived_sessions((sid,))
        else:
            base = await asyncio.to_thread(json.loads, fields["base"])
            base_revision = int(base["sessions"][0]["revision"])
            previous = await self._archive.revision(sid)
            content = await self._redis.hgetall(self._key(f"attachments:{sid}"))
            attachments = await asyncio.to_thread(
                lambda: {
                    identity: base64.b64decode(value)
                    for identity, value in content.items()
                }
            )
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
                if batch and (
                    len(batch) >= self.archive_batch_rows
                    or size + encoded_size > self.archive_batch_bytes
                ):
                    await self._archive.archive_batch(sid, batch)
                    batch, size = [], 0
                    await asyncio.sleep(0)
                batch.append((revision, encoded))
                size += encoded_size
            if batch:
                await self._archive.archive_batch(sid, batch)

    async def _ack_archive_snapshot(self, sid, fields):
        from redis.exceptions import WatchError

        key = self._session_key(sid)
        deleted = fields.get("deleted") == "1"
        try:
            async with self._redis.pipeline() as pipe:
                await cast("RedisSessionCoordination", self)._owned(pipe)
                await pipe.watch(key)
                revision, current_deleted, quiescent, base_snapshot = await pipe.hmget(
                    key, ("revision", "deleted", "quiescent", "base_snapshot")
                )
                if revision != fields.get("revision") or current_deleted != fields.get(
                    "deleted"
                ) or base_snapshot != fields.get("base_snapshot"):
                    return
                token = await pipe.hget(key, "base_snapshot")
                pipe.multi()
                pipe.srem(self._key("pending"), sid)
                if deleted:
                    pipe.delete(
                        key,
                        self._key(f"attachments:{sid}"),
                        self._key(f"derived:{sid}"),
                    )
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
                        cached_keys = [
                            key,
                            self._key(f"attachments:{sid}"),
                            self._key(f"derived:{sid}"),
                        ]
                        if token:
                            cached_keys.append(self._key(f"snapshot:{token}"))
                        for cached in cached_keys:
                            pipe.expire(cached, self.retention_seconds)
                await pipe.execute()
        except WatchError:
            return

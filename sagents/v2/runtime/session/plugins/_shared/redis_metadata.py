"""Backend metadata loading over the canonical Session projection."""

from dataclasses import asdict, replace
from datetime import datetime, timezone
import json

from sagents.v2.contracts.errors import ErrorCategory, SageV2Error
from sagents.v2.contracts.principals import ActorRef
from sagents.v2.contracts.run_state import RunState
from sagents.v2.runtime.session.metadata_replay import (
    project_metadata_state,
    apply_metadata_delta,
)
from sagents.v2.runtime.session.run_metadata import RunMetadata, metadata_from_run
from .aggregate import _json


def metadata_index_keys(store, sid):
    return store._key("run-metadata-order:" + sid), store._key("run-metadata-members:" + sid)


def _metadata_sort_key(created_at, run_id):
    return created_at.astimezone(timezone.utc).isoformat(timespec="microseconds") + ":" + run_id + "\0"


def _encode_metadata(row):
    values = asdict(row)
    values["created_at"] = row.created_at.isoformat()
    values["session_created_at"] = row.session_created_at.isoformat()
    return _metadata_sort_key(row.created_at, row.run_id) + _json(values)


def _decode_metadata(member):
    values = json.loads(member.partition("\0")[2])
    values["state"] = RunState(values["state"])
    for field in ("created_at", "session_created_at"):
        values[field] = datetime.fromisoformat(values[field])
    return RunMetadata(**values)


def prepare_run_metadata(store, sid, runs):
    head = store._sessions[sid]
    owner = head.owner
    if owner is None:
        owner = store._derive_session_owner(sid, runs=store._runs, session_events=store._session_events)
    members = {row.run_id: _encode_metadata(replace(metadata_from_run(row, row.start_command),
               session_created_at=head.created_at, parent_session_id=head.parent_session_id)) for row in runs}
    return (owner.model_dump_json() if owner is not None else "null"), members


def publish_run_metadata(pipe, keys, *, rebuild, members, previous, deleted):
    order_key, members_key = keys
    if rebuild:
        pipe.delete(order_key, members_key)
    else:
        obsolete = [old for rid, old in previous.items() if old is not None and old != members.get(rid)]
        if obsolete:
            pipe.zrem(order_key, *obsolete)
        if deleted:
            pipe.hdel(members_key, *deleted)
    changed = {rid: member for rid, member in members.items() if member != previous.get(rid)}
    if changed:
        pipe.hset(members_key, mapping=changed)
        pipe.zadd(order_key, {member: 0 for member in changed.values()})


async def backfill_run_metadata(store, sid, head, rows, owner):
    """Install an old ledger's read index only while its revision still matches."""
    from redis.exceptions import WatchError

    key = store._session_key(sid)
    keys = metadata_index_keys(store, sid)
    async with store._redis.pipeline() as pipe:
        try:
            await pipe.watch(key)
            revision, indexed, deleted, commit_id, base_snapshot = await pipe.hmget(
                key, ("revision", "run_metadata_revision", "deleted", "commit_id", "base_snapshot")
            )
            if (revision != head["revision"] or indexed == revision or deleted == "1"
                    or commit_id != head.get("commit_id") or base_snapshot != head.get("base_snapshot")):
                return
            ttl = await pipe.pttl(key)
            if ttl == -2:
                return
            members = {row.run_id: _encode_metadata(row) for row in rows}
            pipe.multi()
            publish_run_metadata(pipe, keys, rebuild=True, members=members, previous={}, deleted=())
            if ttl >= 0:
                for index_key in keys:
                    pipe.pexpire(index_key, ttl)
            pipe.hset(key, mapping={"run_metadata_revision": revision, "run_metadata_owner": _json(owner)})
            await pipe.execute()
        except WatchError:
            return


async def read_authorized_indexed_page(store, sid, context, *, after, limit, agent_id, states):
    from redis.exceptions import WatchError

    key = store._session_key(sid)
    order_key, _ = metadata_index_keys(store, sid)
    for _ in range(3):
        async with store._redis.pipeline() as pipe:
            try:
                await pipe.watch(key)
                revision, indexed, deleted, owner = await pipe.hmget(
                    key, ("revision", "run_metadata_revision", "deleted", "run_metadata_owner")
                )
                if deleted == "1":
                    return ()
                if not revision or indexed != revision or owner is None:
                    return None
                try:
                    store._authorize_session_owner(
                        None if owner == "null" else ActorRef.model_validate_json(owner), context
                    )
                except SageV2Error as exc:
                    if exc.info.category == ErrorCategory.AUTHORIZATION:
                        return ()
                    raise
                lower = "-" if after is None else "(" + _metadata_sort_key(
                    datetime.fromisoformat(after[1]), after[2]) + "~"
                rows = []
                size = min(128, limit) if not agent_id and not states else 128
                while len(rows) < limit:
                    members = await pipe.zrangebylex(order_key, lower, "+", start=0, num=size)
                    for member in members:
                        row = _decode_metadata(member)
                        if (not agent_id or row.agent_id == agent_id) and (not states or row.state in states):
                            rows.append(row)
                            if len(rows) == limit:
                                break
                    if len(members) < size:
                        break
                    lower = "(" + members[-1]
                # Reject results if a Run commit or tombstone changed the
                # authorization or the index while a filter crossed batches.
                pipe.multi()
                pipe.hget(key, "revision")
                await pipe.execute()
                return tuple(rows)
            except WatchError:
                continue
    return None


def decode_redis_metadata(
    fields, *, project=project_metadata_state, apply=apply_metadata_delta
):
    state = project(json.loads(fields["base"]))
    revision = int(state["sessions"][0]["revision"])
    for next_revision, encoded in sorted(
        (int(key[2:]), value) for key, value in fields.items() if key.startswith("d:")
    ):
        if next_revision != revision + 1:
            raise ValueError("metadata Redis revision gap")
        state = apply(state, json.loads(encoded))
        revision = next_revision
        if int(state["sessions"][0]["revision"]) != revision:
            raise ValueError("metadata Redis revision mismatch")
    if revision != int(fields["revision"]) or int(
        state["sessions"][0]["last_sequence"]
    ) != int(fields["last_sequence"]):
        raise ValueError("metadata Redis head mismatch")
    return state


async def _read_redis_fields_batched(store, operations, *, raise_on_error=True):
    """Cap each Redis reply batch at 32 commands and 256 projected fields."""
    results = []
    for start in range(0, len(operations), 32):
        async with store._redis.pipeline(transaction=False) as pipe:
            for name, key, fields in operations[start : start + 32]:
                if name == "hget":
                    pipe.hget(key, fields)
                else:
                    pipe.hmget(key, fields)
            results.extend(await pipe.execute(raise_on_error=raise_on_error))
    return results


async def read_redis_metadata_batch(store, session_ids):
    """Batch the existing immutable-base protocol, including compaction checks."""
    import asyncio

    names = (
        "base_snapshot",
        "base_parts",
        "base_revision",
        "revision",
        "last_sequence",
        "deleted",
        "commit_id",
    )
    pending = list(session_ids)
    complete = {}
    for _ in range(5):
        if not pending:
            return complete
        heads = await _read_redis_fields_batched(
            store, [("hmget", store._session_key(sid), names) for sid in pending]
        )
        fields = {
            sid: {key: value for key, value in zip(names, values) if value is not None}
            for sid, values in zip(pending, heads)
        }
        operations, reads = [], []
        for sid, head in fields.items():
            if not head or head.get("deleted") == "1":
                continue
            if head.get("base_snapshot"):
                for start in range(0, int(head["base_parts"]), 8):
                    reads.append(
                        (
                            "hmget",
                            store._key("snapshot:" + head["base_snapshot"]),
                            [
                                str(i)
                                for i in range(
                                    start, min(start + 8, int(head["base_parts"]))
                                )
                            ],
                        )
                    )
                    operations.append((sid, "parts"))
            else:
                reads.append(("hget", store._session_key(sid), "base"))
                operations.append((sid, "base"))
        bases = await _read_redis_fields_batched(store, reads)
        fragments = {}
        for (sid, kind), result in zip(operations, bases):
            if kind == "parts":
                fragments.setdefault(sid, []).extend(result)
            else:
                fields[sid]["base"] = result
        for sid, parts in fragments.items():
            if all(part is not None for part in parts):
                fields[sid]["base"] = "".join(parts)
        deltas, reads = [], []
        for sid, head in fields.items():
            if not head or head.get("deleted") == "1" or not head.get("base"):
                continue
            if "base_revision" not in head:
                head["base_revision"] = str(
                    await asyncio.to_thread(
                        lambda: int(json.loads(head["base"])["sessions"][0]["revision"])
                    )
                )
            for start in range(
                int(head["base_revision"]) + 1, int(head["revision"]) + 1, 8
            ):
                keys = [
                    f"d:{i}"
                    for i in range(start, min(start + 8, int(head["revision"]) + 1))
                ]
                reads.append(("hmget", store._session_key(sid), keys))
                deltas.append((sid, keys))
        values = await _read_redis_fields_batched(store, reads)
        for (sid, keys), values in zip(deltas, values):
            fields[sid].update(zip(keys, values))
        current = await _read_redis_fields_batched(
            store,
            [
                (
                    "hmget",
                    store._session_key(sid),
                    ("base_snapshot", "base_revision", "deleted"),
                )
                for sid in pending
            ],
        )
        retry = []
        for index, (sid, head) in enumerate(zip(pending, current)):
            value = fields[sid]
            original_head = dict(zip(names, heads[index]))
            expected = [
                original_head.get(key)
                for key in ("base_snapshot", "base_revision", "deleted")
            ]
            if not value or value.get("deleted") == "1":
                complete[sid] = value
            elif (
                head == expected
                and value.get("base")
                and all(
                    item is not None
                    for key, item in value.items()
                    if key.startswith("d:")
                )
            ):
                complete[sid] = value
            else:
                retry.append(sid)
        pending = retry
    raise store._conflict(
        "session.revision_conflict", "Redis metadata base changed during loading"
    )

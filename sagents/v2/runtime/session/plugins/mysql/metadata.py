"""Backend metadata loading over the canonical Session projection."""

from sagents.v2.runtime.session.metadata_replay import (
    project_metadata_state,
    apply_metadata_delta,
)


def decode_redis_metadata(
    fields, *, project=project_metadata_state, apply=apply_metadata_delta
):
    import json

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


async def _read_redis_fields_batched(store, operations):
    """Cap each Redis reply batch at 32 commands and 256 projected fields."""
    results = []
    for start in range(0, len(operations), 32):
        async with store._redis.pipeline(transaction=False) as pipe:
            for name, key, fields in operations[start : start + 32]:
                if name == "hget":
                    pipe.hget(key, fields)
                else:
                    pipe.hmget(key, fields)
            results.extend(await pipe.execute())
    return results


async def read_redis_metadata_batch(store, session_ids):
    """Batch the existing immutable-base protocol, including compaction checks."""
    import asyncio
    import json

    names = (
        "base_snapshot",
        "base_parts",
        "base_revision",
        "revision",
        "last_sequence",
        "deleted",
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

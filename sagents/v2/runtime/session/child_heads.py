"""Direct child identities and first/latest Run metadata, without execution state."""

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from sagents.v2.runtime.session.state import SessionStoreCoordinator

from dataclasses import dataclass

from sagents.v2.runtime.session.run_metadata import RunMetadata


@dataclass(frozen=True)
class ChildSessionHeads:
    first: RunMetadata
    latest: RunMetadata


def child_heads(rows):
    grouped = {}
    for row in rows:
        pair = grouped.setdefault(row.session_id, [row, row])
        key = row.created_at, row.run_id
        if key < (pair[0].created_at, pair[0].run_id):
            pair[0] = row
        if key > (pair[1].created_at, pair[1].run_id):
            pair[1] = row
    result = [ChildSessionHeads(*pair) for pair in grouped.values()]
    result.sort(key=lambda head: (head.first.session_created_at or head.first.created_at, head.first.session_id))
    return tuple(result)


class ManagedSessionHeadQueries:
    async def _direct_child_ids_for_run(self, run_id):
        store = cast("SessionStoreCoordinator", self)
        async with store._lock:
            parent = store._runs.get(run_id)
            if parent is None:
                raise store._not_found('run.not_found', run_id)
            return [row.session_id for row in store._sessions.values() if row.parent_session_id == parent.session_id]

    async def managed_session_heads(self, run_id):
        store = cast("SessionStoreCoordinator", self)
        ids = await store._direct_child_ids_for_run(run_id)
        rows = []
        for offset in range(0, len(ids), 128):
            rows.extend(await store._run_metadata_rows(ids[offset:offset + 128]))
        return child_heads(rows)

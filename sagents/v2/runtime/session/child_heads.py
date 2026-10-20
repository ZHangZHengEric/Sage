"""Direct child identities and first/latest Run metadata, without execution state."""
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
        async with self._lock:
            parent = self._runs.get(run_id)
            if parent is None:
                raise self._not_found('run.not_found', run_id)
            return [row.session_id for row in self._sessions.values() if row.parent_session_id == parent.session_id]

    async def managed_session_heads(self, run_id):
        ids = await self._direct_child_ids_for_run(run_id)
        rows = []
        for offset in range(0, len(ids), 128):
            rows.extend(await self._run_metadata_rows(ids[offset:offset + 128]))
        return child_heads(rows)


class FilesystemManagedSessionHeads:
    async def _direct_child_ids_for_run(self, run_id):
        # The existing canonical topology index includes unloaded Sessions.
        async with self._lock:
            row = self._runs.get(run_id)
            sid = row.session_id if row else None
            live = {key: value.parent_session_id for key, value in self._sessions.items()}
        with self._index_lock:
            if sid is None:
                sid = next((key for key, value in self._session_index.items() if run_id in value['run_ids']), None)
            parents = {key: value.get('parent_session_id') for key, value in self._session_index.items()}
        if sid is None:
            raise self._not_found('run.not_found', run_id)
        parents.update(live)
        return [key for key, parent in parents.items() if parent == sid]


class PostgresManagedSessionHeads:
    async def _direct_child_ids_for_run(self, run_id):
        sid = await self._locate_session('run_id', run_id)
        if sid is None:
            raise self._not_found('run.not_found', run_id)
        async with self._pool.acquire() as connection:
            return [row[0] for row in await connection.fetch(
                f"SELECT session_id FROM {self._table('sessions')} WHERE parent_session_id = $1", sid)]


class RedisManagedSessionHeads:
    async def _direct_child_ids_for_run(self, run_id):
        await self._ensure_ready()
        sid = await self._locate_session('run_id', run_id)
        if sid is None or await self._redis.hget(self._session_key(sid), 'deleted') == '1':
            raise self._not_found('run.not_found', run_id)
        ids = set(await self._archive.list_direct_child_session_ids(sid))
        ids.update(child for child, parent in (await self._redis.hgetall(self._key('parents'))).items() if parent == sid)
        return sorted(ids)

    async def managed_session_heads(self, run_id):
        # Redis owns unarchived metadata; the MySQL implementation is not an
        # authoritative reader until those revisions have reached the archive.
        return await ManagedSessionHeadQueries.managed_session_heads(self, run_id)

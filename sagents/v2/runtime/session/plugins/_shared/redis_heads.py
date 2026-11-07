"""Direct child heads from authoritative Redis state and its SQL archive."""

from sagents.v2.runtime.session.child_heads import ManagedSessionHeadQueries


class RedisManagedSessionHeads:
    async def _visible_session_ids(self, session_ids):
        ids = tuple(sorted(set(session_ids)))
        visible = []
        for start in range(0, len(ids), 128):
            batch = ids[start : start + 128]
            async with self._redis.pipeline(transaction=False) as pipe:
                for sid in batch:
                    pipe.hget(self._session_key(sid), "deleted")
                deleted = await pipe.execute()
            visible.extend(sid for sid, marker in zip(batch, deleted) if marker != "1")
        return visible

    async def list_direct_child_session_ids(self, session_id):
        await self._ensure_ready()
        ids = set(await self._archive.list_direct_child_session_ids(session_id))
        ids.update(
            child
            for child, parent in (
                await self._redis.hgetall(self._key("parents"))
            ).items()
            if parent == session_id
        )
        return await self._visible_session_ids(ids)

    async def list_workspace_descendant_ids(self, session_ids):
        await self._ensure_ready()
        roots = set(session_ids)
        found = set()
        for sid in roots:
            found.update(await self._list_descendant_ids(sid))
        return await self._visible_session_ids(found - roots)

    async def has_nonterminal_sessions(self, session_ids):
        from sagents.v2.contracts.run_state import TERMINAL_RUN_STATES

        ids = tuple(dict.fromkeys(session_ids))
        for start in range(0, len(ids), 128):
            rows, _ = await self._run_metadata_batch(ids[start : start + 128])
            if any(row.state not in TERMINAL_RUN_STATES for row in rows):
                return True
        return False

    async def _direct_child_ids_for_run(self, run_id):
        store = self
        await store._ensure_ready()
        sid = await store._locate_session("run_id", run_id)
        if (
            sid is None
            or await store._redis.hget(store._session_key(sid), "deleted") == "1"
        ):
            raise store._not_found("run.not_found", run_id)
        return await store.list_direct_child_session_ids(sid)

    async def managed_session_heads(self, run_id):
        # Redis owns unarchived metadata; the SQL implementation is not an
        # authoritative reader until those revisions have reached the archive.
        store = self
        return await ManagedSessionHeadQueries.managed_session_heads(store, run_id)

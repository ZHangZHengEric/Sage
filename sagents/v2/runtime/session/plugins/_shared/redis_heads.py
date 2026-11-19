"""Direct child heads from authoritative Redis state and its SQL archive."""

from sagents.v2.runtime.session.child_heads import ManagedSessionHeadQueries


class RedisManagedSessionHeads:
    async def _migrate_child_edges(self):
        # Keep the reverse map authoritative and intact for rollback. Current
        # writers update both representations in the same Redis transaction.
        legacy = self._key("parents")
        order = self._key("child-edges:v2")
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.hlen(legacy)
            pipe.zcard(order)
            count, indexed = await pipe.execute()
        if count == indexed:
            return

        async def rebuild():
            async with self._redis.pipeline() as pipe:
                await pipe.watch(legacy)
                if await pipe.hlen(legacy) == await pipe.zcard(order):
                    return
                edges = list((await pipe.hgetall(legacy)).items())
                pipe.multi()
                pipe.delete(order)
                for offset in range(0, len(edges), 256):
                    pipe.zadd(order, {parent + "\0" + sid: 0 for sid, parent in edges[offset:offset + 256]})
                await pipe.execute()

        await self._retry_transaction(rebuild)

    async def _indexed_children(self, parents):
        order = self._key("child-edges:v2")
        result = set()
        ids = sorted(parents)
        for offset in range(0, len(ids), 32):
            async with self._redis.pipeline(transaction=False) as pipe:
                for parent in ids[offset:offset + 32]:
                    pipe.zrangebylex(order, "[" + parent + "\0", "(" + parent + "\x01")
                for values in await pipe.execute():
                    result.update(value.partition("\0")[2] for value in values)
        return result

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
        await self._migrate_child_edges()
        ids = set(await self._archive.list_direct_child_session_ids(session_id))
        ids.update(await self._indexed_children({session_id}))
        return await self._visible_session_ids(ids)

    async def list_workspace_descendant_ids(self, session_ids):
        roots = set(session_ids)
        return await self._visible_session_ids(await self._collect_session_tree(roots) - roots)

    async def _collect_session_tree(self, roots):
        await self._ensure_ready()
        await self._migrate_child_edges()
        found = set(roots)
        frontier = set(roots)
        while frontier:
            # Expand in both stores, including Redis children of archived
            # descendants and archived children of Redis-only descendants.
            archived = set(await self._archive.list_workspace_descendant_ids(sorted(frontier)))
            children = await self._indexed_children(frontier | (archived - found))
            frontier = children - found - archived
            found.update(archived | children)
        return found

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

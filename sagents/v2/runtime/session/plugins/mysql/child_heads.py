"""Direct-child context heads projected in SQL from compact state/journals."""

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from sagents.v2.runtime.session.plugins.mysql._redis_persistence import _RedisMysqlPersistence
    from sagents.v2.runtime.session.plugins.mysql.state import _MysqlSessionState

from sagents.v2.runtime.session.child_heads import ManagedSessionHeadQueries, child_heads
from .run_metadata import mysql_metadata_cte, decode_metadata


class RedisManagedSessionHeads:
    async def _direct_child_ids_for_run(self, run_id):
        store = cast("_RedisMysqlPersistence", self)
        await store._ensure_ready()
        sid = await store._locate_session('run_id', run_id)
        if sid is None or await store._redis.hget(store._session_key(sid), 'deleted') == '1':
            raise store._not_found('run.not_found', run_id)
        ids = set(await store._archive.list_direct_child_session_ids(sid))
        ids.update(child for child, parent in (await store._redis.hgetall(store._key('parents'))).items() if parent == sid)
        return sorted(ids)

    async def managed_session_heads(self, run_id):
        # Redis owns unarchived metadata; the MySQL implementation is not an
        # authoritative reader until those revisions have reached the archive.
        store = cast("_RedisMysqlPersistence", self)
        return await ManagedSessionHeadQueries.managed_session_heads(store, run_id)



class MysqlManagedSessionHeads:
    async def list_direct_child_session_ids(self, session_id):
        store = cast("_MysqlSessionState", self)
        async with store._reader_connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(f"SELECT session_id FROM {store._table('sessions')} WHERE parent_session_id = %s", (session_id,))
                return [row[0] for row in await cursor.fetchall()]

    async def managed_session_heads(self, run_id):
        store = cast("_MysqlSessionState", self)
        await store._ensure_ready()
        sid = await store._locate_session('run_id', run_id)
        if sid is None:
            raise store._not_found('run.not_found', run_id)
        direct = f"WITH direct_children AS (SELECT session_id FROM {store._table('sessions')} WHERE parent_session_id = %s), "
        query = direct + mysql_metadata_cte(store._table, 'SELECT session_id FROM direct_children').removeprefix('WITH ')
        query += """, ranked AS (
            SELECT metadata.*,
              ROW_NUMBER() OVER (PARTITION BY session_id ORDER BY created_at,run_id) first_position,
              ROW_NUMBER() OVER (PARTITION BY session_id ORDER BY created_at DESC,run_id DESC) latest_position
            FROM metadata
        ) SELECT session_id,run_id,created_at,state,agent_id,invocation_mode,task_name,
                 admitted_agent_id,session_created_at,parent_session_id
          FROM ranked WHERE first_position = 1 OR latest_position = 1"""
        async with store._reader_connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(query, (sid,))
                rows = tuple(decode_metadata(row) for row in await cursor.fetchall())
        return child_heads(rows)

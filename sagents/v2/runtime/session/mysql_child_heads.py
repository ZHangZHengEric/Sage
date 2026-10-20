"""Direct-child context heads projected in SQL from compact state/journals."""
from sagents.v2.runtime.session.child_heads import child_heads
from sagents.v2.runtime.session.mysql_run_metadata import mysql_metadata_cte, decode_metadata


class MysqlManagedSessionHeads:
    async def list_direct_child_session_ids(self, session_id):
        async with self._reader_connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(f"SELECT session_id FROM {self._table('sessions')} WHERE parent_session_id = %s", (session_id,))
                return [row[0] for row in await cursor.fetchall()]

    async def managed_session_heads(self, run_id):
        await self._ensure_ready()
        sid = await self._locate_session('run_id', run_id)
        if sid is None:
            raise self._not_found('run.not_found', run_id)
        direct = f"WITH direct_children AS (SELECT session_id FROM {self._table('sessions')} WHERE parent_session_id = %s), "
        query = direct + mysql_metadata_cte(self._table, 'SELECT session_id FROM direct_children').removeprefix('WITH ')
        query += """, ranked AS (
            SELECT metadata.*,
              ROW_NUMBER() OVER (PARTITION BY session_id ORDER BY created_at,run_id) first_position,
              ROW_NUMBER() OVER (PARTITION BY session_id ORDER BY created_at DESC,run_id DESC) latest_position
            FROM metadata
        ) SELECT session_id,run_id,created_at,state,agent_id,invocation_mode,task_name,
                 admitted_agent_id,session_created_at,parent_session_id
          FROM ranked WHERE first_position = 1 OR latest_position = 1"""
        async with self._reader_connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(query, (sid,))
                rows = tuple(decode_metadata(row) for row in await cursor.fetchall())
        return child_heads(rows)

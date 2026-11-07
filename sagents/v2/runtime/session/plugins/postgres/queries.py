"""Trusted topology and lifecycle probes, plus PostgreSQL read projections."""

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.run_state import TERMINAL_RUN_STATES
from sagents.v2.runtime.session.child_heads import child_heads
from .metadata import PostgresRunMetadataQueries, postgres_metadata_cte, decode_metadata
from .read_views import PostgresSessionReadQueries
from .history import PostgresHistoryQueries


class PostgresSessionQueries(
    PostgresRunMetadataQueries, PostgresSessionReadQueries, PostgresHistoryQueries
):
    async def list_direct_child_session_ids(self, session_id):
        async with self._reader_connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    f"SELECT session_id FROM {self._table('sessions')} WHERE parent_session_id = %s",
                    (session_id,),
                )
                return [row[0] for row in await cursor.fetchall()]

    async def list_workspace_descendant_ids(self, session_ids):
        ids = tuple(dict.fromkeys(session_ids))
        found = set()
        for offset in range(0, len(ids), 128):
            batch = ids[offset : offset + 128]
            marks = ",".join(["%s"] * len(batch))
            async with self._reader_connection() as connection:
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        f"""WITH RECURSIVE tree AS (
                        SELECT session_id FROM {self._table("sessions")} WHERE parent_session_id IN ({marks})
                        UNION
                        SELECT child.session_id FROM {self._table("sessions")} child
                        JOIN tree parent ON child.parent_session_id = parent.session_id
                    ) SELECT session_id FROM tree""",
                        batch,
                    )
                    found.update(row[0] for row in await cursor.fetchall())
        return sorted(found - set(ids))

    async def _state_probe(self, session_ids, *, states=None):
        ids = tuple(dict.fromkeys(session_ids))
        selected = set()
        for offset in range(0, len(ids), 128):
            batch = ids[offset : offset + 128]
            marks = ",".join(["%s"] * len(batch))
            if states is None:
                clause = (
                    "m.state NOT IN ("
                    + ",".join(["%s"] * len(TERMINAL_RUN_STATES))
                    + ")"
                )
                values = tuple(state.value for state in TERMINAL_RUN_STATES)
            else:
                clause = "m.state IN (" + ",".join(["%s"] * len(states)) + ")"
                values = tuple(states)
            # The durable location roster is authoritative even when an old or
            # corrupt JSON snapshot has lost its Run row. Missing state must
            # block workspace deletion, just as the MySQL lifecycle probe does.
            query = (
                postgres_metadata_cte(self._table, marks)
                + f"""
                SELECT l.session_id, bool_or(m.state IS NULL), bool_or({clause})
                FROM {self._table("locations")} l
                LEFT JOIN metadata m ON m.session_id = l.session_id AND m.run_id = l.identity
                WHERE l.kind = 'run_id' AND l.session_id IN ({marks})
                GROUP BY l.session_id
            """
            )
            async with self._reader_connection() as connection:
                async with connection.cursor() as cursor:
                    await cursor.execute(query, batch * 4 + values + batch)
                    for sid, incomplete, matches in await cursor.fetchall():
                        if incomplete:
                            raise SageV2Error(
                                RuntimeErrorInfo(
                                    code="session_store.workspace_state_missing",
                                    category=ErrorCategory.RESOURCE_LOST,
                                    message="Workspace Run state is missing",
                                    safe_to_resume=False,
                                )
                            )
                        if matches:
                            selected.add(sid)
        return selected

    async def has_nonterminal_session_trees(self, session_ids):
        ids = tuple(session_ids)
        descendants = await self.list_workspace_descendant_ids(ids)
        return bool(await self._state_probe((*ids, *descendants)))

    async def has_nonterminal_sessions(self, session_ids):
        return bool(await self._state_probe(session_ids))

    async def filter_suspended_session_ids(self, session_ids):
        return await self._state_probe(session_ids, states=("suspended",))

    async def managed_session_heads(self, run_id):
        await self._ensure_ready()
        sid = await self._locate_session("run_id", run_id)
        if sid is None:
            raise self._not_found("run.not_found", run_id)
        query = f"WITH direct_children AS (SELECT session_id FROM {self._table('sessions')} WHERE parent_session_id = %s), "
        query += postgres_metadata_cte(
            self._table, "SELECT session_id FROM direct_children"
        ).removeprefix("WITH ")
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
                return child_heads(
                    tuple(decode_metadata(row) for row in await cursor.fetchall())
                )

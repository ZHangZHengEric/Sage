"""Trusted workspace lifecycle probes over existing Session snapshots/journals."""
from __future__ import annotations


class MysqlWorkspaceQueries:
    async def list_workspace_descendant_ids(self, session_ids):
        """Resolve a page of trusted roots with indexed recursive metadata SQL."""
        ids = tuple(dict.fromkeys(session_ids))
        found = set()
        for offset in range(0, len(ids), 128):
            batch = ids[offset:offset + 128]
            marks = ','.join(['%s'] * len(batch))
            async with self._reader_connection() as connection:
                async with connection.cursor() as cursor:
                    await cursor.execute(f"""
                        WITH RECURSIVE tree AS (
                            SELECT session_id FROM {self._table('sessions')}
                            WHERE parent_session_id IN ({marks})
                            UNION DISTINCT
                            SELECT child.session_id FROM {self._table('sessions')} child
                            JOIN tree parent ON child.parent_session_id = parent.session_id
                        ) SELECT session_id FROM tree
                    """, batch)
                    found.update(row[0] for row in await cursor.fetchall())
        return sorted(found - set(ids))

    async def has_nonterminal_session_trees(self, session_ids):
        """Host-only boolean probe; callers supply verified ownership roots.

        No execution aggregate or canonical event payload is installed. The
        latest journal state, including Run deletions, supersedes compact state.
        """
        return await self._has_nonterminal_sessions(session_ids, include_descendants=True)

    async def has_nonterminal_sessions(self, session_ids):
        """Archive-only exact-ID probe after Redis resolved authoritative topology."""
        return await self._has_nonterminal_sessions(session_ids, include_descendants=False)

    async def _has_nonterminal_sessions(self, session_ids, *, include_descendants):
        ids = tuple(dict.fromkeys(session_ids))
        for offset in range(0, len(ids), 128):
            batch = ids[offset:offset + 128]
            marks = ','.join(['%s'] * len(batch))
            descendants = f"""
                    UNION DISTINCT
                    SELECT child.session_id FROM {self._table('sessions')} child
                    JOIN tree parent ON child.parent_session_id = parent.session_id
            """ if include_descendants else ""
            statement = f"""
                WITH RECURSIVE tree AS (
                    SELECT session_id FROM {self._table('sessions')} WHERE session_id IN ({marks})
                    {descendants}
                ), states AS (
                    SELECT s.session_id, r.run_id, r.state,
                        CAST(JSON_UNQUOTE(JSON_EXTRACT(s.compact_state, '$.sessions[0].revision')) AS UNSIGNED) revision
                    FROM {self._table('sessions')} s JOIN tree ON tree.session_id = s.session_id,
                        JSON_TABLE(s.compact_state, '$.runs[*]' COLUMNS (
                            run_id VARCHAR(128) PATH '$.run_id', state VARCHAR(32) PATH '$.state')) r
                    UNION ALL
                    SELECT m.session_id, r.run_id, r.state, m.revision
                    FROM {self._table('session_mutations')} m JOIN tree ON tree.session_id = m.session_id,
                        JSON_TABLE(m.mutation, '$.upserts.runs[*]' COLUMNS (
                            run_id VARCHAR(128) PATH '$.run_id', state VARCHAR(32) PATH '$.state')) r
                    UNION ALL
                    SELECT m.session_id, r.run_id, r.state, m.revision
                    FROM {self._table('session_mutations')} m JOIN tree ON tree.session_id = m.session_id,
                        JSON_TABLE(m.mutation, '$.patches.runs[*]' COLUMNS (
                            run_id VARCHAR(128) PATH '$.run_id', state VARCHAR(32) PATH '$.state')) r
                    WHERE r.state IS NOT NULL
                    UNION ALL
                    SELECT m.session_id, r.run_id, '__deleted__', m.revision
                    FROM {self._table('session_mutations')} m JOIN tree ON tree.session_id = m.session_id,
                        JSON_TABLE(m.mutation, '$.deletes.runs[*]' COLUMNS (
                            run_id VARCHAR(128) PATH '$[0]')) r
                ), latest AS (
                    SELECT state, ROW_NUMBER() OVER (
                        PARTITION BY session_id, run_id ORDER BY revision DESC) position
                    FROM states
                ) SELECT 1 FROM latest WHERE position = 1
                    AND state NOT IN ('completed', 'failed', 'cancelled', '__deleted__') LIMIT 1
            """
            async with self._reader_connection() as connection:
                async with connection.cursor() as cursor:
                    await cursor.execute(statement, batch)
                    if await cursor.fetchone() is not None:
                        return True
        return False

"""Trusted workspace lifecycle probes over revision-checked Run projections."""
from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from sagents.v2.runtime.session.plugins.mysql.state import _MysqlSessionState



class MysqlWorkspaceQueries:
    async def list_workspace_descendant_ids(self, session_ids):
        """Resolve a page of trusted roots with indexed recursive metadata SQL."""
        store = cast("_MysqlSessionState", self)
        ids = tuple(dict.fromkeys(session_ids))
        found = set()
        for offset in range(0, len(ids), 128):
            batch = ids[offset:offset + 128]
            marks = ','.join(['%s'] * len(batch))
            async with store._reader_connection() as connection:
                async with connection.cursor() as cursor:
                    await cursor.execute(f"""
                        WITH RECURSIVE tree AS (
                            SELECT session_id FROM {store._table('sessions')}
                            WHERE parent_session_id IN ({marks})
                            UNION DISTINCT
                            SELECT child.session_id FROM {store._table('sessions')} child
                            JOIN tree parent ON child.parent_session_id = parent.session_id
                        ) SELECT session_id FROM tree
                    """, batch)
                    found.update(row[0] for row in await cursor.fetchall())
        return sorted(found - set(ids))

    async def has_nonterminal_session_trees(self, session_ids):
        """Host-only boolean probe; callers supply verified ownership roots.

        No execution aggregate or event payload is installed. A revision-checked
        projection is used first; legacy state is recovered from the journal.
        """
        store = cast("_MysqlSessionState", self)
        return await store._has_nonterminal_sessions(session_ids, include_descendants=True)

    async def has_nonterminal_sessions(self, session_ids):
        """Archive-only exact-ID probe after Redis resolved authoritative topology."""
        store = cast("_MysqlSessionState", self)
        return await store._has_nonterminal_sessions(session_ids, include_descendants=False)

    async def _has_nonterminal_sessions(self, session_ids, *, include_descendants):
        from .workspace_probe import has_nonterminal_sessions
        return await has_nonterminal_sessions(self, session_ids, include_descendants=include_descendants)

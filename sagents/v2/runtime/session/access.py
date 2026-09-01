"""Tenant-aware Session query surface for server and protocol adapters.

The low-level SessionStore remains an internal persistence port so Agent and
recovery code can navigate durable relationships without manufacturing user
credentials.  External transports should use this service instead: every
operation authenticates the durable Session owner before returning data or
performing deletion.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sagents.v2.contracts.principals import RequestContext
from sagents.v2.contracts.run_state import EventCursor
from sagents.v2.runtime.session.contracts import SessionStore


class AuthorizedSessionAccess:
    """Context-bearing read/delete facade over an internal SessionStore."""

    def __init__(self, session_store: SessionStore, *, runtime=None) -> None:
        self._session_store = session_store
        self.runtime = runtime

    async def get_run(self, run_id: str, context: RequestContext):
        run = await self._session_store.get_run(run_id)
        await self._authorize(run.session_id, context)
        return run

    async def get_run_result(self, run_id: str, context: RequestContext):
        run = await self._session_store.get_run(run_id)
        await self._authorize(run.session_id, context)
        return await self._session_store.get_run_result(run_id)

    async def get_session(self, session_id: str, context: RequestContext):
        await self._authorize(session_id, context)
        return await self._session_store.get_session(session_id)

    async def get_start_command(self, run_id: str, context: RequestContext):
        run = await self._session_store.get_run(run_id)
        await self._authorize(run.session_id, context)
        return await self._session_store.get_start_command(run_id)

    async def get_checkpoint(self, checkpoint_id: str, context: RequestContext):
        checkpoint = await self._session_store.get_checkpoint(checkpoint_id)
        await self._authorize(checkpoint.session_id, context)
        return checkpoint

    async def get_suspension(self, suspension_id: str, context: RequestContext):
        suspension = await self._session_store.get_suspension(suspension_id)
        run = await self._session_store.get_run(suspension.run_id)
        await self._authorize(run.session_id, context)
        return suspension

    async def get_interaction(self, interaction_id: str, context: RequestContext):
        interaction = await self._session_store.get_interaction(interaction_id)
        run = await self._session_store.get_run(interaction.run_id)
        await self._authorize(run.session_id, context)
        return interaction

    async def get_interaction_resolution(
        self, interaction_id: str, context: RequestContext
    ):
        interaction = await self.get_interaction(interaction_id, context)
        return await self._session_store.get_interaction_resolution(
            interaction.interaction_id
        )

    async def list_descendant_sessions(
        self, session_id: str, context: RequestContext
    ):
        await self._authorize(session_id, context)
        return await self._session_store.list_descendant_sessions(session_id)

    async def list_session_runs(self, session_id: str, context: RequestContext):
        await self._authorize(session_id, context)
        return await self._session_store.list_session_runs(session_id)

    async def read_events(
        self,
        run_id: str,
        context: RequestContext,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ):
        run = await self._session_store.get_run(run_id)
        await self._authorize(run.session_id, context)
        return await self._session_store.read_events(
            run_id, after_sequence=after_sequence, limit=limit
        )

    async def read_session_events(
        self,
        session_id: str,
        context: RequestContext,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ):
        await self._authorize(session_id, context)
        return await self._session_store.read_session_events(
            session_id, after_sequence=after_sequence, limit=limit
        )

    async def subscribe_events(
        self, cursor: EventCursor, context: RequestContext
    ) -> AsyncIterator:
        run = await self._session_store.get_run(cursor.run_id)
        await self._authorize(run.session_id, context)
        async for event in self._session_store.subscribe_events(cursor):
            yield event

    async def subscribe_session_tree(
        self,
        session_id: str,
        context: RequestContext,
        *,
        cursors: dict[str, int] | None = None,
        include_root: bool = True,
    ) -> AsyncIterator:
        await self._authorize(session_id, context)
        if self.runtime is None:
            raise TypeError("session-tree subscription requires a RuntimePort")
        async for event in self.runtime.subscribe_session_tree(
            session_id,
            cursors=cursors,
            include_root=include_root,
        ):
            yield event

    async def delete_session(
        self, session_id: str, context: RequestContext
    ) -> None:
        await self._authorize(session_id, context)
        await self._session_store.delete_session(session_id)

    async def _authorize(self, session_id: str, context: RequestContext) -> None:
        authorize = getattr(self._session_store, "authorize_session_actor", None)
        if not callable(authorize):
            raise TypeError(
                "the SessionStore plugin does not implement durable actor authorization"
            )
        await authorize(session_id, context)

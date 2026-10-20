"""Tenant-aware Session query surface for server and protocol adapters.

The low-level SessionStore remains an internal persistence port so Agent and
recovery code can navigate durable relationships without manufacturing user
credentials.  External transports should use this service instead: every
operation authenticates the durable Session owner before returning data or
performing deletion.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from typing import Protocol

from sagents.v2.contracts.principals import RequestContext
from sagents.v2.contracts.run_state import EventCursor
from sagents.v2.runtime.session.contracts import DerivedStateStore, SessionStore, SessionEventPage
from sagents.v2.runtime.observability.logs import get_logger


LOGGER = get_logger(__name__)


class SessionStateCleaner(Protocol):
    """Best-effort cleanup hook for state derived from a Session."""

    async def forget_session(self, session_id: str) -> None: ...


class AuthorizedSessionAccess:
    """Context-bearing read/delete facade over an internal SessionStore."""

    def __init__(
        self,
        session_store: SessionStore,
        *,
        runtime=None,
        derived_state: DerivedStateStore | None = None,
        derived_state_cleaners: Iterable[SessionStateCleaner] = (),
    ) -> None:
        self._session_store = session_store
        self.runtime = runtime
        cleaners = () if derived_state is None else (derived_state,)
        cleaners = (*cleaners, *derived_state_cleaners)
        self._derived_state_cleaners = tuple(
            cleaner
            for index, cleaner in enumerate(cleaners)
            if all(cleaner is not previous for previous in cleaners[:index])
        )

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

    async def find_start_run(self, session_id: str, idempotency_key: str, context: RequestContext):
        return await self._session_store.find_start_run(session_id, idempotency_key, context)

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

    async def list_descendant_sessions(self, session_id: str, context: RequestContext):
        await self._authorize(session_id, context)
        return await self._session_store.list_descendant_sessions(session_id)

    async def list_session_runs(self, session_id: str, context: RequestContext):
        await self._authorize(session_id, context)
        return await self._session_store.list_session_runs(session_id)

    async def read_session_views(self, session_contexts, *, skip_inaccessible=False, **options):
        """Read bounded list projections and check every durable owner in memory."""
        from sagents.v2.contracts.errors import ErrorCategory, SageV2Error
        from sagents.v2.runtime.session.state import SessionStoreCoordinator
        views = await self._session_store.read_session_views(tuple(session_contexts), **options)
        result = {}
        for sid, view in views.items():
            try:
                SessionStoreCoordinator._authorize_session_owner(view.owner, session_contexts[sid])
            except SageV2Error as exc:
                if skip_inaccessible and exc.info.category == ErrorCategory.AUTHORIZATION:
                    continue
                raise
            result[sid] = view.runs
        return result

    async def run_metadata_page(self, session_ids, context, **options):
        return await self._session_store.authorized_run_metadata_page(session_ids, context, **options)

    async def list_session_commit_proposals(
        self, session_id: str, context: RequestContext
    ):
        await self._authorize(session_id, context)
        return await self._session_store.list_session_commit_proposals(session_id)

    async def get_session_commit_proposal(
        self, proposal_id: str, context: RequestContext
    ):
        proposal = await self._session_store.get_session_commit_proposal(proposal_id)
        await self._authorize(proposal.session_id, context)
        return proposal

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

    async def read_session_event_page(self, session_id, context, *, after_sequence=None, limit=500):
        if not 1 <= limit <= 2000 or (after_sequence is not None and after_sequence < 0):
            raise ValueError("invalid Session event page")
        query = getattr(self._session_store, "read_authorized_session_page", None)
        if callable(query):
            return await query(session_id, context, after_sequence=after_sequence, limit=limit)
        session = await self.get_session(session_id, context)
        start = max(0, session.last_sequence - limit) if after_sequence is None else after_sequence
        events = await self.read_session_events(session_id, context, after_sequence=start, limit=limit)
        return SessionEventPage(tuple(events), session.last_sequence, start)

    async def latest_session_start_command(self, session_id, context):
        query = getattr(self._session_store, "latest_authorized_session_command", None)
        if callable(query):
            return await query(session_id, context)
        runs = await self.list_session_runs(session_id, context)
        return await self.get_start_command(runs[-1].run_id, context) if runs else None

    async def read_stream_previews(self, run_id: str, context: RequestContext):
        run = await self._session_store.get_run(run_id)
        await self._authorize(run.session_id, context)
        return await self._session_store.read_stream_previews(run_id)

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

    async def delete_session(self, session_id: str, context: RequestContext) -> None:
        await self._authorize(session_id, context)
        descendants = await self._session_store.list_descendant_sessions(session_id)
        deleted_session_ids = (session_id, *(value.session_id for value in descendants))
        await self._session_store.delete_session(session_id)
        for deleted_session_id in deleted_session_ids:
            for cleaner in self._derived_state_cleaners:
                try:
                    await cleaner.forget_session(deleted_session_id)
                except Exception as exc:
                    # Canonical deletion is already committed. Derived cleanup must
                    # never turn that acknowledged fact into a client-visible failure.
                    LOGGER.exception(
                        "session.derived_cleanup.failed",
                        "failed to clean derived state for deleted Session",
                        exc,
                        cleaner=type(cleaner).__name__,
                        session_id=deleted_session_id,
                    )

    async def _authorize(self, session_id: str, context: RequestContext) -> None:
        authorize = getattr(self._session_store, "authorize_session_actor", None)
        if not callable(authorize):
            raise TypeError(
                "the SessionStore plugin does not implement durable actor authorization"
            )
        await authorize(session_id, context)

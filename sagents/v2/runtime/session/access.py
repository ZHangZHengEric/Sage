"""Tenant-aware Session query surface for server and protocol adapters.

The low-level SessionStore remains an internal persistence port so Agent and
recovery code can navigate durable relationships without manufacturing user
credentials.  External transports should use this service instead: every
operation authenticates the durable Session owner before returning data or
performing deletion.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable, Callable, Awaitable
from typing import Protocol, cast

from sagents.v2.contracts.commands import StartRun
from sagents.v2.contracts.principals import RequestContext
from sagents.v2.contracts.run_state import EventCursor
from sagents.v2.runtime.session.contracts import (
    DerivedStateStore, SessionEventPage, SessionHistoryMetadata, SessionStore,
)
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

    async def authorize_session(self, session_id: str, context: RequestContext) -> None:
        await self._authorize(session_id, context)

    async def get_session(self, session_id: str, context: RequestContext):
        await self._authorize(session_id, context)
        return await self._session_store.get_session(session_id)

    async def get_start_command(self, run_id: str, context: RequestContext):
        run = await self._session_store.get_run(run_id)
        await self._authorize(run.session_id, context)
        return await self._session_store.get_start_command(run_id)

    async def find_start_run(self, session_id: str, idempotency_key: str, context: RequestContext):
        return await self._session_store.find_start_run(session_id, idempotency_key, context)

    async def supersede_suspended_run(self, command: StartRun, context: RequestContext) -> None:
        """Let fresh user input replace a suspended serial Run, never a running one."""
        from sagents.v2.contracts.commands import CancelRun
        from sagents.v2.contracts.errors import SageV2Error
        from sagents.v2.contracts.run_state import RunState, SessionConcurrencyMode

        # Explicit revision callers retain the store's strict snapshot/CAS
        # contract; ordinary chat messages target the latest Session revision.
        if (not command.session_id or command.parent_run_id
                or command.base_session_revision is not None
                or command.session_concurrency_mode != SessionConcurrencyMode.SERIAL
                or not any(item.role == "user" for item in command.input)):
            return
        # Replaying an admitted request must never cancel that request's Run.
        if await self.find_start_run(command.session_id, command.idempotency_key, context):
            return
        try:
            session = await self.get_session(command.session_id, context)
        except SageV2Error as exc:
            if exc.info.code in {"session.not_found", "session_not_found"}:
                return
            raise
        if not session.active_serial_run_id:
            return
        run = await self.get_run(session.active_serial_run_id, context)
        if run.state != RunState.SUSPENDED:
            return
        receipt = await self.runtime.cancel_run(
            CancelRun(
                run_id=run.run_id,
                expected_revision=run.revision,
                idempotency_key=f"supersede:{run.run_id}:{run.revision}",
                reason="superseded_by_user_message",
            ), context,
        )
        if receipt.error is not None:
            raise SageV2Error(receipt.error)

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
        query = getattr(self._session_store, "read_authorized_session_events", None)
        if callable(query):
            return await query(session_id, context, after_sequence=after_sequence, limit=limit)
        await self._authorize(session_id, context)
        return await self._session_store.read_session_events(
            session_id, after_sequence=after_sequence, limit=limit
        )

    async def read_session_event_page(
        self, session_id, context, *, after_sequence=None, before_sequence=None, limit=500,
    ) -> SessionEventPage:
        if (
            not 1 <= limit <= 2000
            or (after_sequence is not None and after_sequence < 0)
            or (before_sequence is not None and before_sequence < 1)
            or (before_sequence is not None and after_sequence is not None)
        ):
            raise ValueError("invalid Session event page")
        backward = getattr(self._session_store, "read_authorized_session_page_before", None)
        if before_sequence is not None and callable(backward):
            return await backward(session_id, context, before_sequence=before_sequence, limit=limit)
        query = getattr(self._session_store, "read_authorized_session_page", None)
        if before_sequence is None and callable(query):
            return await cast(Callable[..., Awaitable[SessionEventPage]], query)(
                session_id, context, after_sequence=after_sequence, limit=limit
            )
        session = await self.get_session(session_id, context)
        end = min(session.last_sequence, before_sequence - 1) if before_sequence else session.last_sequence
        start = max(0, end - limit) if after_sequence is None else after_sequence
        events = await self.read_session_events(session_id, context, after_sequence=start, limit=limit)
        if before_sequence is not None:
            events = tuple(event for event in events if (event.session_sequence or 0) < before_sequence)
        return SessionEventPage(tuple(events), session.last_sequence, start)

    async def read_session_history_metadata(self, session_id, context) -> SessionHistoryMetadata:
        query = getattr(self._session_store, "read_authorized_history_metadata", None)
        if callable(query):
            return await query(session_id, context)
        session = await self.get_session(session_id, context)
        runs = await self.list_session_runs(session_id, context)
        from sagents.v2.contracts.errors import ErrorCategory, SageV2Error

        children = []
        for child in await self.list_descendant_sessions(session_id, context):
            if child.parent_session_id != session_id:
                continue
            try:
                await self._authorize(child.session_id, context)
            except SageV2Error as exc:
                if exc.info.category != ErrorCategory.AUTHORIZATION:
                    raise
            else:
                children.append(child.session_id)
        return SessionHistoryMetadata(session, runs[-1] if runs else None, tuple(children))

    async def read_session_tool_activity(
        self, session_ids, context, *, tool_name=None, path=None, state=None, limit=100,
    ):
        """Search authorized Sessions supplied by the caller, in input order."""
        ids = tuple(dict.fromkeys(session_ids))
        if not 1 <= limit <= 1000 or len(ids) > 256:
            raise ValueError("invalid Session activity query")
        query = getattr(self._session_store, "read_authorized_tool_activity", None)
        if not callable(query):
            raise NotImplementedError("SessionStore does not support tool activity queries")
        return await query(ids, context, tool_name=tool_name, path=path, state=state, limit=limit)

    async def latest_session_start_command(self, session_id, context):
        query = getattr(self._session_store, "latest_authorized_session_command", None)
        if callable(query):
            return await cast(Callable[..., Awaitable[StartRun | None]], query)(session_id, context)
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
        events = self._session_store.subscribe_events(cursor)
        try:
            async for event in events:
                yield event
        finally:
            close = getattr(events, "aclose", None)
            if close is not None:
                await close()

    async def durable_event_reader(self, run_id: str, context: RequestContext):
        run = await self._session_store.get_run(run_id)
        await self._authorize(run.session_id, context)
        indexed = getattr(self._session_store, "read_indexed_run_events", None)

        async def read(*, after_sequence: int, limit: int):
            if callable(indexed):
                return await indexed(run_id, run.session_id, after_sequence=after_sequence, limit=limit)
            return await self._session_store.read_events(run_id, after_sequence=after_sequence, limit=limit)

        return read

    async def subscribe_durable_events(self, cursor: EventCursor, context: RequestContext) -> AsyncIterator:
        native = getattr(self._session_store, "subscribe_durable_events", None)
        if callable(native):
            run = await self._session_store.get_run(cursor.run_id)
            await self._authorize(run.session_id, context)
            events = native(cursor, run.session_id)
        else:
            events = self.subscribe_events(cursor, context)
        try:
            async for event in events:
                if event.preview_sequence is None:
                    yield event
        finally:
            await events.aclose()

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
        events = self.runtime.subscribe_session_tree(
            session_id, cursors=cursors, include_root=include_root,
        )
        try:
            async for event in events:
                yield event
        finally:
            close = getattr(events, "aclose", None)
            if close is not None:
                await close()

    async def delete_session(self, session_id: str, context: RequestContext, *,
                             require_derived_cleanup: bool = False) -> None:
        await self._authorize(session_id, context)
        descendant_ids = getattr(self._session_store, "list_workspace_descendant_ids", None)
        if callable(descendant_ids):
            deleted_session_ids = (session_id, *await descendant_ids((session_id,)))
        else:
            descendants = await self._session_store.list_descendant_sessions(session_id)
            deleted_session_ids = (session_id, *(value.session_id for value in descendants))
        if require_derived_cleanup:
            # Keep the canonical tree discoverable until every external
            # cleaner succeeds so an interrupted purge can retry all children.
            for deleted_session_id in deleted_session_ids:
                for cleaner in self._derived_state_cleaners:
                    await cleaner.forget_session(deleted_session_id)
            await self._session_store.delete_session(session_id)
            return
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
        await self._session_store.authorize_session_actor(session_id, context)

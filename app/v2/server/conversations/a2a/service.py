from __future__ import annotations

import base64
import json
from datetime import datetime
from collections.abc import AsyncIterator
from dataclasses import dataclass
from sagents.v2.contracts.common import utc_now

from a2a.server.events.event_queue import Event
from a2a.types.a2a_pb2 import AgentCard, Message, Task, TaskState
from google.protobuf.struct_pb2 import Struct

from app.v2.server.catalog.records import AgentRecord, require_agent
from app.v2.server.conversations.a2a.card import agent_card
from app.v2.server.conversations.a2a.mapping import context_id, to_start_run
from app.v2.server.conversations.a2a.stream import task_stream
from app.v2.server.conversations.a2a.task import TaskReducer
from app.v2.server.identity.keys import (
    SCOPE_INVOKE,
    SCOPE_READ,
    SCOPE_APPROVE,
    ApiKeyRecord,
    require_scope,
)
from app.v2.server.observability.context import get_request_id
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.run_state import (
    TERMINAL_RUN_STATES,
    EventCursor,
    RunState,
)
from sagents.v2.interfaces.protocols.a2a import A2AProtocolAdapter
from sagents.v2.contracts.principals import RequestContext
from sagents.v2.runtime.session import AuthorizedSessionAccess
from sagents.v2.tool.plugins.a2a import CALL_DEPTH_KEY, MAX_CALL_DEPTH

# A2A caps a page at what a caller asked for; these bound what the walk over a
# tenant's threads is allowed to cost when the caller does not say.
_DEFAULT_PAGE = 50
_MAX_PAGE = 100

_TERMINAL_EVENTS = frozenset(
    {"run.completed", "run.failed", "run.cancelled", "run.suspended"}
)

# A Run that is waiting on an interaction is reported as input-required, which
# is A2A's own non-terminal resting state, not as a failure.
_TASK_STATE = {
    RunState.QUEUED: TaskState.TASK_STATE_SUBMITTED,
    RunState.RUNNING: TaskState.TASK_STATE_WORKING,
    RunState.RESUMING: TaskState.TASK_STATE_WORKING,
    RunState.SUSPEND_REQUESTED: TaskState.TASK_STATE_WORKING,
    RunState.SUSPENDED: TaskState.TASK_STATE_INPUT_REQUIRED,
    RunState.COMPLETED: TaskState.TASK_STATE_COMPLETED,
    RunState.FAILED: TaskState.TASK_STATE_FAILED,
    RunState.CANCELLED: TaskState.TASK_STATE_CANCELED,
}


class A2AService:
    """The A2A surface, expressed against the same runtime the web UI uses.

    Nothing here keeps its own copy of a Task. A2A Tasks are a projection of
    Sage Runs, rebuilt from the canonical event log on every read, so the two
    surfaces can never disagree about what happened in a conversation.
    """

    def __init__(
        self,
        *,
        threads,
        catalog,
        admission,
        runs,
        application,
        session_access,
        context_for,
        language: str,
        public_base_url: str,
        settings=None,
    ) -> None:
        self._threads = threads
        self._catalog = catalog
        self._admission = admission
        self._runs = runs
        self._language = language
        self.public_base_url = public_base_url
        self._application = application
        self._session_access = session_access
        self._context_for = context_for
        self._adapter = A2AProtocolAdapter()
        self._settings = settings

    async def card(self, key: ApiKeyRecord, *, base_url: str) -> AgentCard:
        agent = await self._agent_for(key)
        return agent_card(agent, base_url=base_url, streaming=True)

    async def send_message(
        self,
        message: Message,
        key: ApiKeyRecord,
        *,
        history_length: int = 0,
        wait: bool = True,
    ) -> Task:
        """Run one A2A message and answer with a Task.

        With ``wait`` the Task returned is terminal; without it the Task is
        whatever the Run looks like the moment it was accepted, which is what
        ``returnImmediately`` asks for. Either way the Run itself is driven on a
        background task, so the two differ only in how long the caller is held.
        """

        started = await self._start(message, key)
        if wait:
            await started.finished()
        return await self._task(
            started.run_id,
            started.session_id,
            started.context,
            history_length=history_length,
        )

    async def stream_message(
        self,
        message: Message,
        key: ApiKeyRecord,
        *,
        history_length: int = 0,
    ) -> AsyncIterator[Event]:
        """Run one A2A message and report it as it happens."""

        started = await self._start(message, key)
        return self._events(
            started.run_id,
            started.session_id,
            started.context,
            resume_after=started.after,
            resumed=started.after > 0,
            history_length=history_length,
        )

    async def subscribe_task(
        self,
        task_id: str,
        key: ApiKeyRecord,
        *,
        history_length: int = 0,
    ) -> AsyncIterator[Event]:
        """Attach to a Task already in flight.

        The Run's current sequence is read first and used as the resume point,
        so the client is given the Task as it stands and then only what happens
        next. A Run that is already terminal yields exactly one event: its final
        Task.
        """

        require_scope(key, SCOPE_READ)
        context = self._context_for(key)
        run = await self._run(task_id, context, key)
        return self._events(
            task_id,
            run.session_id,
            context,
            resume_after=run.last_run_sequence,
            history_length=history_length,
        )

    async def cancel_task(self, task_id: str, key: ApiKeyRecord) -> Task:
        """Ask a Run to stop and answer with the Task that resulted."""

        require_scope(key, SCOPE_INVOKE)
        context = self._context_for(key)
        run = await self._run(task_id, context, key)
        if run.state in TERMINAL_RUN_STATES:
            # A2A distinguishes "cannot be cancelled" from "does not exist", and
            # a Run that already finished is the former.
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="server.conversations.a2a.service.conflict",
                    category=ErrorCategory.CONFLICT,
                    message=f"task is already {run.state.value}",
                )
            )
        try:
            await self._runs.cancel_run(
                task_id, context, expected_revision=run.revision
            )
        except SageV2Error as exc:
            raise _absent(exc) from exc
        return await self._task(task_id, run.session_id, context, history_length=0)

    async def list_tasks(
        self,
        key: ApiKeyRecord,
        *,
        context_id: str = "",
        state: int = 0,
        page_size: int = 0,
        page_token: str = "",
        history_length: int = 0,
    ) -> tuple[list[Task], str]:
        """Page through the Tasks this key's owner can see, newest thread first.

        Sage indexes Runs per Session, not per tenant, so the walk is over the
        owner's threads and the Runs inside each. The page token records where
        in that walk the last page stopped, which keeps the cost of a page
        proportional to the page rather than to the tenant's whole history.
        """

        require_scope(key, SCOPE_READ)
        context = self._context_for(key)
        size = page_size if 0 < page_size <= _MAX_PAGE else _DEFAULT_PAGE
        cursor = _Page.parse(page_token)
        from app.v2.server.conversations.records import thread_cursor
        selected = []
        last_anchor = None
        current = None
        if cursor.session_id:
            current = await self._threads.find(cursor.session_id)
            if current is not None and current.user_id == key.owner_user_id:
                current = current.model_copy(update={"updated_at": cursor.updated_at})
            else:
                current = None
        after_thread = cursor.thread_cursor
        after_run = (cursor.session_id, cursor.created_at, cursor.run_id) if cursor.run_id else None
        states = tuple(run_state for run_state, task_state in _TASK_STATE.items() if task_state == state) if state else ()
        if state and not states:
            return [], ""
        while True:
            if context_id:
                record = current or await self._threads.find(context_id)
                candidates = [record] if record is not None and record.thread_id == context_id and record.user_id == key.owner_user_id else []
                next_thread = None
            else:
                page = await self._threads.page(user_id=key.owner_user_id, agent_id=key.agent_id,
                    include_unassigned=True, limit=199 if current else 200, cursor=after_thread or None)
                candidates = ([current] if current else []) + page.items
                next_thread = page.next_cursor
            candidates = [row for row in candidates if not key.agent_id or row.agent_id in {'', key.agent_id}]
            if candidates:
                ids = [row.thread_id for row in candidates]
                active_after = after_run if after_run is not None and after_run[0] in ids else None
                rows = await self._session_access.run_metadata_page(ids, context, after=active_after,
                    limit=size - len(selected) + 1, agent_id=key.agent_id, states=states)
                remaining = size - len(selected)
                selected.extend(rows[:remaining])
                if rows[:remaining]:
                    last_anchor = next(row for row in candidates if row.thread_id == selected[-1].session_id)
                if len(rows) > remaining:
                    last = selected[-1]
                    anchor = last_anchor
                    assert anchor is not None
                    token = _Page(thread_cursor(anchor), anchor.thread_id, anchor.updated_at,
                                  last.created_at.isoformat(), last.run_id).encode()
                    break
            if not next_thread:
                token = ""
                break
            after_thread, current, after_run = next_thread, None, None
        try:
            views = await self._session_access.read_session_views(
                {row.session_id: context for row in selected},
                run_ids=[row.run_id for row in selected], include_events=True,
            ) if selected else {}
        except SageV2Error as exc:
            raise _absent(exc) from exc
        by_run = {view.run.run_id: view for runs in views.values() for view in runs}
        tasks = []
        for row in selected:
            view = by_run.get(row.run_id)
            if view is None:
                raise _absent(SageV2Error(RuntimeErrorInfo(
                    code="run.not_found", category=ErrorCategory.VALIDATION, message="task not found",
                )))
            tasks.append(self._task_from_events(row.run_id, row.session_id, view.events,
                                               history_length=history_length))
        return tasks, token

    async def get_task(
        self, task_id: str, key: ApiKeyRecord, *, history_length: int = 0
    ) -> Task:
        require_scope(key, SCOPE_READ)
        context = self._context_for(key)
        run = await self._run(task_id, context, key)
        return await self._task(
            task_id, run.session_id, context, history_length=history_length
        )

    async def _start(self, message: Message, key: ApiKeyRecord) -> _Started:
        """Admit one A2A message and put its Run in flight."""

        performance_started_at = utc_now()
        if message.task_id:
            return await self._resume(message, key)
        require_scope(key, SCOPE_INVOKE)
        user_id = key.owner_user_id
        session_id = context_id(message)

        admitted = await self._admission.prepare(
            user_id=user_id,
            session_id=session_id,
            agent_id=key.agent_id or "",
            pin_existing=False,
            call_depth=_call_depth(message),
            absent="context not found",
        )
        if not admitted.model_ready:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="server.conversations.a2a.service.validation",
                    category=ErrorCategory.VALIDATION,
                    message=(
                        "请先在「模型」页配置模型后再发送"
                        if self._language.lower().startswith("zh")
                        else "Configure a model on the Models page before sending"
                    ),
                )
            )
        command = to_start_run(
            message,
            session_id=session_id,
            agent_id=admitted.agent_id,
            composition_hash=self._application.composition_hash,
            enabled_skills=admitted.enabled_skills,
            max_steps=admitted.max_steps,
            metadata={**admitted.metadata, **await self._execution_metadata(message, key, admitted)},
        )
        async with self._runs.workspace_guard(user_id, admitted.agent_id):
            from app.v2.server.conversations.bindings import SessionBinding
            await self._threads.bind(SessionBinding(session_id, user_id, user_id, admitted.agent_id))
            await self._threads.upsert(
                session_id, user_id, title=_title_of(command), agent_id=admitted.agent_id
            )

            context = self._context_for(key, correlation_id=get_request_id())
            run_id = await self._runs.start_detached_run(
                "a2a",
                command,
                context,
                user_id=user_id,
                session_id=session_id,
                label="a2a",
                performance_started_at=performance_started_at,
            )
        return _Started(
            run_id=run_id,
            session_id=session_id,
            context=context,
            session_access=self._session_access,
        )

    async def _resume(self, message: Message, key: ApiKeyRecord) -> _Started:
        """Answer a Task that is waiting on input and put its Run back in flight.

        A2A models "the agent asked me something" as a Task in the
        input-required state, and the answer as an ordinary Message naming that
        Task. Sage models the same thing as a suspended Run with a pending
        Interaction, so this is where one becomes the other: the message
        supplies the answer, the Interaction supplies the vocabulary the answer
        has to be expressed in.
        """

        performance_started_at = utc_now()
        require_scope(key, SCOPE_INVOKE)
        context = self._context_for(key, correlation_id=get_request_id())
        task_id = message.task_id
        run = await self._run(task_id, context, key)
        if run.state != RunState.SUSPENDED:
            # Continuing a finished conversation is a new Task in the same
            # context, not a message to the old one, so this is the client
            # describing a Task that does not exist in the state it assumed.
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="server.conversations.a2a.service.validation",
                    category=ErrorCategory.VALIDATION,
                    message=f"task is {run.state.value} and is not waiting for input",
                )
            )
        try:
            await self._runs.resume_detached_run(
                task_id,
                context,
                user_id=key.owner_user_id,
                session_id=run.session_id,
                label="a2a",
                performance_started_at=performance_started_at,
                decide=lambda interaction: _authorized_answer(interaction, message, key),
            )
        except SageV2Error as exc:
            raise _absent(exc) from exc
        return _Started(
            run_id=task_id,
            session_id=run.session_id,
            context=context,
            session_access=self._session_access,
            after=run.last_run_sequence,
        )

    async def _execution_metadata(self, message, key, admitted):
        from app.v2.server.runtime.policy import (
            ExecutionPolicy, execution_metadata, intersect_policies, EXECUTION_METADATA_KEY,
        )
        raw_grant = admitted.metadata[EXECUTION_METADATA_KEY]
        policies = [ExecutionPolicy.model_validate(raw_grant["policy"])]
        raw = message.metadata["sage.executionPolicy"] if "sage.executionPolicy" in message.metadata else None
        if raw is not None:
            if isinstance(raw, Struct):
                from google.protobuf.json_format import MessageToDict
                raw = MessageToDict(raw)
            # Protobuf numbers are floats; accept integral timeout values only.
            if isinstance(raw, dict) and isinstance(raw.get("approval_timeout_seconds"), float):
                raw = dict(raw)
                value = raw["approval_timeout_seconds"]
                if value.is_integer():
                    raw["approval_timeout_seconds"] = int(value)
            try:
                policies.append(ExecutionPolicy.model_validate(raw))
            except ValueError as exc:
                raise SageV2Error(RuntimeErrorInfo(code="server.execution_policy.validation",
                    category=ErrorCategory.VALIDATION, message="Invalid execution policy restriction")) from exc
        return execution_metadata(intersect_policies(*policies), user_id=key.owner_user_id,
                                  key_id=key.key_id, agent_id=admitted.agent_id)

    async def _events(
        self,
        run_id: str,
        session_id: str,
        context,
        *,
        resume_after: int = 0,
        resumed: bool = False,
        history_length: int,
    ) -> AsyncIterator[Event]:
        events = self._session_access.subscribe_events(
            EventCursor(run_id=run_id, run_sequence=0), context
        )
        async for event in task_stream(
            events,
            task_id=run_id,
            context_id=session_id,
            resume_after=resume_after,
            resumed=resumed,
            history_length=history_length,
        ):
            yield event

    async def _run(self, task_id: str, context, key):
        try:
            run = await self._session_access.get_run(task_id, context)
            command = await self._session_access.get_start_command(task_id, context)
            from app.v2.server.storage.workspaces import workspace_agent_id
            admitted_agent_id = command.agent_id if command.parent_run_id else workspace_agent_id(command)
            if key.agent_id and key.agent_id != admitted_agent_id:
                raise SageV2Error(RuntimeErrorInfo(code="server.conversations.a2a.service.not_found",
                    category=ErrorCategory.VALIDATION, message="task not found"))
            return run
        except SageV2Error as exc:
            raise _absent(exc) from exc

    async def _task(
        self, run_id: str, session_id: str, context, *, history_length: int
    ) -> Task:
        try:
            events = await self._session_access.read_events(run_id, context)
        except SageV2Error as exc:
            raise _absent(exc) from exc
        return self._task_from_events(run_id, session_id, events, history_length=history_length)

    def _task_from_events(self, run_id, session_id, events, *, history_length):
        reducer = TaskReducer(run_id, session_id)
        for event in events:
            for frame in self._adapter.translate(event).frames:
                reducer.push(frame)
        return reducer.build(history_length=history_length)

    async def _agent_for(self, key: ApiKeyRecord) -> AgentRecord:
        catalog = await self._catalog.get(key.owner_user_id)
        return require_agent(catalog, key.agent_id or None)


@dataclass(frozen=True, slots=True)
class _Started:
    """A Run in flight, and the two ids every A2A answer about it needs.

    ``after`` is where the Run's log already stood when this request was
    admitted. A fresh Run starts at zero, but a resumed one has a whole history
    behind it — including the ``run.suspended`` that produced the question being
    answered — so a caller that ignored it would be told the Run had stopped by
    reading the record of it stopping last time.
    """

    run_id: str
    session_id: str
    context: RequestContext
    session_access: AuthorizedSessionAccess
    after: int = 0

    async def finished(self) -> None:
        """Wait for the Run to stop advancing.

        Waiting on the event log rather than on the drive task is what makes
        this correct when an earlier request is already driving the same Run:
        this caller does not own the stream, but it can still watch the record.
        """

        events = self.session_access.subscribe_events(
            EventCursor(run_id=self.run_id, run_sequence=0), self.context
        )
        try:
            async for event in events:
                if event.run_sequence <= self.after:
                    continue
                if event.type in _TERMINAL_EVENTS:
                    return
        finally:
            closer = getattr(events, "aclose", None)
            if closer is not None:
                await closer()


@dataclass(frozen=True, slots=True)
class _Page:
    """Opaque keyset: original thread order and last emitted Run identity."""
    thread_cursor: str = ""
    session_id: str = ""
    updated_at: str = ""
    created_at: str = ""
    run_id: str = ""

    def encode(self):
        return base64.urlsafe_b64encode(json.dumps(["v2", self.thread_cursor, self.session_id,
            self.updated_at, self.created_at, self.run_id], separators=(",", ":")).encode()).decode()

    @classmethod
    def parse(cls, value):
        if not value:
            return cls()
        try:
            values = json.loads(base64.b64decode(value.encode(), altchars=b"-_", validate=True))
            if not isinstance(values, list) or len(values) != 6 or values[0] != "v2" or not all(isinstance(item, str) for item in values):
                raise ValueError("invalid keyset")
            datetime.fromisoformat(values[3])
            datetime.fromisoformat(values[4])
            from app.v2.server.conversations.records import ThreadRecord, thread_cursor
            if thread_cursor(ThreadRecord(thread_id=values[2], user_id="", updated_at=values[3])) != values[1]:
                raise ValueError("invalid thread anchor")
            return cls(*values[1:])
        except (ValueError, TypeError, UnicodeDecodeError):
            raise SageV2Error(RuntimeErrorInfo(code="server.conversations.a2a.service.validation",
                category=ErrorCategory.VALIDATION, message="malformed page token")) from None


def _state_of(run) -> int:
    return _TASK_STATE.get(run.state, TaskState.TASK_STATE_UNSPECIFIED)


def _title_of(command) -> str:
    """The thread title the web UI would have given this conversation."""

    if not command.input or not command.input[0].content:
        return ""
    return getattr(command.input[0].content[0], "text", "")[:80]


def _authorized_answer(interaction, message, key):
    answer = _answer(interaction, message)
    if answer and answer[0].startswith("approve"):
        require_scope(key, SCOPE_APPROVE)
    return answer


def _answer(interaction, message: Message) -> tuple[str, dict] | None:
    """Read an A2A reply as an answer to one pending Interaction.

    Sage questions have a closed vocabulary — approve, deny, submit, retry —
    and A2A messages have none, so the decision has to come from somewhere. A
    client that speaks Sage names it in ``sage.decision``; one that does not
    gets the reading that fits the question, and ``None`` when no reading does.
    Guessing an approval from free text is the one thing this must never do:
    "no, don't" is a sentence, not a decision, and acting on it as approval is
    irreversible.
    """

    allowed = tuple(interaction.allowed_decisions)
    metadata = message.metadata
    decision = str(metadata["sage.decision"]) if "sage.decision" in metadata else ""
    if not decision:
        if "submit" in allowed:
            # A free-text question: the message body is the whole answer.
            decision = "submit"
        elif len(allowed) == 1:
            decision = allowed[0]
        else:
            return None
    if decision not in allowed:
        return None
    payload: dict = {}
    raw = metadata["sage.payload"] if "sage.payload" in metadata else None
    if isinstance(raw, Struct):
        payload = {key: raw[key] for key in raw}
    text = "\n".join(part.text for part in message.parts if part.text)
    if text and "text" not in payload:
        payload["text"] = text
    return decision, payload


def _call_depth(message: Message) -> int:
    """Read how many agents deep this call already is, and refuse to go deeper.

    A2A gives a peer no way to know it is already inside a delegation, so two
    agents that each delegate to the other recurse until something else runs
    out. Sage announces the hop it creates in ``sage.callDepth``; a caller that
    speaks it inherits the budget, and one that does not starts at zero — which
    is the right reading, because a caller outside this convention cannot be
    part of a Sage delegation chain.

    The outbound half of the budget is enforced separately, by not composing
    A2A Tools into a Run that is already at the limit. This check is the belt
    to that pair of braces: it is what stops a peer that rewrites the depth it
    was handed.
    """

    metadata = message.metadata
    raw = metadata[CALL_DEPTH_KEY] if CALL_DEPTH_KEY in metadata else 0
    try:
        if not isinstance(raw, (str, int, float)):
            raise TypeError("call depth must be numeric")
        depth = int(float(raw))
    except (TypeError, ValueError):
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.conversations.a2a.service.validation",
                category=ErrorCategory.VALIDATION,
                message=f"{CALL_DEPTH_KEY} must be a number",
            )
        ) from None
    if depth < 0:
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.conversations.a2a.service.validation",
                category=ErrorCategory.VALIDATION,
                message=f"{CALL_DEPTH_KEY} must not be negative",
            )
        )
    if depth > MAX_CALL_DEPTH:
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.conversations.a2a.service.validation",
                category=ErrorCategory.VALIDATION,
                message=f"this request is {depth} agents deep, which is past the "
                f"{MAX_CALL_DEPTH}-hop limit",
            )
        )
    return depth


def _stale(exc: SageV2Error) -> SageV2Error:
    """Report a lost race over one Task as bad params rather than as -32002.

    A2A has no error for "the Task moved under you". -32002 is reserved for a
    Task that cannot be cancelled, and reusing it here would tell a client to
    give up when the right response is to read the Task again and see what it
    is waiting on now.
    """

    if (
        exc.info.code.endswith("not_found")
        or exc.info.category == ErrorCategory.VALIDATION
    ):
        return exc
    return SageV2Error(
        RuntimeErrorInfo(
            code="server.conversations.a2a.service.validation",
            category=ErrorCategory.VALIDATION,
            message=exc.info.message,
            metadata={"detail": exc.info.metadata.get("detail", exc.info.code)},
        )
    )


def _absent(exc: SageV2Error) -> SageV2Error:
    """Report a Task another tenant owns as missing, not as forbidden.

    Task ids are guessable enough to enumerate. Answering "denied" for ids that
    exist and "not found" for ids that do not turns the endpoint into an oracle
    for which conversations another tenant is having.
    """

    if exc.info.category == ErrorCategory.AUTHORIZATION:
        return SageV2Error(
            RuntimeErrorInfo(
                code="server.conversations.a2a.service.not_found",
                category=ErrorCategory.VALIDATION,
                message="task not found",
            )
        )
    return exc

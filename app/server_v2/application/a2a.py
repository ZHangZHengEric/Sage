from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from dataclasses import dataclass

from a2a.server.events.event_queue import Event
from a2a.types.a2a_pb2 import AgentCard, Message, Task, TaskState
from google.protobuf.struct_pb2 import Struct
from sagents.v2.contracts.errors import ErrorCategory, SageV2Error
from sagents.v2.contracts.run_state import (
    TERMINAL_RUN_STATES,
    EventCursor,
    RunState,
)
from sagents.v2.interfaces.protocols.a2a import A2AProtocolAdapter
from sagents.v2.tool.plugins.a2a import CALL_DEPTH_KEY, MAX_CALL_DEPTH

from app.server_v2.adapters.a2a.card import agent_card
from app.server_v2.adapters.a2a.mapping import context_id, to_start_run
from app.server_v2.adapters.a2a.stream import task_stream
from app.server_v2.adapters.a2a.task import TaskReducer
from app.server_v2.core.errors import ServerV2Error, map_sage_error
from app.server_v2.core.observability.context import get_request_id
from app.server_v2.domain.api_keys import (
    SCOPE_INVOKE,
    SCOPE_READ,
    ApiKeyRecord,
    require_scope,
)
from app.server_v2.domain.catalog import AgentRecord, require_agent

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
        sessions,
        execution,
        runtime,
        context_for,
    ) -> None:
        self._threads = threads
        self._catalog = catalog
        self._admission = admission
        self._runs = runs
        self._sessions = sessions
        self._execution = execution
        self._runtime = runtime
        self._context_for = context_for
        self._adapter = A2AProtocolAdapter()

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
        run = await self._run(task_id, context)
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
        run = await self._run(task_id, context)
        if run.state in TERMINAL_RUN_STATES:
            # A2A distinguishes "cannot be cancelled" from "does not exist", and
            # a Run that already finished is the former.
            raise ServerV2Error("conflict", f"task is already {run.state.value}")
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
        sessions = await self._session_ids(key, context_id=context_id)
        cursor = _Page.parse(page_token)
        tasks: list[Task] = []
        for index, session_id in enumerate(sessions):
            if index < cursor.session_index:
                continue
            runs = await self._list_runs(session_id, context)
            start = cursor.run_index if index == cursor.session_index else 0
            for offset, run in enumerate(runs[start:], start=start):
                if state and _state_of(run) != state:
                    continue
                if len(tasks) == size:
                    return tasks, _Page(index, offset).encode()
                tasks.append(
                    await self._task(
                        run.run_id,
                        session_id,
                        context,
                        history_length=history_length,
                    )
                )
        return tasks, ""

    async def get_task(
        self, task_id: str, key: ApiKeyRecord, *, history_length: int = 0
    ) -> Task:
        require_scope(key, SCOPE_READ)
        context = self._context_for(key)
        run = await self._run(task_id, context)
        return await self._task(
            task_id, run.session_id, context, history_length=history_length
        )

    async def _start(self, message: Message, key: ApiKeyRecord) -> _Started:
        """Admit one A2A message and put its Run in flight."""

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
            raise ServerV2Error("validation", self._execution.model_missing_message())
        command = to_start_run(
            message,
            session_id=session_id,
            agent_id=admitted.agent_id,
            composition_hash=self._runtime.composition_hash,
            enabled_skills=tuple(item.name for item in admitted.skills),
            metadata=admitted.metadata,
        )
        await self._admission.remember(
            session_id, user_id, title=_title_of(command), agent_id=admitted.agent_id
        )

        context = self._context_for(key, correlation_id=get_request_id())
        try:
            run_id = await self._runs.start_detached_run(
                "a2a",
                command,
                context,
                user_id=user_id,
                session_id=session_id,
                label="a2a",
            )
        except SageV2Error as exc:
            raise map_sage_error(exc) from exc
        return _Started(
            run_id=run_id,
            session_id=session_id,
            context=context,
            sessions=self._sessions,
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

        require_scope(key, SCOPE_INVOKE)
        context = self._context_for(key, correlation_id=get_request_id())
        task_id = message.task_id
        run = await self._run(task_id, context)
        if run.state != RunState.SUSPENDED:
            # Continuing a finished conversation is a new Task in the same
            # context, not a message to the old one, so this is the client
            # describing a Task that does not exist in the state it assumed.
            raise ServerV2Error(
                "validation", f"task is {run.state.value} and is not waiting for input"
            )
        try:
            await self._runs.resume_detached_run(
                task_id,
                context,
                user_id=key.owner_user_id,
                session_id=run.session_id,
                label="a2a",
                decide=lambda interaction: _answer(interaction, message),
            )
        except SageV2Error as exc:
            raise _absent(exc) from exc
        except ServerV2Error as exc:
            raise _stale(exc) from exc
        return _Started(
            run_id=task_id,
            session_id=run.session_id,
            context=context,
            sessions=self._sessions,
            after=run.last_run_sequence,
        )

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
        events = self._sessions.subscribe(
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

    async def _run(self, task_id: str, context):
        try:
            return await self._sessions.get_run(task_id, context)
        except SageV2Error as exc:
            raise _absent(exc) from exc

    async def _session_ids(self, key: ApiKeyRecord, *, context_id: str) -> list[str]:
        threads = await self._threads.list_for(key.owner_user_id)
        ids = [thread.thread_id for thread in threads]
        if not context_id:
            return ids
        # A context the key cannot see is empty, not forbidden, for the same
        # reason an unreadable Task is reported as missing.
        return [item for item in ids if item == context_id]

    async def _list_runs(self, session_id: str, context) -> list:
        try:
            runs = await self._sessions.list_runs(session_id, context)
        except SageV2Error:
            return []
        return sorted(runs, key=lambda run: (run.created_at, run.run_id))

    async def _task(
        self, run_id: str, session_id: str, context, *, history_length: int
    ) -> Task:
        try:
            events = await self._sessions.read_run_events(run_id, context)
        except SageV2Error as exc:
            raise _absent(exc) from exc
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
    context: object
    sessions: object
    after: int = 0

    async def finished(self) -> None:
        """Wait for the Run to stop advancing.

        Waiting on the event log rather than on the drive task is what makes
        this correct when an earlier request is already driving the same Run:
        this caller does not own the stream, but it can still watch the record.
        """

        events = self.sessions.subscribe(
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
    """Where a ``ListTasks`` walk stopped: a thread, and a Run inside it.

    Indices rather than ids because the walk is ordered and resumable from a
    position; an id would need a second lookup to find the position again. The
    token is opaque to the client so the shape can change without breaking one.
    """

    session_index: int = 0
    run_index: int = 0

    def encode(self) -> str:
        raw = f"v1:{self.session_index}:{self.run_index}".encode()
        return base64.urlsafe_b64encode(raw).decode()

    @classmethod
    def parse(cls, value: str) -> "_Page":
        if not value:
            return cls()
        try:
            decoded = base64.urlsafe_b64decode(value.encode()).decode()
            marker, session_index, run_index = decoded.split(":")
        except (ValueError, UnicodeDecodeError):
            raise ServerV2Error("validation", "malformed page token") from None
        if marker != "v1":
            raise ServerV2Error("validation", "unsupported page token")
        try:
            return cls(int(session_index), int(run_index))
        except ValueError:
            raise ServerV2Error("validation", "malformed page token") from None


def _state_of(run) -> int:
    return _TASK_STATE.get(run.state, TaskState.TASK_STATE_UNSPECIFIED)


def _title_of(command) -> str:
    """The thread title the web UI would have given this conversation."""

    if not command.input or not command.input[0].content:
        return ""
    return getattr(command.input[0].content[0], "text", "")[:80]


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
        depth = int(float(raw))
    except (TypeError, ValueError):
        raise ServerV2Error(
            "validation", f"{CALL_DEPTH_KEY} must be a number"
        ) from None
    if depth < 0:
        raise ServerV2Error("validation", f"{CALL_DEPTH_KEY} must not be negative")
    if depth > MAX_CALL_DEPTH:
        raise ServerV2Error(
            "validation",
            f"this request is {depth} agents deep, which is past the "
            f"{MAX_CALL_DEPTH}-hop limit",
        )
    return depth


def _stale(exc: ServerV2Error) -> ServerV2Error:
    """Report a lost race over one Task as bad params rather than as -32002.

    A2A has no error for "the Task moved under you". -32002 is reserved for a
    Task that cannot be cancelled, and reusing it here would tell a client to
    give up when the right response is to read the Task again and see what it
    is waiting on now.
    """

    if exc.reason in {"not_found", "validation"}:
        return exc
    return ServerV2Error("validation", exc.message, detail=exc.detail)


def _absent(exc: SageV2Error) -> ServerV2Error:
    """Report a Task another tenant owns as missing, not as forbidden.

    Task ids are guessable enough to enumerate. Answering "denied" for ids that
    exist and "not found" for ids that do not turns the endpoint into an oracle
    for which conversations another tenant is having.
    """

    if exc.info.category == ErrorCategory.AUTHORIZATION:
        return ServerV2Error("not_found", "task not found")
    return map_sage_error(exc)

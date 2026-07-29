"""Backend child-stream consumption with completion decoupled from HTTP EOF.

Team/Fibre ``_delegate_task_via_backend`` used to await the child ``/api/chat``
body forever. Same-process nested calls can leave the parent stuck even after
the child session is already terminal. This helper finishes on the first of:

1. child stream ``stream_end``
2. child session terminal status (completed / error / interrupted)
3. parent interrupt / cancel
4. HTTP EOF (normal path)

There is no wall-clock timeout while the child is still running.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Union

from sagents.context.messages.message import MessageChunk
from sagents.context.messages.message_manager import MessageManager
from sagents.context.session_context import SessionContext, SessionStatus
from sagents.utils.logger import logger

StreamPayload = Union[MessageChunk, Dict[str, Any]]
OnChunks = Callable[[List[StreamPayload]], Awaitable[None]]
ShouldInterrupt = Callable[[], bool]

TERMINAL_STATUS_VALUES = frozenset(
    {
        SessionStatus.COMPLETED.value,
        SessionStatus.ERROR.value,
        SessionStatus.INTERRUPTED.value,
        "completed",
        "error",
        "interrupted",
    }
)

DEFAULT_WATCH_POLL_SECONDS = 0.5


@dataclass
class ChildStreamResult:
    """Outcome of consuming a backend child chat stream."""

    chunk_batches: List[List[StreamPayload]] = field(default_factory=list)
    reason: str = "eof"
    child_status: Optional[str] = None
    error: Optional[str] = None

    @property
    def all_chunks(self) -> List[StreamPayload]:
        flat: List[StreamPayload] = []
        for batch in self.chunk_batches:
            flat.extend(batch)
        return flat


def _payload_type(payload: StreamPayload) -> Optional[str]:
    if isinstance(payload, MessageChunk):
        return payload.type or payload.message_type
    if isinstance(payload, dict):
        value = payload.get("type") or payload.get("message_type")
        return str(value) if value is not None else None
    return None


def is_stream_end_payload(payload: StreamPayload) -> bool:
    return _payload_type(payload) == "stream_end"


def batch_has_stream_end(chunks: Sequence[StreamPayload]) -> bool:
    return any(is_stream_end_payload(chunk) for chunk in chunks)


def resolve_child_workspace(
    session_id: str,
    parent_session_id: Optional[str] = None,
) -> Optional[str]:
    """Locate the child session workspace on disk or via the session registry."""

    if not session_id:
        return None

    try:
        from sagents.session_runtime import get_global_session_manager

        manager = get_global_session_manager()
        workspace = manager.get_session_workspace(session_id)
        if workspace and os.path.isdir(workspace):
            return workspace

        live = manager.get_live_session(session_id)
        if live is not None:
            live_ws = getattr(live, "session_workspace", None)
            if live_ws and os.path.isdir(live_ws):
                return str(live_ws)
            ctx = getattr(live, "session_context", None)
            ctx_ws = getattr(ctx, "session_workspace", None) if ctx else None
            if ctx_ws and os.path.isdir(ctx_ws):
                return str(ctx_ws)

        if parent_session_id:
            parent_ws = manager.get_session_workspace(parent_session_id)
            if parent_ws:
                candidate = os.path.join(parent_ws, "sub_sessions", session_id)
                if os.path.isdir(candidate):
                    return candidate
                # Nested sub-sessions: walk one level of sub_sessions trees.
                nested_root = os.path.join(parent_ws, "sub_sessions")
                if os.path.isdir(nested_root):
                    for entry in os.scandir(nested_root):
                        if not entry.is_dir():
                            continue
                        nested = os.path.join(
                            entry.path, "sub_sessions", session_id
                        )
                        if os.path.isdir(nested):
                            return nested
    except Exception as exc:
        logger.debug(
            f"resolve_child_workspace: registry lookup failed for {session_id}: {exc}"
        )

    return None


def read_child_session_status(
    session_id: str,
    parent_session_id: Optional[str] = None,
) -> Optional[str]:
    """Return child status from the live session or persisted session_context."""

    if not session_id:
        return None

    try:
        from sagents.session_runtime import get_global_session_manager

        manager = get_global_session_manager()
        live = manager.get_live_session(session_id)
        if live is not None:
            status = live.get_status()
            if isinstance(status, SessionStatus):
                return status.value
            if status is not None:
                return str(status)
    except Exception as exc:
        logger.debug(
            f"read_child_session_status: live lookup failed for {session_id}: {exc}"
        )

    workspace = resolve_child_workspace(session_id, parent_session_id)
    if not workspace:
        return None
    context_path = os.path.join(workspace, "session_context.json")
    if not os.path.exists(context_path):
        return None
    try:
        with open(context_path, "r", encoding="utf-8") as handle:
            snapshot = json.load(handle)
        if isinstance(snapshot, dict):
            status = snapshot.get("status")
            if status is not None:
                return str(status)
    except Exception as exc:
        logger.debug(
            f"read_child_session_status: disk read failed for {session_id}: {exc}"
        )
    return None


def load_child_history_fallback(
    session_id: str,
    parent_session_id: Optional[str] = None,
) -> str:
    """Build a summary history string from the child's persisted messages."""

    workspace = resolve_child_workspace(session_id, parent_session_id)
    if not workspace:
        return ""
    try:
        messages, _, _ = SessionContext.load_persisted_message_ledger(
            workspace, session_id=session_id
        )
    except Exception as exc:
        logger.warning(
            f"load_child_history_fallback: failed to load ledger for {session_id}: {exc}"
        )
        return ""
    if not messages:
        return ""
    try:
        return MessageManager.convert_messages_to_str(messages)
    except Exception as exc:
        logger.warning(
            f"load_child_history_fallback: convert failed for {session_id}: {exc}"
        )
        return ""


def merge_history_with_fallback(
    history_str: str,
    session_id: str,
    parent_session_id: Optional[str] = None,
    *,
    prefer_fallback_if_longer: bool = True,
) -> str:
    """Prefer streamed history, but use disk when the HTTP stream was truncated."""

    streamed = (history_str or "").strip()
    fallback = load_child_history_fallback(
        session_id, parent_session_id=parent_session_id
    ).strip()
    if not fallback:
        return streamed
    if not streamed:
        return fallback
    if prefer_fallback_if_longer and len(fallback) > len(streamed):
        return fallback
    return streamed


async def consume_backend_child_stream(
    *,
    backend_client: Any,
    agent_id: str,
    messages: List[Dict[str, Any]],
    session_id: str,
    system_context: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
    max_loop_count: Optional[int] = None,
    interrupt_event: Any = None,
    parent_session_id: Optional[str] = None,
    on_chunks: Optional[OnChunks] = None,
    should_interrupt: Optional[ShouldInterrupt] = None,
    watch_poll_seconds: float = DEFAULT_WATCH_POLL_SECONDS,
) -> ChildStreamResult:
    """Consume a backend child stream until a non-EOF completion signal wins.

    Waits as long as the child is still running. Completes as soon as the child
    reaches a terminal status, ``stream_end`` arrives, HTTP EOF, or interrupt.

    Returns collected chunk batches and a reason. Callers must still summarize
    and return a tool string so ``tool_call_result`` is always written.
    """

    cancel_event = asyncio.Event()
    event_queue: asyncio.Queue = asyncio.Queue()
    result = ChildStreamResult()

    async def _reader() -> None:
        try:
            async for chunks in backend_client.stream_chat(
                agent_id=agent_id,
                messages=messages,
                session_id=session_id,
                system_context=system_context,
                user_id=user_id,
                max_loop_count=max_loop_count,
                interrupt_event=interrupt_event,
                cancel_event=cancel_event,
            ):
                await event_queue.put(("chunks", list(chunks)))
                if batch_has_stream_end(chunks):
                    await event_queue.put(("done", "stream_end"))
                    return
            await event_queue.put(("done", "eof"))
        except asyncio.CancelledError:
            await event_queue.put(("done", "cancelled"))
            raise
        except Exception as exc:
            await event_queue.put(("error", exc))

    async def _watcher() -> None:
        observed_status: Optional[str] = None
        try:
            while not cancel_event.is_set():
                if should_interrupt and should_interrupt():
                    await event_queue.put(("done", "interrupted"))
                    return
                if (
                    interrupt_event is not None
                    and hasattr(interrupt_event, "is_set")
                    and interrupt_event.is_set()
                ):
                    await event_queue.put(("done", "interrupted"))
                    return

                status = read_child_session_status(
                    session_id, parent_session_id=parent_session_id
                )
                if status:
                    observed_status = status
                if status and status in TERMINAL_STATUS_VALUES:
                    result.child_status = status
                    logger.info(
                        "[DelegateStream] child session terminal "
                        f"session_id={session_id} status={status}; "
                        "completing without waiting for HTTP EOF"
                    )
                    await event_queue.put(("done", "child_terminal"))
                    return
                await asyncio.sleep(watch_poll_seconds)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug(
                f"[DelegateStream] watcher error session_id={session_id}: {exc}"
            )
        finally:
            if observed_status and not result.child_status:
                result.child_status = observed_status

    reader_task = asyncio.create_task(_reader(), name=f"delegate-stream-{session_id}")
    watcher_task = asyncio.create_task(
        _watcher(), name=f"delegate-watch-{session_id}"
    )

    try:
        while True:
            kind, payload = await event_queue.get()
            if kind == "chunks":
                batch: List[StreamPayload] = payload
                result.chunk_batches.append(batch)
                if on_chunks is not None:
                    await on_chunks(batch)
                continue
            if kind == "error":
                result.reason = "error"
                result.error = str(payload)
                raise payload
            if kind == "done":
                result.reason = str(payload)
                break
    finally:
        cancel_event.set()
        for task in (reader_task, watcher_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(reader_task, watcher_task, return_exceptions=True)

    logger.info(
        "[DelegateStream] finished "
        f"session_id={session_id} reason={result.reason} "
        f"child_status={result.child_status} batches={len(result.chunk_batches)}"
    )
    return result

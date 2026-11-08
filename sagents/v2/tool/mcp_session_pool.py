"""Opt-in, host-owned MCP sessions with task-local SDK lifecycle ownership."""

from __future__ import annotations

import asyncio
import math
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import anyio

from sagents.v2.tool.plugins._shared.mcp_session import sdk_session
from sagents.v2.tool.plugins.mcp import McpServerConfig, McpSessionFactory, McpToolPlugin


@dataclass(eq=False)
class _Entry:
    key: str
    config: McpServerConfig
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    closed: asyncio.Event = field(default_factory=asyncio.Event)
    replacement: asyncio.Event = field(default_factory=asyncio.Event)
    session: Any = None
    scope: anyio.CancelScope | None = None
    task: asyncio.Task | None = None
    active: int = 0
    retired: bool = False
    force_close: bool = False
    idle_since: float = 0
    failure: str | None = None
    startup_cancelled: bool = False


class _Lease:
    def __init__(self, entry: _Entry) -> None:
        self._entry = entry
        self._released = False

    async def _request(self, method: str, *args, **kwargs):
        if self._released or self._entry.force_close or self._entry.closed.is_set():
            raise RuntimeError("MCP session lease is closed")
        try:
            return await getattr(self._entry.session, method)(*args, **kwargs)
        except BaseException:
            self._entry.retired = True
            self._entry.changed.set()
            raise

    async def list_tools(self, *args, **kwargs):
        return await self._request("list_tools", *args, **kwargs)

    async def call_tool(self, *args, **kwargs):
        return await self._request("call_tool", *args, **kwargs)


class McpSessionPool:
    """Callable ``session_factory`` for one host/security scope and event loop.

    Enter the pool before giving it to McpToolPlugin, and close it after the
    host's work finishes. SDK contexts are entered and exited by one owner
    task; borrowers only release leases. The pool never replays tool calls.
    """

    def __init__(
        self,
        *,
        session_factory: McpSessionFactory | None = None,
        idle_timeout_seconds: float = 300,
        shutdown_timeout_seconds: float = 10,
        cleanup_timeout_seconds: float = 5,
    ) -> None:
        for name, value in (
            ("idle_timeout_seconds", idle_timeout_seconds),
            ("shutdown_timeout_seconds", shutdown_timeout_seconds),
            ("cleanup_timeout_seconds", cleanup_timeout_seconds),
        ):
            self._validate_timeout(name, value)
        self._factory = session_factory or sdk_session
        self._sdk_factory = session_factory is None or session_factory is sdk_session
        self._idle_timeout = idle_timeout_seconds
        self._shutdown_timeout = shutdown_timeout_seconds
        self._cleanup_timeout = cleanup_timeout_seconds
        self._entries: dict[str, _Entry] = {}
        self._owners: set[asyncio.Task] = set()
        self._errors: deque[str] = deque(maxlen=32)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._closing = False
        self._close_task: asyncio.Task | None = None

    @staticmethod
    def _validate_timeout(name: str, value: float) -> None:
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be finite and positive")

    @property
    def cleanup_errors(self) -> tuple[str, ...]:
        """Bounded lifecycle failure codes, never raw transport/credential text."""
        return tuple(self._errors)

    async def __aenter__(self) -> McpSessionPool:
        if self._loop is not None or self._closing:
            raise RuntimeError("MCP session pool cannot be re-entered")
        self._loop = asyncio.get_running_loop()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    def _check_loop(self) -> None:
        if self._loop is not asyncio.get_running_loop():
            raise RuntimeError("MCP session pool must be entered on this event loop")

    @asynccontextmanager
    async def __call__(self, config: McpServerConfig):
        self._check_loop()
        self._validate_timeout("timeout_seconds", config.timeout_seconds)
        config = config.model_copy(deep=True)
        key = McpToolPlugin.servers_fingerprint((config,))
        # All entry state changes are synchronous on the owning asyncio loop.
        # No lock or user code is awaited between checking and reserving a lease.
        async with asyncio.timeout(config.timeout_seconds):
            while True:
                if self._closing:
                    raise RuntimeError("MCP session pool is closing")
                entry = self._entries.get(key)
                if entry is None:
                    entry = _Entry(key=key, config=config)
                    self._entries[key] = entry
                    entry.task = asyncio.create_task(self._own(entry))
                    self._owners.add(entry.task)
                    entry.task.add_done_callback(self._owner_done)
                if entry.retired:
                    await entry.replacement.wait()
                    continue
                await entry.ready.wait()
                if self._closing:
                    raise RuntimeError("MCP session pool is closing")
                if entry.failure is not None:
                    if entry.failure == "startup_timeout":
                        raise TimeoutError("MCP session acquisition timed out")
                    raise ConnectionError("MCP session initialization failed")
                if entry.retired:
                    continue
                entry.active += 1
                entry.changed.set()
                break
        lease = _Lease(entry)
        try:
            yield lease
        except BaseException:
            entry.retired = True
            raise
        finally:
            lease._released = True
            entry.active -= 1
            if entry.active == 0:
                entry.idle_since = asyncio.get_running_loop().time()
            entry.changed.set()

    def _owner_done(self, task: asyncio.Task) -> None:
        self._owners.discard(task)
        if not task.cancelled():
            task.exception()

    def _cancel_startup(self, entry: _Entry) -> None:
        # One-shot asyncio cancellation permits asynchronous cleanup while an
        # AnyIO scope's persistent cancellation would cancel every cleanup await.
        if self._preserve_stdio_cleanup(entry):
            # The SDK already bounds stdio initialization. It may be unwinding
            # an early initialization error inside __aenter__; another cancel
            # here would interrupt process-tree cleanup that already started.
            return
        if entry.session is None and not entry.startup_cancelled:
            entry.startup_cancelled = True
            entry.failure = "startup_timeout"
            entry.retired = True
            if entry.scope is not None and not self._preserve_stdio_cleanup(entry):
                entry.scope.deadline = asyncio.get_running_loop().time() + self._cleanup_timeout
            if entry.task is not None:
                entry.task.cancel()

    def _preserve_stdio_cleanup(self, entry: _Entry) -> bool:
        # SDK stdio needs its graceful wait followed by process-group termination.
        # Cutting that sequence short can orphan descendants. Bound the host's
        # wait instead and retain the owner until the SDK finishes teardown.
        return self._sdk_factory and entry.config.protocol == "stdio"

    async def _own(self, entry: _Entry) -> None:
        entered = False
        scope = anyio.CancelScope()
        startup_timer = asyncio.get_running_loop().call_later(
            entry.config.timeout_seconds, self._cancel_startup, entry
        )
        entry.scope = scope
        try:
            # This scope surrounds (rather than crosses) all SDK/AnyIO scopes.
            # Its deadline can change without moving __aexit__ to another task.
            with scope:
                async with self._factory(entry.config) as session:
                    startup_timer.cancel()
                    entered = True
                    entry.session = session
                    entry.idle_since = asyncio.get_running_loop().time()
                    scope.deadline = math.inf
                    entry.ready.set()
                    try:
                        while not entry.force_close:
                            entry.changed.clear()
                            if entry.active == 0:
                                if self._closing or entry.retired:
                                    break
                                remaining = self._idle_timeout - (
                                    asyncio.get_running_loop().time() - entry.idle_since
                                )
                                if remaining <= 0:
                                    break
                                try:
                                    async with asyncio.timeout(remaining):
                                        await entry.changed.wait()
                                except TimeoutError:
                                    pass
                            else:
                                await entry.changed.wait()
                    finally:
                        entry.retired = True
                        if not self._preserve_stdio_cleanup(entry):
                            scope.deadline = anyio.current_time() + self._cleanup_timeout
        except asyncio.CancelledError:
            entry.failure = entry.failure or "session_closed"
        except Exception:
            if entered:
                self._errors.append("session_cleanup_failed")
            else:
                entry.failure = "initialization_failed"
        finally:
            # Teardown may re-raise the original startup cancellation instead
            # of the cleanup scope's exception. Record the expired deadline
            # regardless of how the transport exits the scope.
            if scope.cancel_called:
                self._errors.append("cleanup_timeout")
                if not entered:
                    entry.failure = "startup_timeout"
            startup_timer.cancel()
            entry.retired = True
            entry.ready.set()
            entry.closed.set()
            entry.replacement.set()
            if self._entries.get(entry.key) is entry:
                del self._entries[entry.key]

    async def aclose(self) -> None:
        """Drain leases, then close concurrently within a separate cleanup bound.

        Cancellation of this caller leaves the shared close task running.
        Hosts can await aclose again to observe completion.
        """
        self._check_loop()
        if self._close_task is None:
            self._closing = True
            self._close_task = asyncio.create_task(self._close())
        await asyncio.shield(self._close_task)

    async def _close(self) -> None:
        entries = tuple(self._entries.values())
        for entry in entries:
            entry.ready.set()  # Wake acquisition waiters, who check _closing.
            entry.replacement.set()
            entry.changed.set()
            if entry.session is None:
                self._cancel_startup(entry)
        tasks = set(self._owners)
        if not tasks:
            return
        _, pending = await asyncio.wait(tasks, timeout=self._shutdown_timeout)
        for entry in entries:
            if entry.task in pending:
                entry.force_close = True
                entry.changed.set()
                if (entry.scope is not None and entry.session is not None
                        and not self._preserve_stdio_cleanup(entry)):
                    entry.scope.deadline = asyncio.get_running_loop().time() + self._cleanup_timeout
        if pending:
            _, pending = await asyncio.wait(pending, timeout=self._cleanup_timeout)
        if pending:
            # A custom factory may suppress cancellation indefinitely. Keep its
            # task tracked and its entry retired; do not claim it was destroyed.
            self._errors.append("cleanup_incomplete")

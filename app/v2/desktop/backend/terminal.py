"""Interactive PTY sessions owned by the local Desktop sidecar.

The terminal is a user-operated local shell. It deliberately does not reuse the
Agent shell tool or its approval protocol: Agent commands continue to flow
through the runtime policy, while terminal input comes directly from the user.
"""

from __future__ import annotations

import asyncio
import base64
from collections import deque
import errno
import os
from pathlib import Path
import shutil
import signal
import struct
import subprocess
from typing import AsyncIterator, Callable
from uuid import uuid4

if os.name == "posix":
    import fcntl
    import pty
    import termios


_OUTPUT_CHUNK_BYTES = 16 * 1024
_HISTORY_EVENTS = 1024
_LIVE_SUBSCRIBER_EVENTS = 256
_EXITED_SESSION_RETENTION_SECONDS = 60.0
_MIN_COLUMNS = 10
_MAX_COLUMNS = 500
_MIN_ROWS = 2
_MAX_ROWS = 500


def _bounded_size(columns: int, rows: int) -> tuple[int, int]:
    columns = int(columns)
    rows = int(rows)
    if not _MIN_COLUMNS <= columns <= _MAX_COLUMNS:
        raise ValueError(
            f"terminal columns must be between {_MIN_COLUMNS} and {_MAX_COLUMNS}"
        )
    if not _MIN_ROWS <= rows <= _MAX_ROWS:
        raise ValueError(f"terminal rows must be between {_MIN_ROWS} and {_MAX_ROWS}")
    return columns, rows


def _default_shell() -> str:
    configured = str(os.environ.get("SHELL") or "").strip()
    if configured and Path(configured).is_absolute() and os.access(configured, os.X_OK):
        return configured
    for candidate in ("zsh", "bash", "sh"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    raise RuntimeError("no interactive shell is available")


def _set_terminal_size(descriptor: int, columns: int, rows: int) -> None:
    columns, rows = _bounded_size(columns, rows)
    if os.name != "posix":
        raise RuntimeError("interactive PTY terminals are unavailable on this platform")
    packed = struct.pack("HHHH", rows, columns, 0, 0)
    fcntl.ioctl(descriptor, termios.TIOCSWINSZ, packed)


class TerminalSession:
    def __init__(
        self,
        *,
        session_id: str,
        owner_id: str,
        cwd: Path,
        shell: str,
        columns: int,
        rows: int,
    ) -> None:
        if os.name != "posix":
            raise RuntimeError(
                "interactive PTY terminals currently require macOS or Linux"
            )
        columns, rows = _bounded_size(columns, rows)
        root = cwd.expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ValueError("terminal working directory must be a directory")

        master_fd, slave_fd = pty.openpty()
        try:
            _set_terminal_size(slave_fd, columns, rows)
            environment = dict(os.environ)
            environment.update(
                {
                    "TERM": "xterm-256color",
                    "COLORTERM": "truecolor",
                    "SAGE_TERMINAL": "1",
                }
            )
            self.process = subprocess.Popen(
                [shell, "-l"],
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                cwd=root,
                env=environment,
                close_fds=True,
                start_new_session=True,
            )
        except BaseException:
            os.close(master_fd)
            raise
        finally:
            os.close(slave_fd)

        self.session_id = session_id
        self.owner_id = owner_id
        self.cwd = root
        self.shell = shell
        self.columns = columns
        self.rows = rows
        self.master_fd = master_fd
        self._sequence = 0
        self._history: deque[dict[str, object]] = deque(maxlen=_HISTORY_EVENTS)
        self._subscribers: set[asyncio.Queue[dict[str, object]]] = set()
        self._ended = asyncio.Event()
        self._write_lock = asyncio.Lock()
        self._reader_task = asyncio.create_task(
            self._read_output(),
            name=f"sage-terminal-reader:{session_id}",
        )

    @property
    def running(self) -> bool:
        return self.process.poll() is None and not self._ended.is_set()

    @property
    def sequence(self) -> int:
        return self._sequence

    def snapshot(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "pid": self.process.pid,
            "cwd": str(self.cwd),
            "shell": self.shell,
            "columns": self.columns,
            "rows": self.rows,
            "sequence": self.sequence,
            "running": self.running,
        }

    async def write(self, data: bytes) -> None:
        if not data:
            return
        if not self.running:
            raise RuntimeError("terminal session has exited")
        async with self._write_lock:
            await asyncio.to_thread(os.write, self.master_fd, data)

    async def resize(self, columns: int, rows: int) -> None:
        columns, rows = _bounded_size(columns, rows)
        if not self.running:
            return
        await asyncio.to_thread(
            _set_terminal_size,
            self.master_fd,
            columns,
            rows,
        )
        self.columns = columns
        self.rows = rows
        try:
            os.killpg(self.process.pid, signal.SIGWINCH)
        except ProcessLookupError:
            pass

    async def events(self, after_sequence: int = 0) -> AsyncIterator[dict[str, object]]:
        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(
            maxsize=_LIVE_SUBSCRIBER_EVENTS
        )
        backlog = [
            event for event in self._history if int(event["sequence"]) > after_sequence
        ]
        terminal_in_backlog = any(
            event["type"] in {"terminal.exited", "terminal.failed"} for event in backlog
        )
        if not terminal_in_backlog and not self._ended.is_set():
            self._subscribers.add(queue)
        try:
            for event in backlog:
                yield event
            if terminal_in_backlog or self._ended.is_set():
                return
            while True:
                event = await queue.get()
                yield event
                if event["type"] in {
                    "terminal.exited",
                    "terminal.failed",
                    "terminal.overflow",
                }:
                    return
        finally:
            self._subscribers.discard(queue)

    async def close(self) -> None:
        if self.running:
            try:
                os.killpg(self.process.pid, signal.SIGHUP)
            except ProcessLookupError:
                pass
        try:
            await asyncio.wait_for(self._ended.wait(), timeout=2)
        except TimeoutError:
            if self.process.poll() is None:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            try:
                await asyncio.wait_for(self._ended.wait(), timeout=2)
            except TimeoutError:
                self._reader_task.cancel()
        await asyncio.gather(self._reader_task, return_exceptions=True)

    async def _read_output(self) -> None:
        try:
            while True:
                try:
                    data = await asyncio.to_thread(
                        os.read,
                        self.master_fd,
                        _OUTPUT_CHUNK_BYTES,
                    )
                except OSError as exc:
                    if exc.errno in {errno.EIO, errno.EBADF}:
                        break
                    raise
                if not data:
                    break
                self._emit(
                    "terminal.output",
                    data=base64.b64encode(data).decode("ascii"),
                )
            return_code = await asyncio.to_thread(self.process.wait)
            self._emit("terminal.exited", exit_code=return_code)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            self._emit(
                "terminal.failed",
                message=f"{type(exc).__name__}: {exc}",
            )
        finally:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
            self._ended.set()

    def _emit(self, event_type: str, **payload: object) -> None:
        self._sequence += 1
        event: dict[str, object] = {
            "type": event_type,
            "session_id": self.session_id,
            "sequence": self._sequence,
            **payload,
        }
        self._history.append(event)
        for queue in tuple(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # A disconnected or slow subscriber must not make terminal
                # output an unbounded memory sink.  End only that subscription;
                # clients can reconnect from their last canonical sequence.
                self._subscribers.discard(queue)
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(
                    {
                        "type": "terminal.overflow",
                        "session_id": self.session_id,
                        "sequence": self._sequence,
                    }
                )


class TerminalSessionManager:
    def __init__(
        self,
        *,
        shell_resolver: Callable[[], str] = _default_shell,
        exited_session_retention_seconds: float = _EXITED_SESSION_RETENTION_SECONDS,
    ) -> None:
        if exited_session_retention_seconds < 0:
            raise ValueError("terminal retention must not be negative")
        self._shell_resolver = shell_resolver
        self._exited_session_retention_seconds = exited_session_retention_seconds
        self._sessions: dict[str, TerminalSession] = {}
        self._reap_tasks: dict[str, asyncio.Task[None]] = {}

    async def create(
        self,
        *,
        owner_id: str,
        cwd: Path,
        columns: int = 100,
        rows: int = 30,
    ) -> TerminalSession:
        session_id = f"terminal_{uuid4().hex}"
        session = TerminalSession(
            session_id=session_id,
            owner_id=owner_id,
            cwd=cwd,
            shell=self._shell_resolver(),
            columns=columns,
            rows=rows,
        )
        self._sessions[session_id] = session
        self._reap_tasks[session_id] = asyncio.create_task(
            self._reap_after_exit(session),
            name=f"sage-terminal-reaper:{session_id}",
        )
        return session

    def get(self, session_id: str, owner_id: str) -> TerminalSession:
        session = self._sessions.get(session_id)
        if session is None or session.owner_id != owner_id:
            raise FileNotFoundError("terminal session was not found")
        return session

    async def close_session(self, session_id: str, owner_id: str) -> None:
        session = self.get(session_id, owner_id)
        await session.close()
        self._sessions.pop(session_id, None)
        reaper = self._reap_tasks.pop(session_id, None)
        if reaper is not None and reaper is not asyncio.current_task():
            reaper.cancel()
            await asyncio.gather(reaper, return_exceptions=True)

    async def _reap_after_exit(self, session: TerminalSession) -> None:
        try:
            await session._ended.wait()
            await asyncio.sleep(self._exited_session_retention_seconds)
            if self._sessions.get(session.session_id) is session:
                self._sessions.pop(session.session_id, None)
        finally:
            self._reap_tasks.pop(session.session_id, None)

    async def close(self) -> None:
        sessions = list(self._sessions.values())
        self._sessions.clear()
        reapers = list(self._reap_tasks.values())
        self._reap_tasks.clear()
        for task in reapers:
            task.cancel()
        await asyncio.gather(
            *(session.close() for session in sessions),
            return_exceptions=True,
        )
        await asyncio.gather(*reapers, return_exceptions=True)


__all__ = ["TerminalSession", "TerminalSessionManager"]

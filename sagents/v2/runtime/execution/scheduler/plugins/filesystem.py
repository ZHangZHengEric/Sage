"""Atomic single-host durable Scheduler implementation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)
from sagents.v2.runtime.execution.scheduler.plugins.ephemeral import InMemoryScheduler

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows requires a lock adapter.
    fcntl = None  # type: ignore[assignment]


class SchedulerInUseError(SageV2Error):
    """Another writer already owns this filesystem Scheduler root."""


class FilesystemSchedulerStateStore:
    format = "sage.scheduler-file/v1"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.path = self.root / "scheduler-state.json"
        self._lock = asyncio.Lock()

    def load(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        envelope = json.loads(self.path.read_text(encoding="utf-8"))
        if envelope.get("format") != self.format:
            raise ValueError("unsupported filesystem Scheduler format")
        state = envelope.get("state")
        if not isinstance(state, dict):
            raise ValueError("filesystem Scheduler state is missing")
        if envelope.get("checksum") != self._checksum(state):
            raise ValueError("filesystem Scheduler checksum mismatch")
        return state

    async def save(self, state: dict[str, Any]) -> None:
        async with self._lock:
            await asyncio.to_thread(self._write, state)

    def _write(self, state: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        envelope = {
            "format": self.format,
            "checksum": self._checksum(state),
            "state": state,
        }
        encoded = json.dumps(
            envelope,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        try:
            with temporary.open("wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            descriptor = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _checksum(state: dict[str, Any]) -> str:
        encoded = json.dumps(
            state,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


class FilesystemScheduler(InMemoryScheduler):
    """Persist state across restarts under one enforced writer lease."""

    plugin_id = "sage.scheduler.filesystem"

    def __init__(self, root: str | Path, **kwargs: Any) -> None:
        state_store = FilesystemSchedulerStateStore(root)
        state_store.root.mkdir(parents=True, exist_ok=True)
        self._writer_handle = (state_store.root / ".writer.lock").open("a+b")
        self._acquire_writer_lock(state_store.root)
        try:
            super().__init__(state_store=state_store, **kwargs)
        except BaseException:
            self._release_writer_lock()
            raise

    async def capabilities(self):
        return (await super().capabilities()).model_copy(
            update={"durable_across_process_restart": True}
        )

    async def close(self) -> None:
        await super().close()
        self._release_writer_lock()

    def _acquire_writer_lock(self, root: Path) -> None:
        if fcntl is None:
            self._writer_handle.close()
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="scheduler.lock_unsupported",
                    category=ErrorCategory.UNSUPPORTED_SCHEMA,
                    message="filesystem Scheduler requires an advisory-lock adapter",
                )
            )
        try:
            fcntl.flock(self._writer_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self._writer_handle.close()
            raise SchedulerInUseError(
                RuntimeErrorInfo(
                    code="scheduler.in_use",
                    category=ErrorCategory.CONFLICT,
                    message=f"filesystem Scheduler root is already owned: {root}",
                    safe_to_resume=True,
                )
            ) from exc

    def _release_writer_lock(self) -> None:
        handle = getattr(self, "_writer_handle", None)
        if handle is None or handle.closed:
            return
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


__all__ = [
    "FilesystemScheduler",
    "FilesystemSchedulerStateStore",
    "SchedulerInUseError",
]

"""Ephemeral, session-scoped environment variables for Server agent sandboxes."""

from __future__ import annotations

import asyncio
import heapq
import inspect
import re
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from loguru import logger

from sagents.utils.sandbox.environment import AGENT_PARENT_ENV_ALLOWLIST

RUNTIME_ENV_UNSET: Final = object()
RUNTIME_ENV_IDLE_TTL_SECONDS: Final = 30 * 60
_RUNTIME_ENV_RETRY_SECONDS: Final = 60
_MAX_ENV_COUNT: Final = 64
_MAX_ENV_NAME_BYTES: Final = 128
_MAX_ENV_VALUE_BYTES: Final = 16 * 1024
_MAX_ENV_TOTAL_BYTES: Final = 64 * 1024
_ENV_NAME_PATTERN: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RESERVED_NAMES: Final = frozenset(AGENT_PARENT_ENV_ALLOWLIST).union(
    {
        "HOME",
        "USERPROFILE",
        "PYTHONHOME",
        "NODE_PATH",
        "BASH_ENV",
        "ENV",
    }
)
_RESERVED_PREFIXES: Final = ("LD_", "DYLD_", "SAGE_", "OPENSANDBOX_")


class RuntimeEnvValidationError(ValueError):
    """Raised without embedding a secret value in the error text."""


class RuntimeEnvRevokingError(RuntimeError):
    """The session environment is currently being revoked."""


def validate_runtime_env_vars(value: Mapping[str, object]) -> dict[str, str]:
    """Validate and copy an API-provided runtime environment without logging it."""

    if not isinstance(value, Mapping):
        raise RuntimeEnvValidationError("env_vars must be an object")
    if len(value) > _MAX_ENV_COUNT:
        raise RuntimeEnvValidationError("env_vars contains too many entries")

    result: dict[str, str] = {}
    total_bytes = 0
    for raw_name, raw_value in value.items():
        if not isinstance(raw_name, str) or not isinstance(raw_value, str):
            raise RuntimeEnvValidationError("env_vars names and values must be strings")
        if (
            not _ENV_NAME_PATTERN.fullmatch(raw_name)
            or len(raw_name.encode("utf-8")) > _MAX_ENV_NAME_BYTES
            or raw_name in _RESERVED_NAMES
            or raw_name.startswith(_RESERVED_PREFIXES)
        ):
            raise RuntimeEnvValidationError("env_vars contains a reserved or invalid name")
        if "\0" in raw_value:
            raise RuntimeEnvValidationError("env_vars values cannot contain NUL")

        value_bytes = len(raw_value.encode("utf-8"))
        if value_bytes > _MAX_ENV_VALUE_BYTES:
            raise RuntimeEnvValidationError("env_vars contains an oversized value")
        total_bytes += len(raw_name.encode("utf-8")) + value_bytes
        if total_bytes > _MAX_ENV_TOTAL_BYTES:
            raise RuntimeEnvValidationError("env_vars total size is too large")
        result[raw_name] = raw_value

    return result


RuntimeCleanup = Callable[[str, str, Sequence[str], Sequence[Any]], Awaitable[None]]


@dataclass
class _RuntimeEnvEntry:
    env_vars: dict[str, str] = field(default_factory=dict)
    active_runs: int = 0
    expires_at: float | None = None
    version: int = 0
    revoking: bool = False
    resources: list[Any] = field(default_factory=list)
    related_session_ids: set[str] = field(default_factory=set)


class RuntimeEnvStore:
    """Concurrency-safe in-memory store with one heap-driven expiry task."""

    def __init__(
        self,
        *,
        ttl_seconds: float = RUNTIME_ENV_IDLE_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        cleanup: RuntimeCleanup,
    ) -> None:
        self._ttl_seconds = float(ttl_seconds)
        self._clock = clock
        self._cleanup = cleanup
        self._entries: dict[tuple[str, str], _RuntimeEnvEntry] = {}
        self._expiry_heap: list[tuple[float, int, tuple[str, str]]] = []
        self._lock = asyncio.Lock()
        self._wake = asyncio.Event()
        self._reaper_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._reaper_task and not self._reaper_task.done():
            return
        self._reaper_task = asyncio.create_task(
            self._reaper_loop(), name="runtime-env-reaper"
        )

    async def shutdown(self) -> None:
        task = self._reaper_task
        self._reaper_task = None
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await self.clear_all()

    async def reserve_run(self, owner_id: str, session_id: str) -> None:
        key = self._key(owner_id, session_id)
        async with self._lock:
            entry = self._entries.setdefault(key, _RuntimeEnvEntry())
            if entry.revoking:
                raise RuntimeEnvRevokingError("runtime environment is being revoked")
            entry.active_runs += 1
            entry.expires_at = None
            entry.version += 1
            self._wake.set()

    async def resolve_for_run(
        self,
        owner_id: str,
        session_id: str,
        update: object = RUNTIME_ENV_UNSET,
    ) -> dict[str, str]:
        key = self._key(owner_id, session_id)
        resources: tuple[Any, ...] = ()
        related_session_ids: tuple[str, ...] = ()
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None or entry.active_runs <= 0:
                raise RuntimeError("runtime environment run was not reserved")
            if entry.revoking:
                raise RuntimeEnvRevokingError("runtime environment is being revoked")
            if update is not RUNTIME_ENV_UNSET:
                resources = tuple(entry.resources)
                related_session_ids = tuple(
                    sorted(entry.related_session_ids.union({session_id}))
                )
                if resources:
                    entry.revoking = True
                entry.version += 1
            else:
                return dict(entry.env_vars)

        if resources:
            try:
                await self._cleanup(
                    owner_id, session_id, related_session_ids, resources
                )
            except Exception:
                async with self._lock:
                    current = self._entries.get(key)
                    if current is not None:
                        current.revoking = False
                raise

        async with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                raise RuntimeError("runtime environment run was removed")
            entry.resources.clear()
            entry.related_session_ids.clear()
            entry.env_vars = dict(update)  # type: ignore[arg-type]
            entry.revoking = False
            return dict(entry.env_vars)

    async def finish_run(self, owner_id: str, session_id: str) -> None:
        key = self._key(owner_id, session_id)
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return
            entry.active_runs = max(0, entry.active_runs - 1)
            if entry.active_runs:
                return
            if not entry.env_vars and not entry.resources:
                self._entries.pop(key, None)
                return
            entry.version += 1
            entry.expires_at = self._clock() + self._ttl_seconds
            heapq.heappush(
                self._expiry_heap,
                (entry.expires_at, entry.version, key),
            )
            self._wake.set()

    async def register_resource(
        self,
        owner_id: str,
        session_id: str,
        resource: Any,
        *,
        resource_session_id: str | None = None,
    ) -> None:
        key = self._key(owner_id, session_id)
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None or not entry.env_vars:
                return
            if all(existing is not resource for existing in entry.resources):
                entry.resources.append(resource)
            if resource_session_id:
                entry.related_session_ids.add(str(resource_session_id))

    async def get_snapshot(self, owner_id: str, session_id: str) -> dict[str, str]:
        key = self._key(owner_id, session_id)
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None or entry.revoking:
                return {}
            return dict(entry.env_vars)

    async def clear_session(self, owner_id: str, session_id: str) -> bool:
        return await self._revoke(self._key(owner_id, session_id), force=True)

    async def clear_session_for_any_owner(self, session_id: str) -> int:
        async with self._lock:
            keys = [key for key in self._entries if key[1] == session_id]
        cleared = 0
        for key in keys:
            if await self._revoke(key, force=True):
                cleared += 1
        return cleared

    async def clear_all(self) -> None:
        async with self._lock:
            keys = list(self._entries)
        for key in keys:
            await self._revoke(key, force=True)

    async def expire_due(self) -> int:
        now = self._clock()
        async with self._lock:
            keys = []
            while self._expiry_heap and self._expiry_heap[0][0] <= now:
                expires_at, version, key = heapq.heappop(self._expiry_heap)
                entry = self._entries.get(key)
                if (
                    entry is None
                    or entry.version != version
                    or entry.expires_at != expires_at
                    or entry.active_runs
                    or entry.revoking
                ):
                    continue
                keys.append(key)

        expired = 0
        for key in keys:
            if await self._revoke(key, force=False):
                expired += 1
        return expired

    async def _revoke(self, key: tuple[str, str], *, force: bool) -> bool:
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return False
            if entry.revoking or (entry.active_runs and not force):
                return False
            entry.revoking = True
            entry.version += 1
            version = entry.version
            resources = tuple(entry.resources)
            related_session_ids = tuple(
                sorted(entry.related_session_ids.union({key[1]}))
            )

        owner_id, session_id = key
        try:
            await self._cleanup(
                owner_id, session_id, related_session_ids, resources
            )
        except Exception as exc:
            logger.bind(session_id=session_id).warning(
                f"Runtime env cleanup failed; retry scheduled: {type(exc).__name__}"
            )
            async with self._lock:
                current = self._entries.get(key)
                if current is not None and current.version == version:
                    current.revoking = False
                    current.version += 1
                    current.expires_at = self._clock() + _RUNTIME_ENV_RETRY_SECONDS
                    heapq.heappush(
                        self._expiry_heap,
                        (current.expires_at, current.version, key),
                    )
                    self._wake.set()
            return False

        async with self._lock:
            current = self._entries.get(key)
            if current is not None and current.version == version:
                self._entries.pop(key, None)
        logger.bind(session_id=session_id).info("Runtime env cleaned")
        return True

    async def _reaper_loop(self) -> None:
        while True:
            self._wake.clear()
            delay = await self._next_delay()
            if delay is None:
                await self._wake.wait()
                continue
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=delay)
            except asyncio.TimeoutError:
                await self.expire_due()

    async def _next_delay(self) -> float | None:
        async with self._lock:
            while self._expiry_heap:
                expires_at, version, key = self._expiry_heap[0]
                entry = self._entries.get(key)
                if (
                    entry is None
                    or entry.version != version
                    or entry.expires_at != expires_at
                ):
                    heapq.heappop(self._expiry_heap)
                    continue
                return max(0.0, expires_at - self._clock())
            return None

    @staticmethod
    def _key(owner_id: str, session_id: str) -> tuple[str, str]:
        owner = str(owner_id or "").strip()
        session = str(session_id or "").strip()
        if not owner or not session:
            raise ValueError("owner_id and session_id are required")
        return owner, session


async def _cleanup_runtime_resources(
    owner_id: str,
    session_id: str,
    related_session_ids: Sequence[str],
    resources: Sequence[Any],
) -> None:
    del owner_id
    from sagents.session_runtime import get_global_session_manager
    from sagents.tool.impl.execute_command_tool import ExecuteCommandTool

    for related_session_id in related_session_ids:
        await ExecuteCommandTool.cleanup_session_background_tasks(related_session_id)
    for resource in resources:
        cleanup = getattr(resource, "kill", None) or getattr(resource, "cleanup", None)
        if cleanup is None:
            continue
        result = cleanup()
        if inspect.isawaitable(result):
            await result
    manager = get_global_session_manager()
    for related_session_id in related_session_ids:
        session = manager.get_live_session(related_session_id)
        context = getattr(session, "session_context", None)
        if context is not None and context.sandbox in resources:
            context.sandbox = None


_runtime_env_store = RuntimeEnvStore(cleanup=_cleanup_runtime_resources)


def get_runtime_env_store() -> RuntimeEnvStore:
    return _runtime_env_store


async def start_runtime_env_service() -> None:
    await _runtime_env_store.start()


async def shutdown_runtime_env_service() -> None:
    await _runtime_env_store.shutdown()

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import re
import time


_CLIENT_ID = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


@dataclass(frozen=True, slots=True)
class SidecarLeaseResult:
    active_clients: int
    shutdown_requested: bool = False


class SidecarClientLeases:
    """Track Desktop clients so one window cannot stop a shared sidecar.

    Leases deliberately live in the sidecar process. A client refreshes its
    lease periodically; crashed clients disappear after ``ttl_seconds``. Once
    the final client detaches or expires, the registry enters a closing state
    and asks the Uvicorn host to shut down gracefully.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = 30.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("sidecar client lease TTL must be positive")
        self.ttl_seconds = ttl_seconds
        self._monotonic = monotonic
        self._unclaimed_deadline = monotonic() + ttl_seconds
        self._clients: dict[str, float] = {}
        self._ever_attached = False
        self._closing = False
        self._lock = asyncio.Lock()

    async def attach(self, client_id: str) -> SidecarLeaseResult:
        self._validate_client_id(client_id)
        async with self._lock:
            if self._closing:
                raise RuntimeError("Desktop sidecar is shutting down")
            now = self._monotonic()
            self._prune_locked(now)
            self._clients[client_id] = now + self.ttl_seconds
            self._ever_attached = True
            return SidecarLeaseResult(active_clients=len(self._clients))

    async def detach(self, client_id: str) -> SidecarLeaseResult:
        self._validate_client_id(client_id)
        async with self._lock:
            self._prune_locked(self._monotonic())
            self._clients.pop(client_id, None)
            should_shutdown = self._request_shutdown_if_empty_locked()
            return SidecarLeaseResult(
                active_clients=len(self._clients),
                shutdown_requested=should_shutdown,
            )

    async def request_shutdown_if_idle(self) -> SidecarLeaseResult:
        async with self._lock:
            self._prune_locked(self._monotonic())
            should_shutdown = self._request_shutdown_if_empty_locked(
                require_prior_client=False
            )
            return SidecarLeaseResult(
                active_clients=len(self._clients),
                shutdown_requested=should_shutdown,
            )

    async def expire(self) -> SidecarLeaseResult:
        async with self._lock:
            now = self._monotonic()
            self._prune_locked(now)
            should_shutdown = self._request_shutdown_if_empty_locked(
                require_prior_client=now < self._unclaimed_deadline
            )
            return SidecarLeaseResult(
                active_clients=len(self._clients),
                shutdown_requested=should_shutdown,
            )

    async def watch(
        self,
        request_shutdown: Callable[[], None],
        *,
        poll_interval_seconds: float | None = None,
    ) -> None:
        interval = poll_interval_seconds or min(5.0, self.ttl_seconds / 3)
        if interval <= 0:
            raise ValueError("sidecar lease poll interval must be positive")
        while True:
            await asyncio.sleep(interval)
            result = await self.expire()
            if result.shutdown_requested:
                request_shutdown()
                return

    def _request_shutdown_if_empty_locked(
        self, *, require_prior_client: bool = True
    ) -> bool:
        if self._closing or self._clients:
            return False
        if require_prior_client and not self._ever_attached:
            return False
        self._closing = True
        return True

    def _prune_locked(self, now: float) -> None:
        expired = [
            client_id
            for client_id, deadline in self._clients.items()
            if deadline <= now
        ]
        for client_id in expired:
            self._clients.pop(client_id, None)

    @staticmethod
    def _validate_client_id(client_id: str) -> None:
        if not _CLIENT_ID.fullmatch(client_id):
            raise ValueError("invalid Desktop sidecar client id")


__all__ = ["SidecarClientLeases", "SidecarLeaseResult"]

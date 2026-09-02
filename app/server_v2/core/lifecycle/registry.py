from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class AsyncResource(Protocol):
    name: str

    async def start(self) -> None: ...

    async def ready(self) -> bool: ...

    async def stop(self) -> None: ...


class LifecycleState(StrEnum):
    NEW = "new"
    STARTING = "starting"
    READY = "ready"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ResourceReadiness:
    ready: bool
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    ready: bool
    state: LifecycleState
    resources: dict[str, ResourceReadiness]


class ResourceRegistry:
    def __init__(
        self,
        resources: Sequence[AsyncResource],
        *,
        probe_timeout_seconds: float,
        start_timeout_seconds: float = 30,
        stop_timeout_seconds: float = 30,
    ) -> None:
        if probe_timeout_seconds <= 0:
            raise ValueError("resource probe timeout must be positive")
        if start_timeout_seconds <= 0:
            raise ValueError("resource start timeout must be positive")
        if stop_timeout_seconds <= 0:
            raise ValueError("resource stop timeout must be positive")
        self._resources = tuple(resources)
        self._started: list[AsyncResource] = []
        self._probe_timeout_seconds = probe_timeout_seconds
        self._start_timeout_seconds = start_timeout_seconds
        self._stop_timeout_seconds = stop_timeout_seconds
        self._operation_lock = asyncio.Lock()
        self._state_lock = asyncio.Lock()
        self.state = LifecycleState.NEW

    async def start(self) -> None:
        async with self._operation_lock:
            async with self._state_lock:
                if self.state is not LifecycleState.NEW:
                    raise RuntimeError(f"cannot start from state {self.state.value}")
                self.state = LifecycleState.STARTING
            try:
                async with asyncio.timeout(self._start_timeout_seconds):
                    for resource in self._resources:
                        async with self._state_lock:
                            self._started.append(resource)
                        await resource.start()
            except BaseException as start_error:
                await self._set_state(LifecycleState.FAILED)
                cleanup_errors, cleanup_timed_out = await self._stop_started()
                if cleanup_timed_out:
                    cleanup_errors.append(TimeoutError("resource startup cleanup timed out"))
                if cleanup_errors:
                    raise BaseExceptionGroup(
                        "resource startup and cleanup failed",
                        [start_error, *cleanup_errors],
                    ) from None
                raise
            await self._set_state(LifecycleState.READY)

    async def stop(self) -> None:
        async with self._operation_lock:
            async with self._state_lock:
                if self.state in {LifecycleState.NEW, LifecycleState.STOPPED}:
                    self.state = LifecycleState.STOPPED
                    return
                self.state = LifecycleState.STOPPING
            try:
                errors, timed_out = await self._stop_started()
            except BaseException:
                await self._set_state(LifecycleState.FAILED)
                raise
            if timed_out or errors:
                await self._set_state(LifecycleState.FAILED)
            else:
                await self._set_state(LifecycleState.STOPPED)
            if timed_out:
                timeout_error = TimeoutError("resource shutdown timed out")
                if errors:
                    raise ExceptionGroup(
                        "resource shutdown failed",
                        [*errors, timeout_error],
                    )
                raise timeout_error
            if errors:
                raise ExceptionGroup("resource shutdown failed", errors)

    async def readiness(self) -> ReadinessReport:
        async with self._state_lock:
            if self.state is not LifecycleState.READY:
                return ReadinessReport(False, self.state, {})
            started = tuple(self._started)
        probes = await asyncio.gather(*(self._probe(resource) for resource in started))
        async with self._state_lock:
            if self.state is not LifecycleState.READY:
                return ReadinessReport(False, self.state, {})
            resources = {resource.name: probe for resource, probe in zip(started, probes, strict=True)}
            return ReadinessReport(
                all(probe.ready for probe in probes),
                self.state,
                resources,
            )

    async def _stop_started(self) -> tuple[list[Exception], bool]:
        errors: list[Exception] = []
        deadline = asyncio.get_running_loop().time() + self._stop_timeout_seconds
        async with self._state_lock:
            started = tuple(self._started)
        for resource in reversed(started):
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return errors, True
            timeout = asyncio.timeout(remaining)
            try:
                async with timeout:
                    await resource.stop()
            except TimeoutError as error:
                if timeout.expired():
                    return errors, True
                errors.append(error)
            except Exception as error:
                errors.append(error)
            else:
                await self._remove_started(resource)
        return errors, False

    async def _remove_started(self, resource: AsyncResource) -> None:
        async with self._state_lock:
            for index in range(len(self._started) - 1, -1, -1):
                if self._started[index] is resource:
                    self._started.pop(index)
                    return

    async def _set_state(self, state: LifecycleState) -> None:
        async with self._state_lock:
            self.state = state

    async def _probe(self, resource: AsyncResource) -> ResourceReadiness:
        try:
            healthy = await asyncio.wait_for(
                resource.ready(),
                timeout=self._probe_timeout_seconds,
            )
        except TimeoutError:
            return ResourceReadiness(False, "probe timeout")
        except Exception as error:
            return ResourceReadiness(False, f"{type(error).__name__}: {error}")
        return ResourceReadiness(
            healthy,
            None if healthy else "resource reported unhealthy",
        )

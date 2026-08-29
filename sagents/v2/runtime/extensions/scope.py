"""Scoped extension instances and deterministic teardown."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any

from sagents.v2.runtime.extensions.contracts import ExtensionRegistration, StopReason
from sagents.v2.runtime.extensions.resolver import ResolvedExtensionGraph


class ExtensionStopError(RuntimeError):
    """Report every teardown failure without requiring Python 3.11 groups."""

    def __init__(self, errors: tuple[Exception, ...]) -> None:
        self.errors = errors
        super().__init__(f"{len(errors)} extension(s) failed to stop")


@dataclass
class StartedExtension:
    registration: ExtensionRegistration
    instance: Any


@dataclass
class ExtensionScopeHandle:
    graph: ResolvedExtensionGraph
    providers: dict[str, Any]
    _started: list[StartedExtension]
    _closed: bool = False

    async def close(self, reason: StopReason = StopReason.SCOPE_CLOSED) -> None:
        if self._closed:
            return
        errors = []
        for value in reversed(self._started):
            try:
                if value.registration.stop is not None:
                    result = value.registration.stop(value.instance, reason)
                else:
                    stop = getattr(value.instance, "stop", None)
                    result = stop(reason) if stop is not None else None
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:
                errors.append(exc)
        self._closed = True
        if errors:
            raise ExtensionStopError(tuple(errors)) from errors[0]

    async def __aenter__(self) -> "ExtensionScopeHandle":
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        await self.close()

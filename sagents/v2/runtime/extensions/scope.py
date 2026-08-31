"""Scoped extension instances and deterministic teardown."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any

from sagents.v2.runtime.extensions.contracts import (
    ExtensionRegistration,
    ExtensionScopeContext,
    ProviderSet,
    StopReason,
)
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
    context: ExtensionScopeContext
    providers: ProviderSet
    _started: list[StartedExtension]
    parent: "ExtensionScopeHandle | None" = None
    composition_hash: str = ""
    _owned_ancestors: tuple["ExtensionScopeHandle", ...] = ()
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
                    if stop is not None:
                        result = stop(reason)
                    else:
                        close = getattr(value.instance, "close", None)
                        result = close() if close is not None else None
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:
                errors.append(exc)
        for handle in reversed(self._owned_ancestors):
            try:
                await handle.close(reason)
            except Exception as exc:
                errors.append(exc)
        self._closed = True
        if errors:
            raise ExtensionStopError(tuple(errors)) from errors[0]

    async def __aenter__(self) -> "ExtensionScopeHandle":
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        await self.close()

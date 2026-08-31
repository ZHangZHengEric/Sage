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
        pending_started = list(reversed(self._started))
        for index, value in enumerate(pending_started):
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
                # Do not tear down dependencies below a component whose stop
                # failed. Keep the failure and all unattempted components for
                # an ordered retry.
                self._started = list(reversed(pending_started[index:]))
                break
        else:
            self._started = []
        if not self._started:
            pending_ancestors = list(reversed(self._owned_ancestors))
            for index, handle in enumerate(pending_ancestors):
                try:
                    await handle.close(reason)
                except Exception as exc:
                    errors.append(exc)
                    self._owned_ancestors = tuple(
                        reversed(pending_ancestors[index:])
                    )
                    break
            else:
                self._owned_ancestors = ()
        self._closed = not self._started and not self._owned_ancestors
        if errors:
            raise ExtensionStopError(tuple(errors)) from errors[0]

    async def __aenter__(self) -> "ExtensionScopeHandle":
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        await self.close()

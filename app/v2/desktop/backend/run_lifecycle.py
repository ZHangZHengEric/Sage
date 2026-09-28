from __future__ import annotations

import asyncio
from contextvars import ContextVar
import inspect
from pathlib import Path
from typing import Any

from sagents.v2.contracts.principals import RequestContext
from sagents.v2.runtime.execution import ExecutionResourceState


ACTIVE_EXTENSION_SCOPE_HANDLES: ContextVar[list[Any] | None] = ContextVar(
    "desktop_v2_active_extension_scope_handles",
    default=None,
)


class DesktopRunResources:
    """Close Run scopes before their sandbox, retaining only failed resources."""

    def __init__(self, sandbox_handle, scope_handles, lifecycle=None) -> None:
        self.sandbox_handle = sandbox_handle
        self.scope_handles = scope_handles
        self.lifecycle = lifecycle
        self._closed = False
        self._sandbox_closed = False
        self._close_lock = asyncio.Lock()
        self.defer_close = False

    def __getattr__(self, name):
        return getattr(self.sandbox_handle, name)

    async def close(self) -> None:
        if self.defer_close:
            return
        await self.close_now()

    async def close_now(self) -> None:
        async with self._close_lock:
            if self._closed:
                return
            errors: list[BaseException] = []
            failed_handles: list[Any] = []
            for handle in reversed(self.scope_handles):
                try:
                    await handle.close()
                except BaseException as exc:
                    errors.append(exc)
                    failed_handles.append(handle)
            self.scope_handles[:] = reversed(failed_handles)
            if not self.scope_handles and not self._sandbox_closed:
                try:
                    await self.sandbox_handle.close()
                except BaseException as exc:
                    errors.append(exc)
                else:
                    self._sandbox_closed = True
            self._closed = not self.scope_handles and self._sandbox_closed
            if errors:
                raise errors[0]


class DesktopDriver:
    """Lazily compose and own one Desktop Run execution binding."""

    def __init__(
        self,
        service: Any,
        loop,
        workspace: Path,
        sandbox_handle,
        lazy_builder=None,
    ) -> None:
        self.service = service
        self.loop = loop
        self.workspace = workspace
        self.sandbox_handle = sandbox_handle
        self._lazy_builder = lazy_builder
        self._compose_lock = asyncio.Lock()
        self._binding_closed = False
        self._controller_closed = False
        self._sandbox_binding_closed = False
        self._binding_close_lock = asyncio.Lock()
        self._binding_close_task: asyncio.Task[None] | None = None

    async def execute(self, run_id: str, context: RequestContext):
        await self._ensure_composed()
        token = ACTIVE_EXTENSION_SCOPE_HANDLES.set(self.sandbox_handle.scope_handles)
        try:
            return await self.loop.execute(run_id, context)
        finally:
            ACTIVE_EXTENSION_SCOPE_HANDLES.reset(token)

    async def resume(self, run_id: str, context: RequestContext):
        await self._ensure_composed()
        token = ACTIVE_EXTENSION_SCOPE_HANDLES.set(self.sandbox_handle.scope_handles)
        try:
            return await self.loop.resume(run_id, context)
        finally:
            ACTIVE_EXTENSION_SCOPE_HANDLES.reset(token)

    async def _ensure_composed(self) -> None:
        if self.loop is not None:
            return
        async with self._compose_lock:
            if self.loop is not None:
                return
            if self._lazy_builder is None:
                raise RuntimeError("Desktop driver has no composition builder")
            _resolved, loop, sandbox_handle = await self._lazy_builder()
            self.loop = loop
            self.sandbox_handle = sandbox_handle

    async def on_suspended(self, context: RequestContext) -> None:
        lifecycle = getattr(self.sandbox_handle, "lifecycle", None)
        if lifecycle is not None:
            record = await lifecycle.suspend(
                run_id=self.sandbox_handle.ref.owner_run_id,
                context=context,
            )
            if record is not None and self.service is not None:
                log = (
                    self.service.logger.warning
                    if record.state == ExecutionResourceState.RELEASE_FAILED
                    else self.service.logger.info
                )
                log(
                    "sandbox.lifecycle_settled",
                    "Sandbox suspension lifecycle settled",
                    attributes={
                        "run_id": record.run_id,
                        "generation": record.generation,
                        "state": record.state.value,
                        "disposition": (
                            record.release_disposition.value
                            if record.release_disposition is not None
                            else None
                        ),
                        "compute_released": record.compute_released,
                        "blocking_job_count": len(record.blocking_job_ids),
                        "blocking_child_run_count": len(record.blocking_child_run_ids),
                        "retry_count": record.retry_count,
                    },
                )
            if (
                record is not None
                and record.state == ExecutionResourceState.RELEASE_BLOCKED
                and record.blocking_job_ids
            ):
                self.sandbox_handle.defer_close = True
                self.service._schedule_blocked_sandbox_cleanup(
                    self.sandbox_handle, lifecycle, record, context
                )

    async def close_binding(self) -> None:
        async with self._binding_close_lock:
            if self._binding_closed:
                return
            if self._binding_close_task is None:
                self._binding_close_task = asyncio.create_task(
                    self._close_binding_once()
                )
            close_task = self._binding_close_task
        try:
            await asyncio.shield(close_task)
        except BaseException:
            if close_task.done():
                async with self._binding_close_lock:
                    if self._binding_close_task is close_task:
                        self._binding_close_task = None
            raise
        async with self._binding_close_lock:
            if self._binding_close_task is close_task:
                self._binding_closed = True

    async def close(self) -> None:
        """Release all Run-scoped resources at terminal or suspension boundary."""

        await self.close_binding()

    async def _close_binding_once(self) -> None:
        if self.sandbox_handle is None:
            return
        controller = getattr(self.loop, "delegated_run_controller", None)
        controller_close = getattr(controller, "close", None)
        controller_error: BaseException | None = None
        if controller_close is not None and not self._controller_closed:
            try:
                closed = controller_close()
                if inspect.isawaitable(closed):
                    await closed
            except BaseException as exc:
                controller_error = exc
            else:
                self._controller_closed = True
        else:
            self._controller_closed = True
        if not self._sandbox_binding_closed:
            try:
                await self.sandbox_handle.close()
            except BaseException as sandbox_error:
                if controller_error is not None:
                    raise sandbox_error from controller_error
                raise
            else:
                self._sandbox_binding_closed = True
        if controller_error is not None:
            raise controller_error


__all__ = [
    "ACTIVE_EXTENSION_SCOPE_HANDLES",
    "DesktopDriver",
    "DesktopRunResources",
]

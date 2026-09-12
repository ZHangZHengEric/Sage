"""Cleanup of process-local Run pins, including repeated observer cancellation."""

from __future__ import annotations

import asyncio


async def finish_fence(
    condition: asyncio.Condition, pinned: set[str], run_id: str
) -> None:
    async def release() -> None:
        async with condition:
            pinned.discard(run_id)
            condition.notify_all()

    # A second cancel while waiting for Scheduler persistence must not leave
    # the pin behind and permanently block cancellation, claims or shutdown.
    cleanup = asyncio.create_task(release())
    cancelled = False
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            cancelled = True
    cleanup.result()
    if cancelled:
        raise asyncio.CancelledError

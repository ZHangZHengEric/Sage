from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

from loguru import logger

from ..user_context import DEFAULT_DESKTOP_USER_ID
from .browser_bridge import BrowserBridgeHub
from .browser_tools import BrowserBridgeTool


CHECK_INTERVAL_SECONDS = 5.0
OFFLINE_GRACE_SECONDS = 60.0


class BrowserCapabilityCoordinator:
    """
    Tracks browser extension liveness and logs online/offline transitions.
    """

    def __init__(self, user_id: str = DEFAULT_DESKTOP_USER_ID) -> None:
        self.user_id = user_id
        self.hub = BrowserBridgeHub.get_instance()
        self._task: Optional[asyncio.Task] = None
        self._wake_event = asyncio.Event()
        self._current_online: Optional[bool] = None

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop(), name="browser_capability_coordinator")
        logger.info("[BrowserCapability] coordinator started")

    async def stop(self) -> None:
        if not self._task:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        logger.info("[BrowserCapability] coordinator stopped")

    def notify_activity(self) -> None:
        self._wake_event.set()

    async def _loop(self) -> None:
        try:
            while True:
                await self._sync_once()
                self._wake_event.clear()
                try:
                    await asyncio.wait_for(self._wake_event.wait(), timeout=CHECK_INTERVAL_SECONDS)
                except asyncio.TimeoutError:
                    pass
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(f"[BrowserCapability] coordinator loop error: {exc}")

    async def _sync_once(self) -> None:
        status = await self.hub.get_status(self.user_id)
        last_seen_at = float(status.get("last_seen_at") or 0.0)
        ttl = float(status.get("heartbeat_ttl_seconds") or 45.0)
        online = False
        if last_seen_at > 0:
            online = (time.time() - last_seen_at) <= (ttl + OFFLINE_GRACE_SECONDS)

        if self._current_online is None:
            self._current_online = online
            logger.info(f"[BrowserCapability] initialized state online={online}")
            return

        if online == self._current_online:
            return

        self._current_online = online
        if online:
            logger.info("[BrowserCapability] transition offline -> online")
        else:
            logger.info("[BrowserCapability] transition online -> offline")


_COORDINATOR: Optional[BrowserCapabilityCoordinator] = None


def get_browser_capability_coordinator() -> BrowserCapabilityCoordinator:
    global _COORDINATOR
    if _COORDINATOR is None:
        _COORDINATOR = BrowserCapabilityCoordinator()
    return _COORDINATOR


async def get_browser_tool_sync_state(
    user_id: str = DEFAULT_DESKTOP_USER_ID,
) -> dict[str, Any]:
    """
    Return browser extension liveness plus the browser tools that should be
    considered available to the current chat request/UI state.
    """
    hub = BrowserBridgeHub.get_instance()
    status = await hub.get_status(user_id)

    last_seen_at = float(status.get("last_seen_at") or 0.0)
    ttl = float(status.get("heartbeat_ttl_seconds") or 45.0)
    browser_tools_online = False
    if last_seen_at > 0:
        browser_tools_online = (time.time() - last_seen_at) <= (ttl + OFFLINE_GRACE_SECONDS)

    reported_capabilities = status.get("capabilities") or []
    if isinstance(reported_capabilities, list) and reported_capabilities:
        supported_tools = [
            tool_name
            for tool_name in BrowserBridgeTool.TOOL_NAMES
            if tool_name in reported_capabilities
        ]
    else:
        supported_tools = list(BrowserBridgeTool.TOOL_NAMES)

    return {
        **status,
        "browser_tools_online": browser_tools_online,
        "browser_tools": supported_tools,
        "browser_tool_class_tools": list(BrowserBridgeTool.TOOL_NAMES),
    }

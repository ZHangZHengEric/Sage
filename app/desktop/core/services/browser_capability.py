from __future__ import annotations

import asyncio
import time
from typing import Optional

from loguru import logger
from sagents.tool import get_tool_manager
from sagents.tool.tool_schema import ToolSpec

from ..user_context import DEFAULT_DESKTOP_USER_ID
from .browser_bridge import BrowserBridgeHub
from .browser_tools import BrowserBridgeTool


CHECK_INTERVAL_SECONDS = 5.0
OFFLINE_GRACE_SECONDS = 60.0


class BrowserCapabilityCoordinator:
    """
    Coordinates dynamic browser tool registration with lease-based liveness.
    It updates ToolManager only on online/offline edge transitions.
    """

    def __init__(self, user_id: str = DEFAULT_DESKTOP_USER_ID) -> None:
        self.user_id = user_id
        self.hub = BrowserBridgeHub.get_instance()
        self._task: Optional[asyncio.Task] = None
        self._wake_event = asyncio.Event()
        self._current_online: Optional[bool] = None
        self._tool_instance: Optional[BrowserBridgeTool] = None
        self._tool_names = set(BrowserBridgeTool.TOOL_NAMES)

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
            if online:
                self._activate_tools()
            else:
                self._deactivate_tools()
            logger.info(f"[BrowserCapability] initialized state online={online}")
            return

        if online == self._current_online:
            return

        self._current_online = online
        if online:
            self._activate_tools()
            logger.info("[BrowserCapability] transition offline -> online")
        else:
            self._deactivate_tools()
            logger.info("[BrowserCapability] transition online -> offline")

    def _activate_tools(self) -> None:
        tm = get_tool_manager()
        if not tm:
            logger.warning("[BrowserCapability] ToolManager is unavailable, skip activation")
            return
        if self._tool_instance is None:
            self._tool_instance = BrowserBridgeTool(user_id=self.user_id)
        tm.register_tools_from_object(self._tool_instance)

    def _deactivate_tools(self) -> None:
        tm = get_tool_manager()
        if not tm:
            return
        for tool_name in list(tm.tools.keys()):
            if tool_name not in self._tool_names:
                continue
            spec = tm.tools.get(tool_name)
            if not isinstance(spec, ToolSpec):
                continue
            # Guard: only remove our tool implementations.
            func = getattr(spec, "func", None)
            if not func:
                continue
            if getattr(func, "__module__", "") != "app.desktop.core.services.browser_tools":
                continue
            del tm.tools[tool_name]


_COORDINATOR: Optional[BrowserCapabilityCoordinator] = None


def get_browser_capability_coordinator() -> BrowserCapabilityCoordinator:
    global _COORDINATOR
    if _COORDINATOR is None:
        _COORDINATOR = BrowserCapabilityCoordinator()
    return _COORDINATOR


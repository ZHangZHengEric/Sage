from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

from loguru import logger

from ..user_context import DEFAULT_DESKTOP_USER_ID
from .browser_bridge import BrowserBridgeHub, PING_ACTION
from .browser_tools import BrowserBridgeTool


CHECK_INTERVAL_SECONDS = 5.0
# 不再额外加宽限：BrowserBridgeHub.HEARTBEAT_TTL_SECONDS 本身已经覆盖一次心跳间隔
OFFLINE_GRACE_SECONDS = 0.0
# 主动探活时等待扩展响应 ping 的超时时间。需大于扩展端长轮询的最长往返。
PROBE_TIMEOUT_SECONDS = 5.0


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

    Important contract:
    - `browser_tools` 仅在扩展确实在线时才会包含工具名；扩展未连接/已离线时返回 `[]`，
      避免把所有浏览器工具误注入到 agent 的 available_tools。
    - `browser_tool_class_tools` 始终是「这一类工具的全集」，仅供前端展示。
    """
    hub = BrowserBridgeHub.get_instance()
    status = await hub.get_status(user_id)

    last_seen_at = float(status.get("last_seen_at") or 0.0)
    ttl = float(status.get("heartbeat_ttl_seconds") or 45.0)
    browser_tools_online = False
    if last_seen_at > 0:
        browser_tools_online = (time.time() - last_seen_at) <= (ttl + OFFLINE_GRACE_SECONDS)

    if browser_tools_online:
        reported_capabilities = status.get("capabilities") or []
        if isinstance(reported_capabilities, list) and reported_capabilities:
            supported_tools = [
                tool_name
                for tool_name in BrowserBridgeTool.TOOL_NAMES
                if tool_name in reported_capabilities
            ]
        else:
            # 扩展在线但未上报 capabilities，按全集处理（向后兼容旧版扩展）
            supported_tools = list(BrowserBridgeTool.TOOL_NAMES)
    else:
        # 扩展从未连接 / 已离线：必须返回空，否则会被注入到 chat 请求中
        supported_tools = []

    return {
        **status,
        "browser_tools_online": browser_tools_online,
        "browser_tools": supported_tools,
        "browser_tool_class_tools": list(BrowserBridgeTool.TOOL_NAMES),
    }


async def probe_extension(
    user_id: str = DEFAULT_DESKTOP_USER_ID,
    *,
    timeout_seconds: float = PROBE_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """主动探活：入队一个 `ping` 命令，等待扩展回包。

    - 扩展在线（连续长轮询）→ 几乎立即返回 `online=True`，并刷新 `last_seen_at`。
    - 扩展掉线/挂起 → 等待 `timeout_seconds` 后超时，强制把状态置为离线再返回。
      这样用户点击「重新检测」时不会被陈旧心跳误导，AgentEdit 的 5s 轮询也会立刻
      看到离线状态并禁用浏览器工具。

    返回值与 `get_browser_tool_sync_state` 同 schema，并额外包含 `probe`：
      {"latency_ms": int|None, "timed_out": bool, "forced_offline": bool}
    """
    hub = BrowserBridgeHub.get_instance()
    started_at = time.monotonic()

    command = await hub.enqueue_command(user_id=user_id, action=PING_ACTION, args={})
    command_id = command.get("command_id", "")
    result = await hub.wait_command_result(
        command_id=command_id,
        timeout_seconds=max(0.5, float(timeout_seconds)),
    )
    elapsed_ms = int((time.monotonic() - started_at) * 1000)

    if result is None:
        # 探活超时：强制标记离线，让前端立刻看到 offline
        await hub.force_offline(user_id)
        state = await get_browser_tool_sync_state(user_id)
        state["probe"] = {
            "latency_ms": None,
            "timed_out": True,
            "forced_offline": True,
        }
        logger.info(
            f"[BrowserCapability] probe timeout user_id={user_id}, command_id={command_id}, forced offline"
        )
        return state

    # 拿到响应即认为扩展在线，刷新 last_seen_at（capabilities 走下一次心跳更新）
    await hub.heartbeat(user_id=user_id)
    state = await get_browser_tool_sync_state(user_id)
    state["probe"] = {
        "latency_ms": elapsed_ms,
        "timed_out": False,
        "forced_offline": False,
    }
    logger.info(
        f"[BrowserCapability] probe ok user_id={user_id}, command_id={command_id}, latency={elapsed_ms}ms"
    )
    return state

from __future__ import annotations

import asyncio
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any


HEARTBEAT_TTL_SECONDS = 75.0  # Chrome 扩展心跳每 30s 一次，给两次心跳 + 一点抖动余量

# 用户主动点击「重新检测」时，后端入队此 action 探活，扩展端必须立即响应
PING_ACTION = "ping"


@dataclass
class PendingCommand:
    id: str
    action: str
    args: dict[str, Any]
    created_at: float


class BrowserBridgeHub:
    """In-memory bridge between local browser extension and desktop backend."""

    _instance: "BrowserBridgeHub | None" = None

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._states: dict[str, dict[str, Any]] = {}
        self._command_queues: dict[str, deque[PendingCommand]] = defaultdict(deque)
        self._queue_events: dict[str, asyncio.Event] = defaultdict(asyncio.Event)
        self._command_results: dict[str, dict[str, Any]] = {}
        self._result_waiters: dict[str, asyncio.Future] = {}

    @classmethod
    def get_instance(cls) -> "BrowserBridgeHub":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def heartbeat(
        self,
        *,
        user_id: str,
        extension_id: str | None = None,
        extension_version: str | None = None,
        active_tab: dict[str, Any] | None = None,
        page_context: dict[str, Any] | None = None,
        capabilities: list[str] | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        async with self._lock:
            state = self._states.get(user_id, {})
            state.update(
                {
                    "user_id": user_id,
                    "extension_id": extension_id or state.get("extension_id"),
                    "extension_version": extension_version or state.get("extension_version"),
                    "active_tab": active_tab or state.get("active_tab"),
                    "page_context": page_context or state.get("page_context"),
                    "capabilities": capabilities or state.get("capabilities") or [],
                    "last_seen_at": now,
                }
            )
            self._states[user_id] = state
            return self._serialize_state_unlocked(user_id)

    async def get_status(self, user_id: str) -> dict[str, Any]:
        async with self._lock:
            return self._serialize_state_unlocked(user_id)

    async def force_offline(self, user_id: str) -> dict[str, Any]:
        """强制把指定 user 的扩展状态置为离线（last_seen_at 清零）。

        用于 /probe 主动探活失败、或用户希望立刻取消「在线」状态的场景。
        清空 capabilities 和 page_context 防止界面继续展示陈旧信息，但保留 extension_id
        以便 UI 显示「上次连接的扩展是哪一个」。
        """
        async with self._lock:
            state = self._states.get(user_id)
            if state is not None:
                state["last_seen_at"] = 0.0
                state["capabilities"] = []
                state["page_context"] = None
                state["active_tab"] = None
            return self._serialize_state_unlocked(user_id)

    async def enqueue_command(
        self,
        *,
        user_id: str,
        action: str,
        args: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        command = PendingCommand(
            id=uuid.uuid4().hex,
            action=action,
            args=args or {},
            created_at=time.time(),
        )
        async with self._lock:
            self._command_queues[user_id].append(command)
            self._queue_events[user_id].set()
            return {
                "command_id": command.id,
                "action": command.action,
                "args": command.args,
                "created_at": command.created_at,
            }

    async def poll_command(self, *, user_id: str, timeout_seconds: float = 20.0) -> dict[str, Any] | None:
        async with self._lock:
            queue = self._command_queues[user_id]
            if queue:
                command = queue.popleft()
                if not queue:
                    self._queue_events[user_id].clear()
                return self._command_to_dict(command)
            event = self._queue_events[user_id]

        try:
            await asyncio.wait_for(event.wait(), timeout=max(0.0, timeout_seconds))
        except asyncio.TimeoutError:
            return None

        async with self._lock:
            queue = self._command_queues[user_id]
            if not queue:
                self._queue_events[user_id].clear()
                return None
            command = queue.popleft()
            if not queue:
                self._queue_events[user_id].clear()
            return self._command_to_dict(command)

    async def submit_command_result(
        self,
        *,
        user_id: str,
        command_id: str,
        success: bool,
        result: Any = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "command_id": command_id,
            "user_id": user_id,
            "success": success,
            "result": result,
            "error": error,
            "finished_at": time.time(),
        }
        async with self._lock:
            self._command_results[command_id] = payload
            waiter = self._result_waiters.pop(command_id, None)
            if waiter and not waiter.done():
                waiter.set_result(payload)
            return payload

    async def wait_command_result(self, *, command_id: str, timeout_seconds: float = 30.0) -> dict[str, Any] | None:
        async with self._lock:
            existing = self._command_results.get(command_id)
            if existing is not None:
                return existing
            loop = asyncio.get_running_loop()
            future = loop.create_future()
            self._result_waiters[command_id] = future

        try:
            return await asyncio.wait_for(future, timeout=max(0.0, timeout_seconds))
        except asyncio.TimeoutError:
            return None
        finally:
            async with self._lock:
                current = self._result_waiters.get(command_id)
                if current is future:
                    self._result_waiters.pop(command_id, None)

    def _serialize_state_unlocked(self, user_id: str) -> dict[str, Any]:
        state = self._states.get(user_id, {})
        now = time.time()
        last_seen = float(state.get("last_seen_at") or 0.0)
        connected = (now - last_seen) <= HEARTBEAT_TTL_SECONDS if last_seen else False
        return {
            "connected": connected,
            "last_seen_at": last_seen or None,
            "heartbeat_ttl_seconds": HEARTBEAT_TTL_SECONDS,
            "extension_id": state.get("extension_id"),
            "extension_version": state.get("extension_version"),
            "active_tab": state.get("active_tab"),
            "page_context": state.get("page_context"),
            "capabilities": state.get("capabilities") or [],
            "queued_commands": len(self._command_queues[user_id]),
        }

    @staticmethod
    def _command_to_dict(command: PendingCommand) -> dict[str, Any]:
        return {
            "command_id": command.id,
            "action": command.action,
            "args": command.args,
            "created_at": command.created_at,
        }


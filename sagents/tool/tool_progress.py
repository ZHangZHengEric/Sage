"""Tool progress channel.

允许工具在执行过程中通过 ``emit_tool_progress`` 推送实时增量到前端 UI，
不影响最终给 LLM 的 tool message（仍然是工具一次性返回的完整结果）。

设计参考 Codex App Server / Claude Code 的 ``item/*/delta`` 机制：
"过程展示" 与 "工具结果" 用两种 event type 分离，共用同一个传输通道。

依赖关系：
- 上游（``AgentBase._execute_tool``）在调用工具前用 ``bind_tool_progress_context``
  绑定当前 ``session_id`` / ``tool_call_id``，工具内部即可直接调
  ``await emit_tool_progress(...)`` 推送增量。
- 接收侧（``ChatService.execute_chat_session``）用 ``register_progress_queue``
  把 session 对应的 ``asyncio.Queue`` 注册进来；emit 时事件入队。
- 任何环节缺失时（无注册队列、上下文未绑定、总开关关闭）emit 静默 no-op，
  保证工具行为零受影响、零异常。

合并 / 节流：
默认开启 50ms 时间窗 + 16KB 字节阈值合并，避免高频小增量挤爆通道；阈值任一
触发即 flush；显式调用 ``emit_tool_progress_closed``、注销 queue 也会强制
flush 残余。可用 ``SAGE_TOOL_PROGRESS_FLUSH_INTERVAL_MS=0`` 关闭合并以保持
原样实时推送。

所有公开 API 都是同步无副作用的注册操作，或纯粹的 ``await`` 调用，便于在任意
地方使用。
"""

from __future__ import annotations

import asyncio
import contextvars
import os
import time
from typing import Any, Dict, List, Optional, Tuple

# session_id -> asyncio.Queue，由 ChatService 在每条 chat 请求开始时注册
_progress_queues: Dict[str, asyncio.Queue] = {}


class _Coalescer:
    """单个 (session_id, tool_call_id, stream) 维度的待合并缓冲区。"""

    __slots__ = ("parts", "total_len", "flush_task")

    def __init__(self) -> None:
        self.parts: List[str] = []
        self.total_len: int = 0
        self.flush_task: Optional[asyncio.Task] = None


# (session_id, tool_call_id, stream) -> _Coalescer
_pending_buffers: Dict[Tuple[str, str, str], _Coalescer] = {}

# 当前正在执行的 tool_call_id（由 AgentBase._execute_tool 绑定）
_current_tool_call_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "sage_current_tool_call_id", default=None
)
_current_session_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "sage_current_session_id", default=None
)


def _is_progress_enabled() -> bool:
    val = os.environ.get("SAGE_TOOL_PROGRESS_ENABLED", "true")
    return val.strip().lower() not in ("0", "false", "no", "off")


def _get_flush_interval_ms() -> int:
    """合并时间窗（毫秒）。<=0 关闭合并立即推送。默认 50ms。"""
    raw = os.environ.get("SAGE_TOOL_PROGRESS_FLUSH_INTERVAL_MS", "50")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 50


def _get_flush_bytes() -> int:
    """单 stream 累计字节阈值，超过即立即 flush。默认 16KB。"""
    raw = os.environ.get("SAGE_TOOL_PROGRESS_FLUSH_BYTES", "16384")
    try:
        n = int(raw)
        return n if n > 0 else 16384
    except (TypeError, ValueError):
        return 16384


def register_progress_queue(session_id: str, queue: asyncio.Queue) -> None:
    """为指定 session 注册 progress 接收队列。重复注册会覆盖。"""
    if session_id:
        _progress_queues[session_id] = queue


def unregister_progress_queue(session_id: str) -> None:
    """注销 progress 队列；找不到则忽略。应在 chat 会话结束 finally 中调用。

    同时清理该 session 下所有 pending 的合并 buffer 与 flush task，避免
    悬挂 task 在事件循环里写入已被释放的队列。
    """
    _progress_queues.pop(session_id, None)
    if not _pending_buffers:
        return
    keys = [k for k in list(_pending_buffers.keys()) if k[0] == session_id]
    for k in keys:
        coalescer = _pending_buffers.pop(k, None)
        if coalescer and coalescer.flush_task is not None and not coalescer.flush_task.done():
            coalescer.flush_task.cancel()


def get_progress_queue(session_id: str) -> Optional[asyncio.Queue]:
    return _progress_queues.get(session_id)


class _ToolProgressContextToken:
    """Context manager，用 with/async with 包裹工具调用以临时绑定上下文。"""

    def __init__(self, session_id: Optional[str], tool_call_id: Optional[str]):
        self._sid = session_id
        self._tcid = tool_call_id
        self._sid_token = None
        self._tcid_token = None

    def __enter__(self):
        if self._sid is not None:
            self._sid_token = _current_session_id.set(self._sid)
        if self._tcid is not None:
            self._tcid_token = _current_tool_call_id.set(self._tcid)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._tcid_token is not None:
            _current_tool_call_id.reset(self._tcid_token)
        if self._sid_token is not None:
            _current_session_id.reset(self._sid_token)
        return False


def bind_tool_progress_context(session_id: Optional[str], tool_call_id: Optional[str]) -> _ToolProgressContextToken:
    """绑定当前协程上下文中的 session_id / tool_call_id。

    用法::

        with bind_tool_progress_context(session_id, tool_call_id):
            tool_response = await tool_manager.run_tool_async(...)
    """
    return _ToolProgressContextToken(session_id, tool_call_id)


def _flush_buffer(key: Tuple[str, str, str]) -> None:
    """把指定 key 的 buffer 合并成一条事件入队，并清掉 buffer / flush_task。"""
    coalescer = _pending_buffers.pop(key, None)
    if coalescer is None:
        return
    if coalescer.flush_task is not None and not coalescer.flush_task.done():
        coalescer.flush_task.cancel()
    if not coalescer.parts:
        return
    session_id, tool_call_id, stream = key
    queue = _progress_queues.get(session_id)
    if queue is None:
        return
    text = "".join(coalescer.parts)
    try:
        queue.put_nowait(_build_event(tool_call_id, text, stream, closed=False))
    except asyncio.QueueFull:
        pass
    except Exception:
        pass


def _flush_buffers_for_tool(session_id: str, tool_call_id: str) -> None:
    """flush 指定 (session_id, tool_call_id) 下所有 stream 的 pending buffer。"""
    if not _pending_buffers:
        return
    keys = [
        k for k in list(_pending_buffers.keys())
        if k[0] == session_id and k[1] == tool_call_id
    ]
    for k in keys:
        _flush_buffer(k)


async def _delayed_flush(key: Tuple[str, str, str], delay_s: float) -> None:
    try:
        await asyncio.sleep(delay_s)
    except asyncio.CancelledError:
        return
    try:
        _flush_buffer(key)
    except Exception:
        pass


async def emit_tool_progress(text: str, *, stream: str = "stdout") -> None:
    """工具调用过程中推送一段实时输出到前端 UI。

    Args:
        text: 本次新增的文本片段。
        stream: 通道标识，``stdout`` / ``stderr`` / ``info``。前端可按通道分栏渲染。

    安全降级：若总开关 ``SAGE_TOOL_PROGRESS_ENABLED`` 关闭、当前协程上下文未绑定
    session_id/tool_call_id、或 session 未注册接收队列，本函数静默 no-op，
    不抛异常、不阻塞。这样保证工具在 CLI / 单测 / 旧上下文中的行为完全不受影响。

    合并行为：默认 50ms 内的多次 emit（同一 stream）会被合并成一条事件下发；
    单 stream 累计 ≥16KB 也会立即 flush；二选一；可用环境变量
    ``SAGE_TOOL_PROGRESS_FLUSH_INTERVAL_MS`` / ``SAGE_TOOL_PROGRESS_FLUSH_BYTES``
    调整或关闭（设为 ``0`` 走立即推送）。
    """
    if not text:
        return
    if not _is_progress_enabled():
        return
    tool_call_id = _current_tool_call_id.get()
    session_id = _current_session_id.get()
    if not tool_call_id or not session_id:
        return
    queue = _progress_queues.get(session_id)
    if queue is None:
        return

    interval_ms = _get_flush_interval_ms()
    if interval_ms <= 0:
        try:
            queue.put_nowait(_build_event(tool_call_id, text, stream, closed=False))
        except asyncio.QueueFull:
            pass
        except Exception:
            pass
        return

    key = (session_id, tool_call_id, stream)
    coalescer = _pending_buffers.get(key)
    if coalescer is None:
        coalescer = _Coalescer()
        _pending_buffers[key] = coalescer
    coalescer.parts.append(text)
    coalescer.total_len += len(text)

    if coalescer.total_len >= _get_flush_bytes():
        _flush_buffer(key)
        return

    if coalescer.flush_task is None or coalescer.flush_task.done():
        try:
            coalescer.flush_task = asyncio.create_task(
                _delayed_flush(key, interval_ms / 1000.0)
            )
        except RuntimeError:
            # 没有运行中的事件循环（极少数边界），退化为立即 flush
            _flush_buffer(key)


async def emit_tool_progress_closed(*, stream: str = "info") -> None:
    """显式标记当前 tool 的 progress 流结束，让前端立即收起 spinner。

    AgentBase 在 ``_execute_tool`` finally 中会调用一次；工具自己一般不需要调。
    会先 flush 该 tool_call 下所有 pending 的合并 buffer，再下发 ``closed=True``
    事件，保证前端先看到完整内容、再看到结束标记。
    """
    if not _is_progress_enabled():
        return
    tool_call_id = _current_tool_call_id.get()
    session_id = _current_session_id.get()
    if not tool_call_id or not session_id:
        return
    _flush_buffers_for_tool(session_id, tool_call_id)
    queue = _progress_queues.get(session_id)
    if queue is None:
        return
    try:
        queue.put_nowait(_build_event(tool_call_id, "", stream, closed=True))
    except Exception:
        pass


def _build_event(tool_call_id: str, text: str, stream: str, closed: bool) -> Dict[str, Any]:
    return {
        "type": "tool_progress",
        "tool_call_id": tool_call_id,
        "text": text,
        "stream": stream,
        "closed": closed,
        "ts": time.time(),
    }


__all__ = [
    "register_progress_queue",
    "unregister_progress_queue",
    "get_progress_queue",
    "bind_tool_progress_context",
    "emit_tool_progress",
    "emit_tool_progress_closed",
]

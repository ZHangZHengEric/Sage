"""流式合并工具。

把"主消息异步迭代器"与"次级事件队列"交错输出为一个统一的异步迭代器，
用于 ``ChatService`` 把 LLM/Agent 输出的 message 流与工具的 ``tool_progress``
事件合并到同一个 NDJSON 通道。

设计要点：
- 主消息流（``message_iter``）的结束即整个合并 generator 的结束；次级队列
  （``progress_queue``）只是过程展示，不主导生命周期。
- 内部用一个汇聚队列把两路转写后的事件按到达顺序串行输出；不依赖 ``cancel``
  pending 任务，避免丢消息。
- 主消息流抛出的异常会向上传播。
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Tuple

_MERGE_SENTINEL = object()


async def interleave_message_and_progress(
    message_iter: AsyncIterator[Any],
    progress_queue: asyncio.Queue,
) -> AsyncIterator[Tuple[str, Any]]:
    """把 message 异步迭代器与 progress 队列交错输出。

    Yields:
        ``(kind, payload)`` 二元组：

        - ``kind == "message"``：来自 ``message_iter`` 的对象。
        - ``kind == "tool_progress"``：来自 ``progress_queue`` 的事件 dict。

    Raises:
        ``message_iter`` 内部抛出的任何异常会向上传播。
    """
    out_queue: asyncio.Queue = asyncio.Queue()

    async def _drain_messages():
        try:
            async for msg in message_iter:
                await out_queue.put(("msg", msg))
        except Exception as exc:
            await out_queue.put(("error", exc))
        finally:
            await out_queue.put(("msg_end", None))

    async def _drain_progress():
        while True:
            ev = await progress_queue.get()
            if ev is _MERGE_SENTINEL:
                break
            await out_queue.put(("prog", ev))

    msg_task = asyncio.create_task(_drain_messages())
    prog_task = asyncio.create_task(_drain_progress())

    try:
        while True:
            kind, payload = await out_queue.get()
            if kind == "msg":
                yield ("message", payload)
            elif kind == "prog":
                yield ("tool_progress", payload)
            elif kind == "error":
                raise payload
            elif kind == "msg_end":
                # 通知 progress drainer 退出
                await progress_queue.put(_MERGE_SENTINEL)
                # 等 drainer 把 sentinel 之前残留的 prog 事件全部 forward 到 out_queue
                try:
                    await prog_task
                except Exception:
                    pass
                # 把 out_queue 中残留的 progress 事件 flush 出去
                while not out_queue.empty():
                    k2, p2 = out_queue.get_nowait()
                    if k2 == "prog":
                        yield ("tool_progress", p2)
                break
    finally:
        if not msg_task.done():
            msg_task.cancel()
        if not prog_task.done():
            prog_task.cancel()


__all__ = ["interleave_message_and_progress"]

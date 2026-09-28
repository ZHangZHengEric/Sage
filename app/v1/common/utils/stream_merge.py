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
import time
from typing import Any, AsyncIterator, Tuple

from loguru import logger

_MERGE_SENTINEL = object()
_WORKER_SHUTDOWN_TIMEOUT_SECONDS = 13.0


def _consume_task_exception(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    try:
        task.exception()
    except (asyncio.CancelledError, Exception):
        pass


async def interleave_message_and_progress(
    message_iter: AsyncIterator[Any],
    progress_queue: asyncio.Queue,
    *,
    latency_budget=None,
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

    budget = latency_budget if getattr(latency_budget, "stream_diagnostics", False) else None

    async def enqueue(kind, value):
        queued_at = time.perf_counter() if budget is not None else None
        await out_queue.put((kind, value, queued_at))
        if budget is not None:
            budget.record_queue_depth(out_queue.qsize())

    async def _drain_messages():
        try:
            async for msg in message_iter:
                await enqueue("msg", msg)
        except Exception as exc:
            await enqueue("error", exc)
        finally:
            await enqueue("msg_end", None)

    async def _drain_progress():
        while True:
            ev = await progress_queue.get()
            if ev is _MERGE_SENTINEL:
                break
            await enqueue("prog", ev)

    msg_task = asyncio.create_task(_drain_messages())
    prog_task = asyncio.create_task(_drain_progress())

    try:
        while True:
            kind, payload, queued_at = await out_queue.get()
            if budget is not None:
                budget.add_stream_timing("delivery.queue_residence", time.perf_counter() - queued_at)
            if kind == "msg":
                sent_at = time.perf_counter() if budget is not None else None
                try:
                    yield ("message", payload)
                finally:
                    if budget is not None:
                        budget.add_stream_timing("delivery.downstream_resume", time.perf_counter() - sent_at)
            elif kind == "prog":
                sent_at = time.perf_counter() if budget is not None else None
                try:
                    yield ("tool_progress", payload)
                finally:
                    if budget is not None:
                        budget.add_stream_timing("delivery.downstream_resume", time.perf_counter() - sent_at)
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
                    k2, p2, queued_at = out_queue.get_nowait()
                    if budget is not None:
                        budget.add_stream_timing("delivery.queue_residence", time.perf_counter() - queued_at)
                    if k2 == "prog":
                        sent_at = time.perf_counter() if budget is not None else None
                        try:
                            yield ("tool_progress", p2)
                        finally:
                            if budget is not None:
                                budget.add_stream_timing("delivery.downstream_resume", time.perf_counter() - sent_at)
                break
    finally:
        if budget is not None:
            budget.emit_delivery_summary()
        workers = (msg_task, prog_task)
        for task in workers:
            if not task.done():
                task.cancel()
        try:
            done, pending = await asyncio.wait(
                workers, timeout=_WORKER_SHUTDOWN_TIMEOUT_SECONDS
            )
        except asyncio.CancelledError:
            for task in workers:
                task.add_done_callback(_consume_task_exception)
            raise

        for task in done:
            _consume_task_exception(task)
        if pending:
            logger.warning(
                "Stream merge worker cleanup timed out; detaching "
                f"{len(pending)} task(s) after "
                f"{_WORKER_SHUTDOWN_TIMEOUT_SECONDS:.3f}s"
            )
            for task in pending:
                task.cancel()
                task.add_done_callback(_consume_task_exception)


__all__ = ["interleave_message_and_progress"]

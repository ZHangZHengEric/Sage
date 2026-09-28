"""用户输入与中断：单一 stdin 读取者 + 覆盖整个命令生命周期的 SIGINT 控制器。"""

from __future__ import annotations

import asyncio
import contextlib
import io
import os
import signal
import sys
import threading
from collections.abc import Iterator
from typing import TextIO

EXIT_INTERRUPTED = 130


class InterruptController:
    """把 SIGINT 变成可等待的事件。

    第一次按下：置位 ``event``（Run 中 → 取消 Run；提示符处 → 退出）。
    第二次按下（事件尚未被 ``reset``）：取消当前任务，强制退出。
    """

    def __init__(self, task: asyncio.Task | None) -> None:
        self.event = asyncio.Event()
        self.forced = False
        self._task = task

    def on_sigint(self) -> None:
        if not self.event.is_set():
            self.event.set()
            return
        self.forced = True
        if self._task is not None and not self._task.done():
            self._task.cancel()

    def reset(self) -> None:
        """一段工作结束后清除中断标记，下一次 Ctrl-C 重新从"第一次"算起。"""

        self.event.clear()

    @property
    def triggered(self) -> bool:
        return self.event.is_set()


@contextlib.contextmanager
def interrupt_scope() -> Iterator[InterruptController]:
    """在作用域内接管 SIGINT；离开作用域恢复默认行为。"""

    loop = asyncio.get_running_loop()
    controller = InterruptController(asyncio.current_task())
    installed = False
    try:
        loop.add_signal_handler(signal.SIGINT, controller.on_sigint)
        installed = True
    except (NotImplementedError, RuntimeError, ValueError):
        # Windows / 非主线程：退回 KeyboardInterrupt 语义。
        installed = False
    try:
        yield controller
    finally:
        if installed:
            loop.remove_signal_handler(signal.SIGINT)


class StdinLineReader:
    """整个进程唯一的 stdin 行读取者。

    提示符输入、``--json`` 模式的决策行都从这里取，避免多个线程/协程争抢同一个 fd：
    被 Ctrl-C 打断的读取不会留下孤儿线程去"偷"用户的下一行。优先用
    ``loop.add_reader``（非阻塞、可取消），不支持时退回单个常驻 daemon 线程。
    """

    def __init__(self, stream: TextIO | None = None) -> None:
        self.stream = stream if stream is not None else sys.stdin
        self._queue: asyncio.Queue[str | None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._fd: int | None = None
        self._buffer = bytearray()
        self._eof = False

    def isatty(self) -> bool:
        try:
            return self.stream.isatty()
        except (AttributeError, ValueError, OSError):
            return False

    async def read_line(self) -> str | None:
        """返回去掉行尾换行的一行；EOF 返回 None。"""

        queue = self._ensure_started()
        if self._eof and queue.empty():
            return None
        line = await queue.get()
        if line is None:
            self._eof = True
        return line

    def close(self) -> None:
        if self._fd is not None and self._loop is not None:
            with contextlib.suppress(Exception):
                self._loop.remove_reader(self._fd)
            self._fd = None

    def _ensure_started(self) -> asyncio.Queue[str | None]:
        if self._queue is not None:
            return self._queue
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()
        try:
            fd = self.stream.fileno()
            self._loop.add_reader(fd, self._on_readable)
            self._fd = fd
        except (
            AttributeError,
            NotImplementedError,
            OSError,
            RuntimeError,
            ValueError,
            io.UnsupportedOperation,
        ):
            self._start_thread()
        return self._queue

    def _on_readable(self) -> None:
        assert self._fd is not None
        try:
            chunk = os.read(self._fd, 4096)
        except BlockingIOError:
            return
        except OSError:
            chunk = b""
        if not chunk:
            self.close()
            if self._buffer:
                self._push(self._buffer.decode("utf-8", errors="replace").rstrip("\r"))
                self._buffer.clear()
            self._push(None)
            return
        self._buffer.extend(chunk)
        while b"\n" in self._buffer:
            line, _, rest = self._buffer.partition(b"\n")
            self._buffer[:] = rest
            self._push(line.decode("utf-8", errors="replace").rstrip("\r"))

    def _start_thread(self) -> None:
        loop = self._loop
        assert loop is not None

        def worker() -> None:
            while True:
                try:
                    line = self.stream.readline()
                except Exception:  # noqa: BLE001 - 读失败视同 EOF
                    line = ""
                if line == "":
                    loop.call_soon_threadsafe(self._push, None)
                    return
                loop.call_soon_threadsafe(self._push, line.rstrip("\r\n"))

        threading.Thread(target=worker, name="sage-cli-v2-stdin", daemon=True).start()

    def _push(self, line: str | None) -> None:
        assert self._queue is not None
        self._queue.put_nowait(line)


async def read_line_or_interrupt(
    reader: StdinLineReader, interrupt: asyncio.Event | None
) -> str | None:
    """等一行输入；用户中断时立即返回 None，不再等待 stdin。"""

    if interrupt is None:
        return await reader.read_line()
    if interrupt.is_set():
        return None
    read_task = asyncio.ensure_future(reader.read_line())
    wait_task = asyncio.ensure_future(interrupt.wait())
    try:
        done, _ = await asyncio.wait(
            {read_task, wait_task}, return_when=asyncio.FIRST_COMPLETED
        )
        if read_task in done:
            return read_task.result()
        return None
    finally:
        for task in (read_task, wait_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(read_task, wait_task, return_exceptions=True)

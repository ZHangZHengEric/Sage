"""把 v2 native 事件渲染成终端输出：纯文本模式或 NDJSON（``--json``）模式。"""

from __future__ import annotations

import json
import sys
from typing import Any, Protocol, TextIO

from sagents.v2.contracts.events import RuntimeEvent
from sagents.v2.contracts.items import MessageItemData, TextBlock
from sagents.v2.contracts.run_state import RunResult


class EventRenderer(Protocol):
    last_sequence: int

    def handle(self, event: RuntimeEvent) -> None: ...

    def frame(self, payload: dict[str, Any]) -> None:
        """CLI 自身的框架信息（会话开始/审批请求/最终结果）。"""
        ...

    def notice(self, text: str) -> None: ...


class PlainRenderer:
    """人类可读渲染：assistant 文本流式到 stdout，其余状态行走 stderr。"""

    def __init__(
        self,
        out: TextIO | None = None,
        err: TextIO | None = None,
        *,
        verbose: bool = False,
    ) -> None:
        self.out = out or sys.stdout
        self.err = err or sys.stderr
        self.verbose = verbose
        self.last_sequence = 0
        self._assistant_items: set[str] = set()
        self._streamed_chars: dict[str, int] = {}
        self._announced_session: str | None = None

    def handle(self, event: RuntimeEvent) -> None:
        self.last_sequence = max(self.last_sequence, event.run_sequence)
        data = event.data
        if event.type == "message.started":
            item = data.item
            if isinstance(getattr(item, "data", None), MessageItemData):
                if item.data.role == "assistant":
                    self._assistant_items.add(item.item_id)
            return
        if event.type == "message.delta":
            item_id = event.item_id or ""
            if item_id not in self._assistant_items:
                return
            text = data.delta if isinstance(data.delta, str) else ""
            if text:
                self._streamed_chars[item_id] = (
                    self._streamed_chars.get(item_id, 0) + len(text)
                )
                self.out.write(text)
                self.out.flush()
            return
        if event.type == "message.completed":
            item = data.item
            if not isinstance(getattr(item, "data", None), MessageItemData):
                return
            if item.data.role != "assistant":
                return
            if self._streamed_chars.get(item.item_id, 0) == 0:
                # provider 没有流式增量时，用完成态的完整文本兜底。
                self.out.write(_message_text(item.data))
            self.out.write("\n")
            self.out.flush()
            return
        if data.kind == "tool":
            line = f"[tool] {data.tool_name} {data.state}"
            if data.error is not None:
                line += f" ({data.error.code}: {data.error.message})"
            self.notice(line)
            return
        if event.type == "run.failed" and data.error is not None:
            self.notice(f"[run failed] {data.error.code}: {data.error.message}")
            return
        if event.type == "run.cancelled":
            reason = f" reason={data.reason}" if data.reason else ""
            self.notice(f"[run cancelled]{reason}")

    def frame(self, payload: dict[str, Any]) -> None:
        kind = payload.get("type")
        if kind == "cli_v2_session":
            session_id = str(payload.get("session_id"))
            if session_id != self._announced_session:
                self._announced_session = session_id
                self.notice(f"session_id: {session_id}")
            if self.verbose:
                self.notice(f"run_id: {payload.get('run_id')}")
        elif kind == "cli_v2_steer":
            if payload.get("status") == "accepted":
                self.notice(f"(steer) queued for the next model step: {payload.get('text')}")
            elif payload.get("status") == "unapplied":
                self.notice(
                    f"(steer) the run ended before it could be applied: {payload.get('text')}"
                )
            else:
                self.notice(
                    f"(steer) not applied: {payload.get('detail') or 'rejected'}"
                    + (f" — {payload.get('text')}" if payload.get("text") else "")
                )
        elif kind == "cli_v2_result" and payload.get("state") != "completed":
            suffix = " (interrupted)" if payload.get("interrupted") else ""
            self.notice(f"[result] state={payload.get('state')}{suffix}")

    def notice(self, text: str) -> None:
        self.err.write(text + "\n")
        self.err.flush()


class JsonRenderer:
    """机器可读渲染：每行一个 JSON；native 事件原样透传，CLI 框架帧以 ``cli_v2_`` 前缀区分。"""

    def __init__(self, out: TextIO | None = None) -> None:
        self.out = out or sys.stdout
        self.last_sequence = 0

    def handle(self, event: RuntimeEvent) -> None:
        self.last_sequence = max(self.last_sequence, event.run_sequence)
        self._write(event.model_dump(mode="json"))

    def frame(self, payload: dict[str, Any]) -> None:
        self._write(payload)

    def notice(self, text: str) -> None:
        self._write({"type": "cli_v2_notice", "content": text})

    def _write(self, payload: dict[str, Any]) -> None:
        self.out.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.out.flush()


def _message_text(data: MessageItemData) -> str:
    return "".join(block.text for block in data.content if isinstance(block, TextBlock))


def final_assistant_text(result: RunResult) -> str:
    """从终态结果中拼出 assistant 的最终文本（多条消息以换行连接）。"""

    return "\n".join(
        _message_text(item.data)
        for item in result.final_items
        if isinstance(item.data, MessageItemData) and item.data.role == "assistant"
    )

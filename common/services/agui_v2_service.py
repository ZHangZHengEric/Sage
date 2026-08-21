"""Translate Sage stream messages into AG-UI 0.1.19 events.

The public event lifecycles follow the AG-UI event contract:
https://docs.ag-ui.com/concepts/events
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from ag_ui.core import (
    ActivitySnapshotEvent,
    ReasoningEndEvent,
    ReasoningMessageContentEvent,
    ReasoningMessageEndEvent,
    ReasoningMessageStartEvent,
    ReasoningStartEvent,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)
from pydantic import BaseModel


_REASONING_TYPES = frozenset({"reasoning_content", "task_analysis", "thinking"})
_ACTIVITY_TYPES = frozenset(
    {
        "agent_execution_error",
        "error",
        "guide",
        "loop_break",
        "skill_exec_plan",
        "skill_exec_result",
        "skill_observation",
        "stage_summary",
        "tool_progress",
    }
)


def _dump(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(by_alias=True, exclude_none=True, mode="json")


def _stable_id(namespace: str, *values: object) -> str:
    source = "\0".join(str(value) for value in values).encode()
    return f"{namespace}-{hashlib.sha256(source).hexdigest()[:24]}"


def _message_type(message: Mapping[str, Any]) -> str:
    return str(message.get("type") or message.get("message_type") or "").strip().lower()


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return "\n".join(
            str(part["text"])
            for part in value
            if isinstance(part, Mapping) and isinstance(part.get("text"), str)
        )
    return ""


def _is_failure(message: Mapping[str, Any]) -> bool:
    if _message_type(message) in {"error", "agent_execution_error", "loop_break"}:
        return True
    if message.get("error") or message.get("error_info"):
        return True
    content = message.get("content")
    return isinstance(content, Mapping) and str(
        content.get("status") or ""
    ).lower() in {
        "error",
        "failed",
    }


class AguiEventTranslator:
    """Stateful translator for one Sage Agent run."""

    def __init__(self, *, thread_id: str, run_id: str) -> None:
        self.thread_id = thread_id
        self.run_id = run_id
        self._text_message_id: str | None = None
        self._reasoning_message_id: str | None = None
        self._tool_streams: list[dict[str, Any]] = []
        self._tool_streams_by_id: dict[str, dict[str, Any]] = {}
        self._tool_streams_by_slot: dict[tuple[str, str], dict[str, Any]] = {}
        self._activity_index = 0
        self._usage: dict[str, Any] | None = None

    def run_started(self) -> dict[str, Any]:
        return _dump(RunStartedEvent(thread_id=self.thread_id, run_id=self.run_id))

    def translate(self, source: Mapping[str, Any]) -> list[dict[str, Any]]:
        if str(source.get("type") or "") == "stream_end":
            return []

        kind = _message_type(source)
        role = str(source.get("role") or "").lower()
        events: list[dict[str, Any]] = []

        if kind == "token_usage":
            metadata = source.get("metadata")
            usage = (
                metadata.get("token_usage") if isinstance(metadata, Mapping) else None
            )
            if isinstance(usage, Mapping):
                self._usage = dict(usage)
            return events

        if kind in _REASONING_TYPES or source.get("reasoning_content"):
            content = str(
                source.get("reasoning_content") or _text(source.get("content"))
            )
            if content:
                message_id = str(
                    source.get("message_id")
                    or source.get("id")
                    or _stable_id("reasoning", self.run_id)
                )
                if self._reasoning_message_id != message_id:
                    events += self._close_reasoning()
                    self._reasoning_message_id = message_id
                    events.append(_dump(ReasoningStartEvent(message_id=message_id)))
                    events.append(
                        _dump(
                            ReasoningMessageStartEvent(
                                message_id=message_id, role="reasoning"
                            )
                        )
                    )
                    events.append(
                        _dump(
                            ReasoningMessageContentEvent(
                                message_id=message_id, delta=content
                            )
                        )
                    )
            if kind in _REASONING_TYPES and not source.get("content"):
                return events

        raw_tool_calls = source.get("tool_calls") or source.get("toolCalls")
        if isinstance(raw_tool_calls, list) and raw_tool_calls:
            parent_message_id = str(
                source.get("message_id")
                or source.get("id")
                or _stable_id("assistant", self.run_id, "tools")
            )
            events += self._translate_tool_call_deltas(
                raw_tool_calls, parent_message_id
            )

        if role == "tool" or kind == "tool_call_result":
            call_id = str(source.get("tool_call_id") or source.get("toolCallId") or "")
            if call_id:
                events += self._close_tool(call_id)
                result_id = str(
                    source.get("message_id")
                    or source.get("id")
                    or _stable_id("tool-result", self.run_id, call_id)
                )
                raw_content = source.get("content")
                content = (
                    raw_content
                    if isinstance(raw_content, str)
                    else json.dumps(raw_content, ensure_ascii=False, default=str)
                )
                events.append(
                    _dump(
                        ToolCallResultEvent(
                            message_id=result_id,
                            tool_call_id=call_id,
                            content=content,
                            role="tool",
                        )
                    )
                )
            return events

        if kind in _ACTIVITY_TYPES:
            self._activity_index += 1
            if kind == "tool_progress":
                call_id = str(
                    source.get("tool_call_id") or source.get("toolCallId") or ""
                )
                if call_id:
                    events += self._close_tool(call_id)
                activity_id = _stable_id(
                    "activity",
                    self.run_id,
                    kind,
                    call_id or self._activity_index,
                )
                content = {
                    "toolCallId": call_id,
                    "text": _text(source.get("text") or source.get("content")),
                    "stream": str(source.get("stream") or "info"),
                    "closed": bool(source.get("closed")),
                }
            else:
                activity_id = str(
                    source.get("message_id")
                    or source.get("id")
                    or _stable_id("activity", self.run_id, self._activity_index, kind)
                )
                raw_content = source.get("content")
                content = (
                    dict(raw_content)
                    if isinstance(raw_content, Mapping)
                    else {"text": _text(raw_content)}
                )
                if _is_failure(source):
                    content["status"] = "failed"
            events.append(
                _dump(
                    ActivitySnapshotEvent(
                        message_id=activity_id,
                        activity_type=kind or "activity",
                        content=content,
                        replace=True,
                    )
                )
            )
            return events

        if role == "assistant":
            content = _text(source.get("content"))
            if content:
                events += self._close_reasoning()
                message_id = str(
                    source.get("message_id")
                    or source.get("id")
                    or _stable_id("assistant", self.run_id)
                )
                if self._text_message_id != message_id:
                    events += self._close_text()
                    self._text_message_id = message_id
                    events.append(
                        _dump(
                            TextMessageStartEvent(
                                message_id=message_id, role="assistant"
                            )
                        )
                    )
                events.append(
                    _dump(TextMessageContentEvent(message_id=message_id, delta=content))
                )
        return events

    def run_finished(self, *, result: Any | None = None) -> list[dict[str, Any]]:
        events = self._close_all()
        if result is None and self._usage is not None:
            result = {"usage": self._usage}
        events.append(
            _dump(
                RunFinishedEvent(
                    thread_id=self.thread_id,
                    run_id=self.run_id,
                    result=result,
                )
            )
        )
        return events

    def run_error(
        self, message: str, *, code: str | None = None
    ) -> list[dict[str, Any]]:
        return self._close_all() + [_dump(RunErrorEvent(message=message, code=code))]

    def _translate_tool_call_deltas(
        self,
        tool_calls: list[Any],
        parent_message_id: str,
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for raw_tool_call in tool_calls:
            if not isinstance(raw_tool_call, Mapping):
                continue
            function_value = raw_tool_call.get("function")
            function = function_value if isinstance(function_value, Mapping) else {}
            call_id = str(
                raw_tool_call.get("id") or raw_tool_call.get("tool_call_id") or ""
            )
            name = str(function.get("name") or raw_tool_call.get("name") or "")
            index = raw_tool_call.get("index")
            slot = (parent_message_id, str(index)) if index is not None else None

            stream = self._tool_streams_by_id.get(call_id) if call_id else None
            if stream is None and slot is not None:
                stream = self._tool_streams_by_slot.get(slot)
            if stream is None and not call_id and index is None:
                stream = next(
                    (
                        candidate
                        for candidate in reversed(self._tool_streams)
                        if candidate["parent_message_id"] == parent_message_id
                        and not candidate["ended"]
                    ),
                    None,
                )
            if stream is None:
                stream = {
                    "parent_message_id": parent_message_id,
                    "call_id": "",
                    "name": "",
                    "pending_args": [],
                    "started": False,
                    "ended": False,
                }
                self._tool_streams.append(stream)
                if slot is not None:
                    self._tool_streams_by_slot[slot] = stream

            if stream["ended"]:
                continue
            if call_id:
                stream["call_id"] = call_id
                self._tool_streams_by_id[call_id] = stream
            if name:
                stream["name"] = name

            arguments_value = function.get("arguments")
            if isinstance(arguments_value, str):
                arguments = arguments_value
            elif arguments_value is not None:
                arguments = json.dumps(arguments_value, ensure_ascii=False, default=str)
            else:
                arguments = ""
            if arguments:
                stream["pending_args"].append(arguments)

            if not stream["started"] and stream["call_id"] and stream["name"]:
                stream["started"] = True
                events.append(
                    _dump(
                        ToolCallStartEvent(
                            tool_call_id=stream["call_id"],
                            tool_call_name=stream["name"],
                            parent_message_id=stream["parent_message_id"],
                        )
                    )
                )
                events += self._flush_tool_arguments(stream)
            elif stream["started"]:
                events += self._flush_tool_arguments(stream)
        return events

    @staticmethod
    def _flush_tool_arguments(stream: dict[str, Any]) -> list[dict[str, Any]]:
        events = [
            _dump(ToolCallArgsEvent(tool_call_id=stream["call_id"], delta=delta))
            for delta in stream["pending_args"]
        ]
        stream["pending_args"] = []
        return events

    def _close_text(self) -> list[dict[str, Any]]:
        if self._text_message_id is None:
            return []
        message_id = self._text_message_id
        self._text_message_id = None
        return [_dump(TextMessageEndEvent(message_id=message_id))]

    def _close_reasoning(self) -> list[dict[str, Any]]:
        if self._reasoning_message_id is None:
            return []
        message_id = self._reasoning_message_id
        self._reasoning_message_id = None
        return [
            _dump(ReasoningMessageEndEvent(message_id=message_id)),
            _dump(ReasoningEndEvent(message_id=message_id)),
        ]

    def _close_tool(self, call_id: str) -> list[dict[str, Any]]:
        stream = self._tool_streams_by_id.get(call_id)
        if stream is None or stream["ended"]:
            return []
        stream["ended"] = True
        if not stream["started"]:
            return []
        return [_dump(ToolCallEndEvent(tool_call_id=call_id))]

    def _close_tools(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for stream in self._tool_streams:
            call_id = str(stream["call_id"])
            if call_id:
                events += self._close_tool(call_id)
        return events

    def _close_all(self) -> list[dict[str, Any]]:
        return self._close_reasoning() + self._close_text() + self._close_tools()


__all__ = ["AguiEventTranslator"]

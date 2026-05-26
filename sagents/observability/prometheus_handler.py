import contextvars
import hashlib
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Union

from .base import BaseTraceHandler


_DURATION_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)
_OP_STACK: contextvars.ContextVar[tuple[tuple[str, str, str, float], ...]] = contextvars.ContextVar(
    "sagents_prometheus_operation_stack",
    default=(),
)


@dataclass
class _PrometheusTraceState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    agent_total: dict[tuple[str, str], int] = field(default_factory=dict)
    tool_total: dict[tuple[str, str], int] = field(default_factory=dict)
    tool_duration_sum: dict[str, float] = field(default_factory=dict)
    tool_duration_count: dict[str, int] = field(default_factory=dict)
    tool_duration_buckets: dict[tuple[str, float], int] = field(default_factory=dict)
    tool_failures: dict[tuple[str, str, str, str], int] = field(default_factory=dict)


_STATE = _PrometheusTraceState()


def build_session_trace_id(session_id: str) -> str:
    return hashlib.md5(str(session_id or "unknown").encode("utf-8")).hexdigest()


def _escape_label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _labeled_metric_line(name: str, labels: dict[str, str], value: int | float) -> str:
    rendered_labels = ",".join(f'{key}="{_escape_label_value(val)}"' for key, val in labels.items())
    return f"{name}{{{rendered_labels}}} {float(value):.6f}"


def _normalize_label_value(value: Any, fallback: str = "unknown") -> str:
    text = str(value or "").strip()
    return text or fallback


def _push_operation(kind: str, name: str, session_id: str) -> None:
    _OP_STACK.set(_OP_STACK.get() + ((kind, name, _normalize_label_value(session_id), time.perf_counter()),))


def _pop_operation(kind: str) -> tuple[str, str, float] | None:
    stack = _OP_STACK.get()
    remaining: list[tuple[str, str, str, float]] = []
    matched: tuple[str, str, float] | None = None
    for item in reversed(stack):
        item_kind, name, session_id, started_at = item
        if matched is None and item_kind == kind:
            matched = (name, session_id, started_at)
            continue
        remaining.append(item)
    if matched is None:
        return None
    remaining.reverse()
    _OP_STACK.set(tuple(remaining))
    return matched


def _record_agent(agent_id: str, status: str) -> None:
    key = (_normalize_label_value(agent_id), _normalize_label_value(status))
    with _STATE.lock:
        _STATE.agent_total[key] = _STATE.agent_total.get(key, 0) + 1


def _record_tool(tool_name: str, status: str, duration: float) -> None:
    normalized_tool_name = _normalize_label_value(tool_name)
    normalized_status = _normalize_label_value(status)
    with _STATE.lock:
        total_key = (normalized_tool_name, normalized_status)
        _STATE.tool_total[total_key] = _STATE.tool_total.get(total_key, 0) + 1
        _STATE.tool_duration_sum[normalized_tool_name] = _STATE.tool_duration_sum.get(normalized_tool_name, 0.0) + duration
        _STATE.tool_duration_count[normalized_tool_name] = _STATE.tool_duration_count.get(normalized_tool_name, 0) + 1
        for bucket in _DURATION_BUCKETS:
            if duration <= bucket:
                bucket_key = (normalized_tool_name, bucket)
                _STATE.tool_duration_buckets[bucket_key] = _STATE.tool_duration_buckets.get(bucket_key, 0) + 1


def _record_tool_failure(tool_name: str, session_id: str, error: Exception) -> None:
    normalized_session_id = _normalize_label_value(session_id)
    key = (
        _normalize_label_value(tool_name),
        normalized_session_id,
        build_session_trace_id(normalized_session_id),
        error.__class__.__name__ or "Error",
    )
    with _STATE.lock:
        _STATE.tool_failures[key] = _STATE.tool_failures.get(key, 0) + 1


def _agent_status(output: Any) -> str:
    if not isinstance(output, dict):
        return "success"
    raw_status = str(output.get("status") or "finished").lower()
    if raw_status == "finished":
        return "success"
    return raw_status or "unknown"


def reset_prometheus_trace_metrics() -> None:
    with _STATE.lock:
        _STATE.agent_total.clear()
        _STATE.tool_total.clear()
        _STATE.tool_duration_sum.clear()
        _STATE.tool_duration_count.clear()
        _STATE.tool_duration_buckets.clear()
        _STATE.tool_failures.clear()
    _OP_STACK.set(())


def render_prometheus_trace_metrics() -> str:
    with _STATE.lock:
        agent_total = dict(_STATE.agent_total)
        tool_total = dict(_STATE.tool_total)
        tool_duration_sum = dict(_STATE.tool_duration_sum)
        tool_duration_count = dict(_STATE.tool_duration_count)
        tool_duration_buckets = dict(_STATE.tool_duration_buckets)
        tool_failures = dict(_STATE.tool_failures)

    lines = [
        "# HELP sagents_agent_runs_total Total SAgents agent runs by agent_id and status.",
        "# TYPE sagents_agent_runs_total counter",
    ]
    for agent_id, status in sorted(agent_total):
        lines.append(
            _labeled_metric_line(
                "sagents_agent_runs_total",
                {"agent_id": agent_id, "status": status},
                agent_total[(agent_id, status)],
            )
        )

    lines.extend(
        [
            "# HELP sagents_tool_calls_total Total SAgents tool calls by tool_name and status.",
            "# TYPE sagents_tool_calls_total counter",
        ]
    )
    for tool_name, status in sorted(tool_total):
        lines.append(
            _labeled_metric_line(
                "sagents_tool_calls_total",
                {"tool_name": tool_name, "status": status},
                tool_total[(tool_name, status)],
            )
        )

    lines.extend(
        [
            "# HELP sagents_tool_call_duration_seconds SAgents tool call duration in seconds.",
            "# TYPE sagents_tool_call_duration_seconds histogram",
        ]
    )
    for tool_name in sorted(set(tool_duration_count) | set(tool_duration_sum)):
        cumulative = 0
        for bucket in _DURATION_BUCKETS:
            cumulative = tool_duration_buckets.get((tool_name, bucket), cumulative)
            lines.append(
                _labeled_metric_line(
                    "sagents_tool_call_duration_seconds_bucket",
                    {"tool_name": tool_name, "le": str(bucket)},
                    cumulative,
                )
            )
        lines.append(
            _labeled_metric_line(
                "sagents_tool_call_duration_seconds_bucket",
                {"tool_name": tool_name, "le": "+Inf"},
                tool_duration_count.get(tool_name, 0),
            )
        )
        lines.append(
            _labeled_metric_line(
                "sagents_tool_call_duration_seconds_sum",
                {"tool_name": tool_name},
                tool_duration_sum.get(tool_name, 0.0),
            )
        )
        lines.append(
            _labeled_metric_line(
                "sagents_tool_call_duration_seconds_count",
                {"tool_name": tool_name},
                tool_duration_count.get(tool_name, 0),
            )
        )

    lines.extend(
        [
            "# HELP sagents_tool_call_failures_total SAgents tool call failures with session_id for drilldown.",
            "# TYPE sagents_tool_call_failures_total counter",
        ]
    )
    for tool_name, session_id, trace_id, error_type in sorted(tool_failures):
        lines.append(
            _labeled_metric_line(
                "sagents_tool_call_failures_total",
                {
                    "tool_name": tool_name,
                    "session_id": session_id,
                    "trace_id": trace_id,
                    "error_type": error_type,
                },
                tool_failures[(tool_name, session_id, trace_id, error_type)],
            )
        )
    return "\n".join(lines) + "\n"


class PrometheusTraceHandler(BaseTraceHandler):
    def on_chain_start(self, session_id: str, input_data: Any, **kwargs: Any) -> Any:
        return None

    def on_chain_end(self, output_data: Any, **kwargs: Any) -> Any:
        return None

    def on_chain_error(self, error: Exception, **kwargs: Any) -> Any:
        return None

    def on_agent_start(self, session_id: str, agent_name: str, **kwargs: Any) -> Any:
        agent_id = _normalize_label_value(kwargs.get("agent_id") or agent_name)
        _push_operation("agent", agent_id, session_id)

    def on_agent_end(self, output: Any, **kwargs: Any) -> Any:
        current = _pop_operation("agent")
        if not current:
            return
        agent_id = current[0]
        _record_agent(agent_id, _agent_status(output))

    def on_agent_error(self, error: Exception, **kwargs: Any) -> Any:
        current = _pop_operation("agent")
        agent_id = current[0] if current else _normalize_label_value(kwargs.get("agent_id"))
        _record_agent(agent_id, "error")

    def on_llm_start(
        self,
        session_id: str,
        model_name: str,
        messages: List[Any],
        step_name: str = None,
        **kwargs: Any,
    ) -> Any:
        return None

    def on_llm_end(self, response: Any, **kwargs: Any) -> Any:
        return None

    def on_llm_error(self, error: Exception, **kwargs: Any) -> Any:
        return None

    def on_tool_start(
        self,
        session_id: str,
        tool_name: str,
        tool_input: Union[str, Dict],
        **kwargs: Any,
    ) -> Any:
        _push_operation("tool", _normalize_label_value(tool_name), session_id)

    def on_tool_end(self, tool_output: Any, **kwargs: Any) -> Any:
        current = _pop_operation("tool")
        if not current:
            return
        tool_name, _, started_at = current
        _record_tool(tool_name, "success", max(time.perf_counter() - started_at, 0.0))

    def on_tool_error(self, error: Exception, **kwargs: Any) -> Any:
        current = _pop_operation("tool")
        if not current:
            return
        tool_name, session_id, started_at = current
        _record_tool(tool_name, "error", max(time.perf_counter() - started_at, 0.0))
        _record_tool_failure(tool_name, session_id, error)

    def on_message_start(self, session_id: str, message_id: str, **kwargs: Any) -> Any:
        return None

    def on_message_end(self, session_id: str, message_id: str, **kwargs: Any) -> Any:
        return None

import contextvars
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Union

from .base import BaseTraceHandler


_DURATION_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)
_OP_STACK: contextvars.ContextVar[tuple[tuple[str, str, float], ...]] = contextvars.ContextVar(
    "sagents_prometheus_operation_stack",
    default=(),
)


@dataclass
class _PrometheusTraceState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    total: dict[tuple[str, str, str], int] = field(default_factory=dict)
    duration_sum: dict[tuple[str, str], float] = field(default_factory=dict)
    duration_count: dict[tuple[str, str], int] = field(default_factory=dict)
    duration_buckets: dict[tuple[str, str, float], int] = field(default_factory=dict)
    active: dict[tuple[str, str], int] = field(default_factory=dict)


_STATE = _PrometheusTraceState()


def _escape_label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _labeled_metric_line(name: str, labels: dict[str, str], value: int | float) -> str:
    rendered_labels = ",".join(f'{key}="{_escape_label_value(val)}"' for key, val in labels.items())
    return f"{name}{{{rendered_labels}}} {float(value):.6f}"


def _start_operation(category: str, name: str) -> None:
    started_at = time.perf_counter()
    key = (category, name)
    with _STATE.lock:
        _STATE.active[key] = _STATE.active.get(key, 0) + 1
    _OP_STACK.set(_OP_STACK.get() + ((category, name, started_at),))


def _finish_operation(category: str, name: str, status: str) -> None:
    stack = _OP_STACK.get()
    started_at = None
    remaining: list[tuple[str, str, float]] = []
    for item in reversed(stack):
        item_category, item_name, item_started_at = item
        if started_at is None and item_category == category and item_name == name:
            started_at = item_started_at
            continue
        remaining.append(item)
    if started_at is None:
        return
    remaining.reverse()
    _OP_STACK.set(tuple(remaining))

    duration = max(time.perf_counter() - started_at, 0.0)
    key = (category, name)
    status_key = (category, name, status or "unknown")
    with _STATE.lock:
        _STATE.total[status_key] = _STATE.total.get(status_key, 0) + 1
        _STATE.duration_sum[key] = _STATE.duration_sum.get(key, 0.0) + duration
        _STATE.duration_count[key] = _STATE.duration_count.get(key, 0) + 1
        for bucket in _DURATION_BUCKETS:
            if duration <= bucket:
                bucket_key = (category, name, bucket)
                _STATE.duration_buckets[bucket_key] = _STATE.duration_buckets.get(bucket_key, 0) + 1
        _STATE.active[key] = max(_STATE.active.get(key, 0) - 1, 0)


def reset_prometheus_trace_metrics() -> None:
    with _STATE.lock:
        _STATE.total.clear()
        _STATE.duration_sum.clear()
        _STATE.duration_count.clear()
        _STATE.duration_buckets.clear()
        _STATE.active.clear()
    _OP_STACK.set(())


def render_prometheus_trace_metrics() -> str:
    lines = [
        "# HELP sagents_observability_operations_total Total sagents operations by category, name, and status.",
        "# TYPE sagents_observability_operations_total counter",
    ]
    with _STATE.lock:
        total = dict(_STATE.total)
        duration_sum = dict(_STATE.duration_sum)
        duration_count = dict(_STATE.duration_count)
        duration_buckets = dict(_STATE.duration_buckets)
        active = dict(_STATE.active)

    for category, name, status in sorted(total):
        lines.append(
            _labeled_metric_line(
                "sagents_observability_operations_total",
                {"category": category, "name": name, "session_id": name, "status": status},
                total[(category, name, status)],
            )
        )

    lines.extend(
        [
            "# HELP sagents_observability_operation_duration_seconds Sagents operation duration in seconds.",
            "# TYPE sagents_observability_operation_duration_seconds histogram",
        ]
    )
    for category, name in sorted(set(duration_count) | set(duration_sum)):
        cumulative = 0
        for bucket in _DURATION_BUCKETS:
            cumulative = duration_buckets.get((category, name, bucket), cumulative)
            lines.append(
                _labeled_metric_line(
                    "sagents_observability_operation_duration_seconds_bucket",
                    {"category": category, "name": name, "session_id": name, "le": str(bucket)},
                    cumulative,
                )
            )
        lines.append(
            _labeled_metric_line(
                "sagents_observability_operation_duration_seconds_bucket",
                {"category": category, "name": name, "session_id": name, "le": "+Inf"},
                duration_count.get((category, name), 0),
            )
        )
        lines.append(
            _labeled_metric_line(
                "sagents_observability_operation_duration_seconds_sum",
                {"category": category, "name": name, "session_id": name},
                duration_sum.get((category, name), 0.0),
            )
        )
        lines.append(
            _labeled_metric_line(
                "sagents_observability_operation_duration_seconds_count",
                {"category": category, "name": name, "session_id": name},
                duration_count.get((category, name), 0),
            )
        )

    lines.extend(
        [
            "# HELP sagents_observability_operations_active Sagents operations currently in progress.",
            "# TYPE sagents_observability_operations_active gauge",
        ]
    )
    for category, name in sorted(active):
        lines.append(
            _labeled_metric_line(
                "sagents_observability_operations_active",
                {"category": category, "name": name, "session_id": name},
                active[(category, name)],
            )
        )
    return "\n".join(lines) + "\n"


class PrometheusTraceHandler(BaseTraceHandler):
    def on_chain_start(self, session_id: str, input_data: Any, **kwargs: Any) -> Any:
        _start_operation("chain", _session_operation_name(session_id))

    def on_chain_end(self, output_data: Any, **kwargs: Any) -> Any:
        _finish_operation("chain", _current_name_for_category("chain"), "success")

    def on_chain_error(self, error: Exception, **kwargs: Any) -> Any:
        _finish_operation("chain", _current_name_for_category("chain"), "error")

    def on_agent_start(self, session_id: str, agent_name: str, **kwargs: Any) -> Any:
        _start_operation("agent", _session_operation_name(session_id))

    def on_agent_end(self, output: Any, **kwargs: Any) -> Any:
        status = "success"
        if isinstance(output, dict):
            raw_status = str(output.get("status") or "finished").lower()
            status = "success" if raw_status == "finished" else raw_status
        _finish_operation("agent", _current_name_for_category("agent"), status)

    def on_agent_error(self, error: Exception, **kwargs: Any) -> Any:
        _finish_operation("agent", _current_name_for_category("agent"), "error")

    def on_llm_start(
        self,
        session_id: str,
        model_name: str,
        messages: List[Any],
        step_name: str = None,
        **kwargs: Any,
    ) -> Any:
        _start_operation("llm", _session_operation_name(session_id))

    def on_llm_end(self, response: Any, **kwargs: Any) -> Any:
        _finish_operation("llm", _current_name_for_category("llm"), "success")

    def on_llm_error(self, error: Exception, **kwargs: Any) -> Any:
        _finish_operation("llm", _current_name_for_category("llm"), "error")

    def on_tool_start(
        self,
        session_id: str,
        tool_name: str,
        tool_input: Union[str, Dict],
        **kwargs: Any,
    ) -> Any:
        tool_type = str(kwargs.get("tool_type") or "tool")
        category = "mcp" if tool_type == "mcp" else "tool"
        _start_operation(category, _session_operation_name(session_id))

    def on_tool_end(self, tool_output: Any, **kwargs: Any) -> Any:
        category, name = _current_tool_category_and_name()
        _finish_operation(category, name, "success")

    def on_tool_error(self, error: Exception, **kwargs: Any) -> Any:
        category, name = _current_tool_category_and_name()
        _finish_operation(category, name, "error")

    def on_message_start(self, session_id: str, message_id: str, **kwargs: Any) -> Any:
        return None

    def on_message_end(self, session_id: str, message_id: str, **kwargs: Any) -> Any:
        return None


def _current_name_for_category(category: str) -> str:
    for item_category, item_name, _ in reversed(_OP_STACK.get()):
        if item_category == category:
            return item_name
    return "unknown"


def _session_operation_name(session_id: str) -> str:
    return str(session_id or "unknown")


def _current_tool_category_and_name() -> tuple[str, str]:
    for category, name, _ in reversed(_OP_STACK.get()):
        if category in {"tool", "mcp"}:
            return category, name
    return "tool", "unknown"

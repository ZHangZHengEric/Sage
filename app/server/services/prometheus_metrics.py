import gc
import hashlib
import os
import re
import resource
import sys
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass, field


_PROCESS_START_TIME = time.time()
_HTTP_DURATION_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
_DYNAMIC_PATH_SEGMENT_RE = re.compile(
    r"^(\d+|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$"
)


@dataclass
class _HttpMetricState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    requests_total: dict[tuple[str, str, str], int] = field(default_factory=dict)
    request_last_seen: dict[tuple[str, str, str], float] = field(default_factory=dict)
    duration_sum: dict[tuple[str, str], float] = field(default_factory=dict)
    duration_count: dict[tuple[str, str], int] = field(default_factory=dict)
    duration_buckets: dict[tuple[str, str, float], int] = field(default_factory=dict)
    in_progress: dict[tuple[str, str], int] = field(default_factory=dict)


@dataclass
class _OperationMetricState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    total: dict[tuple[str, str, str], int] = field(default_factory=dict)
    duration_sum: dict[tuple[str, str], float] = field(default_factory=dict)
    duration_count: dict[tuple[str, str], int] = field(default_factory=dict)
    duration_buckets: dict[tuple[str, str, float], int] = field(default_factory=dict)
    active: dict[tuple[str, str], int] = field(default_factory=dict)


@dataclass
class _SseFailureMetricState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    failures_total: dict[tuple[str, str, str, str], int] = field(default_factory=dict)


_HTTP_STATE = _HttpMetricState()
_OPERATION_STATE = _OperationMetricState()
_SSE_FAILURE_STATE = _SseFailureMetricState()
_SSE_FAILURE_STATUSES = frozenset({"error", "cancelled", "fallback_missing"})


def _reset_prometheus_metrics_state() -> None:
    with _HTTP_STATE.lock:
        _HTTP_STATE.requests_total.clear()
        _HTTP_STATE.request_last_seen.clear()
        _HTTP_STATE.duration_sum.clear()
        _HTTP_STATE.duration_count.clear()
        _HTTP_STATE.duration_buckets.clear()
        _HTTP_STATE.in_progress.clear()
    with _OPERATION_STATE.lock:
        _OPERATION_STATE.total.clear()
        _OPERATION_STATE.duration_sum.clear()
        _OPERATION_STATE.duration_count.clear()
        _OPERATION_STATE.duration_buckets.clear()
        _OPERATION_STATE.active.clear()
    with _SSE_FAILURE_STATE.lock:
        _SSE_FAILURE_STATE.failures_total.clear()


def _metric_line(name: str, value: int | float) -> str:
    return f"{name} {float(value):.6f}"


def _labeled_metric_line(name: str, labels: dict[str, str], value: int | float) -> str:
    rendered_labels = ",".join(
        f'{key}="{_escape_label_value(val)}"' for key, val in labels.items()
    )
    return f"{name}{{{rendered_labels}}} {float(value):.6f}"


def _metric_block(
    name: str, description: str, metric_type: str, value: int | float
) -> list[str]:
    return [
        f"# HELP {name} {description}",
        f"# TYPE {name} {metric_type}",
        _metric_line(name, value),
    ]


def _escape_label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _session_trace_id(session_id: str) -> str:
    return hashlib.md5(str(session_id or "unknown").encode("utf-8")).hexdigest()


def _route_template(path: str, route_path: str | None) -> str:
    if route_path:
        return route_path
    if not path:
        return "unknown"
    return "/".join(
        "{id}" if _DYNAMIC_PATH_SEGMENT_RE.match(segment) else segment
        for segment in path.split("/")
    )


def start_http_request(
    method: str, path: str, route_path: str | None = None
) -> tuple[float, str, str]:
    normalized_method = (method or "GET").upper()
    normalized_path = _route_template(path, route_path)
    with _HTTP_STATE.lock:
        key = (normalized_method, normalized_path)
        _HTTP_STATE.in_progress[key] = _HTTP_STATE.in_progress.get(key, 0) + 1
    return time.perf_counter(), normalized_method, normalized_path


def finish_http_request(
    started_at: float, method: str, path: str, status_code: int | str
) -> None:
    duration = max(time.perf_counter() - started_at, 0.0)
    status = str(status_code)
    key = (method, path)
    status_key = (method, path, status)

    with _HTTP_STATE.lock:
        _HTTP_STATE.requests_total[status_key] = (
            _HTTP_STATE.requests_total.get(status_key, 0) + 1
        )
        _HTTP_STATE.request_last_seen[status_key] = time.time()
        _HTTP_STATE.duration_sum[key] = (
            _HTTP_STATE.duration_sum.get(key, 0.0) + duration
        )
        _HTTP_STATE.duration_count[key] = _HTTP_STATE.duration_count.get(key, 0) + 1
        for bucket in _HTTP_DURATION_BUCKETS:
            if duration <= bucket:
                bucket_key = (method, path, bucket)
                _HTTP_STATE.duration_buckets[bucket_key] = (
                    _HTTP_STATE.duration_buckets.get(bucket_key, 0) + 1
                )
        in_progress = _HTTP_STATE.in_progress.get(key, 0)
        _HTTP_STATE.in_progress[key] = max(in_progress - 1, 0)


def start_operation(category: str, name: str) -> tuple[float, str, str]:
    normalized_category = (category or "unknown").strip() or "unknown"
    normalized_name = (name or "unknown").strip() or "unknown"
    key = (normalized_category, normalized_name)
    with _OPERATION_STATE.lock:
        _OPERATION_STATE.active[key] = _OPERATION_STATE.active.get(key, 0) + 1
    return time.perf_counter(), normalized_category, normalized_name


def finish_operation(started_at: float, category: str, name: str, status: str) -> None:
    duration = max(time.perf_counter() - started_at, 0.0)
    normalized_status = (status or "unknown").strip() or "unknown"
    key = (category, name)
    status_key = (category, name, normalized_status)

    with _OPERATION_STATE.lock:
        _OPERATION_STATE.total[status_key] = (
            _OPERATION_STATE.total.get(status_key, 0) + 1
        )
        _OPERATION_STATE.duration_sum[key] = (
            _OPERATION_STATE.duration_sum.get(key, 0.0) + duration
        )
        _OPERATION_STATE.duration_count[key] = (
            _OPERATION_STATE.duration_count.get(key, 0) + 1
        )
        for bucket in _HTTP_DURATION_BUCKETS:
            if duration <= bucket:
                bucket_key = (category, name, bucket)
                _OPERATION_STATE.duration_buckets[bucket_key] = (
                    _OPERATION_STATE.duration_buckets.get(bucket_key, 0) + 1
                )
        active = _OPERATION_STATE.active.get(key, 0)
        _OPERATION_STATE.active[key] = max(active - 1, 0)


def record_sse_stream_failure(stream: str, session_id: str, status: str) -> None:
    normalized_status = (status or "unknown").strip() or "unknown"
    if normalized_status not in _SSE_FAILURE_STATUSES:
        return
    normalized_stream = (stream or "unknown").strip() or "unknown"
    normalized_session_id = (session_id or "unknown").strip() or "unknown"
    key = (
        normalized_stream,
        normalized_session_id,
        _session_trace_id(normalized_session_id),
        normalized_status,
    )
    with _SSE_FAILURE_STATE.lock:
        _SSE_FAILURE_STATE.failures_total[key] = (
            _SSE_FAILURE_STATE.failures_total.get(key, 0) + 1
        )


def _parse_proc_status() -> dict[str, int]:
    values: dict[str, int] = {}
    try:
        with open("/proc/self/status", encoding="utf-8") as fh:
            for line in fh:
                if ":" not in line:
                    continue
                key, raw_value = line.split(":", 1)
                parts = raw_value.strip().split()
                if not parts:
                    continue
                if key in {"VmRSS", "VmSize"}:
                    values[key] = int(parts[0]) * 1024
                elif key == "Threads":
                    values[key] = int(parts[0])
    except OSError:
        pass
    return values


def _parse_proc_meminfo() -> dict[str, int]:
    values: dict[str, int] = {}
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if ":" not in line:
                    continue
                key, raw_value = line.split(":", 1)
                if key not in {"MemTotal", "MemAvailable", "MemFree"}:
                    continue
                parts = raw_value.strip().split()
                if parts:
                    values[key] = int(parts[0]) * 1024
    except OSError:
        pass
    return values


def _resident_memory_bytes(proc_status: dict[str, int]) -> int:
    if "VmRSS" in proc_status:
        return proc_status["VmRSS"]

    usage = resource.getrusage(resource.RUSAGE_SELF)
    if sys.platform == "darwin":
        return int(usage.ru_maxrss)
    return int(usage.ru_maxrss) * 1024


def _virtual_memory_bytes(proc_status: dict[str, int]) -> int:
    return proc_status.get("VmSize", 0)


def _open_fds() -> int:
    try:
        return len(os.listdir("/proc/self/fd"))
    except OSError:
        return 0


def _max_fds() -> int:
    try:
        soft_limit, _ = resource.getrlimit(resource.RLIMIT_NOFILE)
    except (OSError, ValueError):
        return 0
    if soft_limit == resource.RLIM_INFINITY:
        return 0
    return int(soft_limit)


def _system_memory_values() -> tuple[int, int]:
    meminfo = _parse_proc_meminfo()
    total = meminfo.get("MemTotal", 0)
    available = meminfo.get("MemAvailable", meminfo.get("MemFree", 0))
    if total:
        return total, max(total - available, 0)

    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        phys_pages = os.sysconf("SC_PHYS_PAGES")
        return int(page_size * phys_pages), 0
    except (OSError, ValueError):
        return 0, 0


def _load_average() -> Iterable[tuple[str, float]]:
    try:
        one, five, fifteen = os.getloadavg()
    except OSError:
        return ()
    return (
        ("sage_server_system_load1", one),
        ("sage_server_system_load5", five),
        ("sage_server_system_load15", fifteen),
    )


def _render_http_metrics() -> list[str]:
    lines = [
        "# HELP sage_server_http_requests_total Total HTTP requests handled by the Sage server.",
        "# TYPE sage_server_http_requests_total counter",
    ]
    with _HTTP_STATE.lock:
        requests_total = dict(_HTTP_STATE.requests_total)
        request_last_seen = dict(_HTTP_STATE.request_last_seen)
        duration_sum = dict(_HTTP_STATE.duration_sum)
        duration_count = dict(_HTTP_STATE.duration_count)
        duration_buckets = dict(_HTTP_STATE.duration_buckets)
        in_progress = dict(_HTTP_STATE.in_progress)

    for method, path, status in sorted(requests_total):
        lines.append(
            _labeled_metric_line(
                "sage_server_http_requests_total",
                {"method": method, "path": path, "status": status},
                requests_total[(method, path, status)],
            )
        )

    lines.extend(
        [
            "# HELP sage_server_http_request_last_seen_timestamp_seconds Unix timestamp of the most recent completed HTTP request by method, path, and status.",
            "# TYPE sage_server_http_request_last_seen_timestamp_seconds gauge",
        ]
    )
    for method, path, status in sorted(request_last_seen):
        lines.append(
            _labeled_metric_line(
                "sage_server_http_request_last_seen_timestamp_seconds",
                {"method": method, "path": path, "status": status},
                request_last_seen[(method, path, status)],
            )
        )

    lines.extend(
        [
            "# HELP sage_server_http_request_duration_seconds HTTP request duration in seconds.",
            "# TYPE sage_server_http_request_duration_seconds histogram",
        ]
    )
    duration_keys = sorted(set(duration_count) | set(duration_sum))
    for method, path in duration_keys:
        cumulative = 0
        for bucket in _HTTP_DURATION_BUCKETS:
            cumulative = duration_buckets.get((method, path, bucket), cumulative)
            lines.append(
                _labeled_metric_line(
                    "sage_server_http_request_duration_seconds_bucket",
                    {"method": method, "path": path, "le": str(bucket)},
                    cumulative,
                )
            )
        lines.append(
            _labeled_metric_line(
                "sage_server_http_request_duration_seconds_bucket",
                {"method": method, "path": path, "le": "+Inf"},
                duration_count.get((method, path), 0),
            )
        )
        lines.append(
            _labeled_metric_line(
                "sage_server_http_request_duration_seconds_sum",
                {"method": method, "path": path},
                duration_sum.get((method, path), 0.0),
            )
        )
        lines.append(
            _labeled_metric_line(
                "sage_server_http_request_duration_seconds_count",
                {"method": method, "path": path},
                duration_count.get((method, path), 0),
            )
        )

    lines.extend(
        [
            "# HELP sage_server_http_requests_in_progress HTTP requests currently being processed.",
            "# TYPE sage_server_http_requests_in_progress gauge",
        ]
    )
    for method, path in sorted(in_progress):
        lines.append(
            _labeled_metric_line(
                "sage_server_http_requests_in_progress",
                {"method": method, "path": path},
                in_progress[(method, path)],
            )
        )
    return lines


def _render_python_metrics() -> list[str]:
    lines: list[str] = []
    lines.extend(
        _metric_block(
            "sage_server_python_objects",
            "Objects currently tracked by the Python garbage collector.",
            "gauge",
            len(gc.get_objects()),
        )
    )
    lines.extend(
        [
            "# HELP sage_server_python_gc_collections_total Python GC collections by generation.",
            "# TYPE sage_server_python_gc_collections_total counter",
        ]
    )
    for generation, stats in enumerate(gc.get_stats()):
        lines.append(
            _labeled_metric_line(
                "sage_server_python_gc_collections_total",
                {"generation": str(generation)},
                stats.get("collections", 0),
            )
        )
    return lines


def _render_operation_metrics() -> list[str]:
    lines = [
        "# HELP sage_server_operations_total Total Sage server operations by category, name, and status.",
        "# TYPE sage_server_operations_total counter",
    ]
    with _OPERATION_STATE.lock:
        total = dict(_OPERATION_STATE.total)
        duration_sum = dict(_OPERATION_STATE.duration_sum)
        duration_count = dict(_OPERATION_STATE.duration_count)
        duration_buckets = dict(_OPERATION_STATE.duration_buckets)
        active = dict(_OPERATION_STATE.active)

    for category, name, status in sorted(total):
        lines.append(
            _labeled_metric_line(
                "sage_server_operations_total",
                {"category": category, "name": name, "status": status},
                total[(category, name, status)],
            )
        )

    lines.extend(
        [
            "# HELP sage_server_operation_duration_seconds Sage server operation duration in seconds.",
            "# TYPE sage_server_operation_duration_seconds histogram",
        ]
    )
    duration_keys = sorted(set(duration_count) | set(duration_sum))
    for category, name in duration_keys:
        cumulative = 0
        for bucket in _HTTP_DURATION_BUCKETS:
            cumulative = duration_buckets.get((category, name, bucket), cumulative)
            lines.append(
                _labeled_metric_line(
                    "sage_server_operation_duration_seconds_bucket",
                    {"category": category, "name": name, "le": str(bucket)},
                    cumulative,
                )
            )
        lines.append(
            _labeled_metric_line(
                "sage_server_operation_duration_seconds_bucket",
                {"category": category, "name": name, "le": "+Inf"},
                duration_count.get((category, name), 0),
            )
        )
        lines.append(
            _labeled_metric_line(
                "sage_server_operation_duration_seconds_sum",
                {"category": category, "name": name},
                duration_sum.get((category, name), 0.0),
            )
        )
        lines.append(
            _labeled_metric_line(
                "sage_server_operation_duration_seconds_count",
                {"category": category, "name": name},
                duration_count.get((category, name), 0),
            )
        )

    lines.extend(
        [
            "# HELP sage_server_operations_active Sage server operations currently in progress.",
            "# TYPE sage_server_operations_active gauge",
        ]
    )
    for category, name in sorted(active):
        lines.append(
            _labeled_metric_line(
                "sage_server_operations_active",
                {"category": category, "name": name},
                active[(category, name)],
            )
        )
    return lines


def _render_sse_failure_metrics() -> list[str]:
    lines = [
        "# HELP sage_server_sse_stream_failures_total SSE stream failures with session_id for drilldown.",
        "# TYPE sage_server_sse_stream_failures_total counter",
    ]
    with _SSE_FAILURE_STATE.lock:
        failures_total = dict(_SSE_FAILURE_STATE.failures_total)

    for stream, session_id, trace_id, status in sorted(failures_total):
        lines.append(
            _labeled_metric_line(
                "sage_server_sse_stream_failures_total",
                {
                    "stream": stream,
                    "session_id": session_id,
                    "trace_id": trace_id,
                    "status": status,
                },
                failures_total[(stream, session_id, trace_id, status)],
            )
        )
    return lines


def render_prometheus_metrics() -> str:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    proc_status = _parse_proc_status()
    system_memory_total, system_memory_used = _system_memory_values()

    lines: list[str] = []
    metrics = [
        (
            "sage_server_process_cpu_seconds_total",
            "Total user and system CPU time consumed by the Sage server process.",
            "counter",
            usage.ru_utime + usage.ru_stime,
        ),
        (
            "sage_server_process_resident_memory_bytes",
            "Resident memory size used by the Sage server process.",
            "gauge",
            _resident_memory_bytes(proc_status),
        ),
        (
            "sage_server_process_virtual_memory_bytes",
            "Virtual memory size used by the Sage server process.",
            "gauge",
            _virtual_memory_bytes(proc_status),
        ),
        (
            "sage_server_process_threads",
            "Number of threads in the Sage server process.",
            "gauge",
            proc_status.get("Threads", threading.active_count()),
        ),
        (
            "sage_server_process_open_fds",
            "Number of open file descriptors in the Sage server process.",
            "gauge",
            _open_fds(),
        ),
        (
            "sage_server_process_max_fds",
            "Soft limit for open file descriptors in the Sage server process.",
            "gauge",
            _max_fds(),
        ),
        (
            "sage_server_process_start_time_seconds",
            "Unix timestamp for when this Python process imported the metrics module.",
            "gauge",
            _PROCESS_START_TIME,
        ),
        (
            "sage_server_uptime_seconds",
            "Seconds since this Python process imported the metrics module.",
            "gauge",
            time.time() - _PROCESS_START_TIME,
        ),
        (
            "sage_server_system_memory_total_bytes",
            "Total physical memory visible to the Sage server process.",
            "gauge",
            system_memory_total,
        ),
        (
            "sage_server_system_memory_used_bytes",
            "Used physical memory visible to the Sage server process.",
            "gauge",
            system_memory_used,
        ),
    ]

    for name, description, metric_type, value in metrics:
        lines.extend(_metric_block(name, description, metric_type, value))

    for name, value in _load_average():
        lines.extend(
            _metric_block(name, f"{name} from os.getloadavg().", "gauge", value)
        )

    lines.extend(_render_python_metrics())
    lines.extend(_render_http_metrics())
    lines.extend(_render_operation_metrics())
    lines.extend(_render_sse_failure_metrics())
    try:
        from sagents.observability.prometheus_handler import (
            render_prometheus_trace_metrics,
        )

        lines.append(render_prometheus_trace_metrics().rstrip("\n"))
    except Exception:
        pass

    return "\n".join(lines) + "\n"

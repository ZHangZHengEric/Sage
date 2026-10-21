"""Bounded timing capture and native-span enrichment, independent of backends."""

from __future__ import annotations
from collections import OrderedDict
from collections.abc import Callable
from datetime import datetime, timezone
import json
import time
from threading import RLock
from sagents.v2.contracts.common import utc_now
from ..contracts import LogRecord, TraceEvent, TraceExportSink, TraceSpan, TraceStatus
from .aggregation import EVENTS, build_run, normalize_timing_rows, timestamp

SPAN_NAME = "agent.run"
PAYLOAD = "sage.performance.data"
MODEL_FIELDS = frozenset(
    {
        "session_id",
        "run_id",
        "request_id",
        "started_at",
        "completed_at",
        "first_token_at",
        "purpose",
        "turn_id",
    }
)
LOG_FIELDS = frozenset(
    {
        "session_id",
        "run_id",
        "event",
        "timestamp",
        "request_id",
        "tool_call_id",
        "turn_id",
    }
)
LOG_ATTRIBUTES = frozenset(
    {"agent_id", "purpose", "started_at", "run_state", "duration_ms", "first_text_ms"}
)


class PerformanceCapture:
    """Accumulate timings until host cleanup completes, then enrich the native span."""

    def __init__(
        self,
        *,
        service,
        environment,
        raw_capture,
        on_failure: Callable[[], None],
        max_entries=1024,
        max_rows=4096,
        idle_seconds=300,
    ):
        if min(max_entries, max_rows, idle_seconds) <= 0:
            raise ValueError("invalid performance retention limits")
        self.service, self.environment = service, environment
        self.raw_capture, self._on_failure = raw_capture, on_failure
        self.closed = False
        self._performance = OrderedDict()
        self._performance_max_entries = max_entries
        self._performance_max_rows = max_rows
        self._performance_idle_seconds = idle_seconds
        self._performance_lock = RLock()

    def _pending(self, key):
        now = time.monotonic()
        while self._performance:
            first = next(iter(self._performance))
            if (
                now - self._performance[first]["last_seen"]
                < self._performance_idle_seconds
            ):
                break
            _, expired = self._performance.popitem(last=False)
            self._discard_performance(expired, "expired")
        pending = self._performance.pop(key, None)
        if pending is None:
            while len(self._performance) >= self._performance_max_entries:
                _, overflow = self._performance.popitem(last=False)
                self._discard_performance(overflow, "entry_limit")
            pending = {
                "rows": [],
                "span": None,
                "sink": None,
                "ended_span": None,
                "host_managed": False,
                "finished_requested": False,
                "raw_logs": 0,
                "raw_logs_dropped": 0,
                "dropped_rows": 0,
            }
        pending["last_seen"] = now
        self._performance[key] = pending
        return pending

    def _discard_performance(self, pending, reason):
        self._on_failure()
        # Keep only observed cohort/start facts on the native span. Otherwise a
        # later resume could look complete after its earlier segment vanished.
        anchors = []
        seen = set()
        for row in pending["rows"]:
            event = row["data"].get("event")
            if (
                event
                in {
                    "server.run.performance.accepted",
                    "server.run.performance.resuming",
                    "agent.run.started",
                }
                and event not in seen
            ):
                seen.add(event)
                anchors.append(row)
        loss = {
            "sage.performance.incomplete": True,
            "sage.performance.loss_reason": reason,
            "sage.performance.format": "events/v3",
            PAYLOAD: json.dumps(anchors, default=str),
            "sage.performance.service": self.service,
            "sage.performance.environment": self.environment,
        }
        if anchors:
            starts = [row["at"] for row in anchors]
            starts.extend(
                timestamp(row["data"]["attributes"]["started_at"])
                for row in anchors
                if row["data"].get("attributes", {}).get("started_at")
            )
            loss["sage.performance.started_at"] = datetime.fromtimestamp(
                min(starts), timezone.utc
            ).isoformat()
        if pending["span"] is not None:
            # The live handle carries this marker to its eventual native end.
            # Only observation state is discarded; execution continues normally.
            pending["span"].attributes.update(loss)
        if pending["ended_span"] is not None:
            ended = pending["ended_span"]
            pending["sink"].export_span(
                ended.model_copy(update={"attributes": {**ended.attributes, **loss}})
            )

    def raw_record_admitted(self, kind, session_id, run_id, accepted):
        if kind == "log":
            with self._performance_lock:
                pending = self._performance.get((session_id, run_id))
                if pending is None:
                    return
                pending["raw_logs"] += 1
                pending["raw_logs_dropped"] += not accepted

    def span_started(self, sink: TraceExportSink, span: TraceSpan) -> None:
        if (
            self.closed
            or span.name != SPAN_NAME
            or not span.session_id
            or not span.run_id
        ):
            return
        with self._performance_lock:
            pending = self._pending((span.session_id, span.run_id))
            pending.update(span=span, sink=sink)

    def defer_span_end(self, sink: TraceExportSink, span: TraceSpan) -> bool:
        if span.name != SPAN_NAME:
            return False
        key = span.session_id, span.run_id
        with self._performance_lock:
            pending = self._performance.get(key)
            if (
                pending is None
                or pending["span"] is None
                or pending["span"].span_id != span.span_id
            ):
                return False
            pending["ended_span"] = span
            if pending["finished_requested"]:
                self._finish_performance(key)
            # Keep the Agent's own end timestamp, but allow host cleanup timing
            # and final Run logs to be added before the existing span is exported.
            return True

    def flush_trace_sink(self, sink: TraceExportSink) -> None:
        with self._performance_lock:
            for key in list(self._performance):
                if self._performance[key]["sink"] is sink:
                    self._finish_performance(key, incomplete=True)

    def emit(self, kind, row, *, at=None):
        if self.closed or not row.get("session_id") or not row.get("run_id"):
            return
        allowed = MODEL_FIELDS if kind == "model" else LOG_FIELDS
        data = {k: v for k, v in row.items() if k in allowed}
        if kind == "log":
            data["attributes"] = {
                k: v
                for k, v in row.get("attributes", {}).items()
                if k in LOG_ATTRIBUTES
            }
        try:
            observed = timestamp(at) if at is not None else utc_now().timestamp()
            key = row["session_id"], row["run_id"]
            with self._performance_lock:
                pending = self._pending(key)
                if len(pending["rows"]) < self._performance_max_rows:
                    pending["rows"].append({"kind": kind, "data": data, "at": observed})
                else:
                    pending["dropped_rows"] += 1
                    self._on_failure()
                event = data.get("event", "")
                if event in {
                    "server.run.performance.accepted",
                    "server.run.performance.resuming",
                }:
                    pending["host_managed"] = True
                if event == "server.run.performance.finished" or (
                    event.startswith("agent.run.")
                    and event != "agent.run.started"
                    and not pending["host_managed"]
                ):
                    self._finish_performance(key)
        except Exception:
            self._on_failure()

    def _finish_performance(self, key, *, incomplete=False):
        pending = self._performance.get(key)
        if pending is None:
            return
        if pending["span"] is None:
            # Completion cannot acquire a new execution span later. In
            # particular, the transport may have refused its root at admission.
            self._performance.pop(key)
            return
        if pending["ended_span"] is None and not incomplete:
            pending["finished_requested"] = True
            return
        self._performance.pop(key)
        enriched, additions = self._build_performance_span(
            pending, interrupted=incomplete
        )
        sink = pending["sink"]
        for event in additions:
            sink.add_event(enriched.span_id, event)
        sink.export_span(enriched)

    def _build_performance_span(self, pending, *, interrupted):
        """Project a finished timing buffer without changing capture state."""
        incomplete = interrupted or bool(pending["dropped_rows"])
        rows = pending["rows"]
        span = pending["ended_span"] or pending["span"].model_copy(
            update={
                "end_time": utc_now(),
                "status": TraceStatus.UNSET,
            }
        )
        attrs = {
            **span.attributes,
            PAYLOAD: json.dumps(rows, default=str),
            "sage.performance.format": "events/v3",
            "sage.performance.service": self.service,
            "sage.performance.environment": self.environment,
            "sage.performance.incomplete": incomplete,
            "sage.performance.dropped_rows": pending["dropped_rows"],
        }
        if self.raw_capture:
            attrs["sage.diagnostic.log_count"] = pending["raw_logs"]
            attrs["sage.diagnostic.dropped_log_records"] = pending["raw_logs_dropped"]
        if interrupted:
            attrs["sage.interrupted"] = True
        agent_ids = [
            r["data"].get("attributes", {}).get("agent_id")
            for r in rows
            if r["kind"] == "log"
        ]
        if any(agent_ids):
            attrs["agent_id"] = next(value for value in agent_ids if value)
        if rows:
            starts = [r["at"] for r in rows]
            starts.extend(
                timestamp(r["data"]["attributes"]["started_at"])
                for r in rows
                if r["kind"] == "log"
                and r["data"].get("event")
                in {
                    "server.run.performance.accepted",
                    "server.run.performance.resuming",
                }
                and r["data"].get("attributes", {}).get("started_at")
            )
            attrs.update(
                {
                    "sage.performance.started_at": datetime.fromtimestamp(
                        min(starts), timezone.utc
                    ).isoformat(),
                    "sage.performance.finished_at": datetime.fromtimestamp(
                        max(r["at"] for r in rows), timezone.utc
                    ).isoformat(),
                }
            )
        events, models = normalize_timing_rows(rows, incomplete=incomplete)
        run_id = span.run_id
        summary = build_run(events[run_id], models[run_id])
        if summary is not None:
            attrs.update(
                {
                    "sage.performance." + field: summary[field]
                    for field in (
                        "total_ms",
                        "first_token_ms",
                        "first_text_ms",
                        "model_ms",
                        "tool_ms",
                        "framework_ms",
                        "coverage",
                    )
                    if summary.get(field) is not None
                }
            )
        additions = [
            TraceEvent(
                name="sage.performance." + r["kind"],
                timestamp=datetime.fromtimestamp(r["at"], timezone.utc),
                attributes={
                    "kind": r["kind"],
                    PAYLOAD: json.dumps(r["data"], default=str),
                },
            )
            for r in rows
        ]
        enriched = span.model_copy(
            update={"attributes": attrs, "events": [*span.events, *additions]}
        )
        return enriched, additions

    def begin_log(self, record: LogRecord) -> None:
        if (
            not self.closed
            and record.session_id
            and record.run_id
            and record.event
            in {
                "server.run.performance.accepted",
                "server.run.performance.resuming",
                "agent.run.started",
            }
        ):
            # Count the first raw log of a segment, but late replay/download
            # logs must not resurrect an already exported performance buffer.
            with self._performance_lock:
                self._pending((record.session_id, record.run_id))

    def write(self, record: LogRecord) -> None:
        if record.event in EVENTS:
            self.emit(
                "log",
                {
                    **{key: getattr(record, key) for key in LOG_FIELDS},
                    "attributes": record.attributes,
                },
                at=record.timestamp,
            )

    def close(self):
        self.closed = True
        with self._performance_lock:
            for key in list(self._performance):
                try:
                    self._finish_performance(key, incomplete=True)
                except Exception:
                    self._on_failure()

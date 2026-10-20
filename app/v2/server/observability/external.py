"""Server timing projection and observation-backend configuration."""
from __future__ import annotations
import asyncio
from collections import defaultdict, OrderedDict
from datetime import datetime, timezone
import json
import os
import time
from urllib.parse import unquote
from threading import RLock
import httpx
from sagents.v2.contracts.common import utc_now
from sagents.v2.runtime.observability.contracts import TraceEvent, TraceStatus
from sagents.v2.runtime.observability.plugins.external import ExternalEvidenceSink
from sagents.v2.runtime.observability.query import QueryCache
from sagents.v2.runtime.observability.plugins.diagnostic_noop import NoopDiagnosticSink
from .performance import EVENTS, build_run, timing_report, timestamp

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


class ExternalDiagnostics(ExternalEvidenceSink):
    """Host timing projection over the observation evidence capability."""

    def __init__(self, *, performance_max_entries=1024, performance_max_rows=4096,
                 performance_idle_seconds=300, **options):
        if min(performance_max_entries, performance_max_rows, performance_idle_seconds) <= 0:
            raise ValueError('invalid performance retention limits')
        super().__init__(**options)
        self._performance = OrderedDict()
        self._performance_max_entries = performance_max_entries
        self._performance_max_rows = performance_max_rows
        self._performance_idle_seconds = performance_idle_seconds
        self._performance_lock = RLock()
        self._query_cache = QueryCache()

    def bind_trace_sink(self, sink):
        if self.trace_sink is None:
            self.trace_sink = sink
        setter = getattr(sink, "set_span_observer", None)
        if callable(setter):
            setter(self)

    def _pending(self, key):
        now = time.monotonic()
        while self._performance:
            first = next(iter(self._performance))
            if now - self._performance[first]['last_seen'] < self._performance_idle_seconds:
                break
            _, expired = self._performance.popitem(last=False)
            self._discard_performance(expired, 'expired')
        pending = self._performance.pop(key, None)
        if pending is None:
            while len(self._performance) >= self._performance_max_entries:
                _, overflow = self._performance.popitem(last=False)
                self._discard_performance(overflow, 'entry_limit')
            pending = {
            "rows": [], "span": None, "sink": None, "ended_span": None,
            "host_managed": False, "finished_requested": False,
            "raw_logs": 0, "raw_logs_dropped": 0,
            "dropped_rows": 0,
            }
        pending['last_seen'] = now
        self._performance[key] = pending
        return pending

    def _discard_performance(self, pending, reason):
        self.capture_failures += 1
        # Keep only observed cohort/start facts on the native span. Otherwise a
        # later resume could look complete after its earlier segment vanished.
        anchors = []
        seen = set()
        for row in pending['rows']:
            event = row['data'].get('event')
            if event in {'server.run.performance.accepted', 'server.run.performance.resuming', 'agent.run.started'} and event not in seen:
                seen.add(event)
                anchors.append(row)
        loss = {'sage.performance.incomplete': True, 'sage.performance.loss_reason': reason,
                'sage.performance.format': 'events/v3', PAYLOAD: json.dumps(anchors, default=str),
                'sage.performance.service': self.service, 'sage.performance.environment': self.environment}
        if anchors:
            starts = [row['at'] for row in anchors]
            starts.extend(timestamp(row['data']['attributes']['started_at']) for row in anchors
                          if row['data'].get('attributes', {}).get('started_at'))
            loss['sage.performance.started_at'] = datetime.fromtimestamp(min(starts), timezone.utc).isoformat()
        if pending['span'] is not None:
            # The live handle carries this marker to its eventual native end.
            # Only observation state is discarded; execution continues normally.
            pending['span'].attributes.update(loss)
        if pending['ended_span'] is not None:
            ended = pending['ended_span']
            pending['sink'].export_span(ended.model_copy(update={'attributes': {**ended.attributes, **loss}}))

    def _raw_record_admitted(self, kind, session_id, run_id, accepted):
        if kind == "log":
            with self._performance_lock:
                pending = self._performance.get((session_id, run_id))
                if pending is None:
                    return
                pending["raw_logs"] += 1
                pending["raw_logs_dropped"] += not accepted

    def span_started(self, sink, span):
        if self.closed or span.name != SPAN_NAME or not span.session_id or not span.run_id:
            return
        with self._performance_lock:
            pending = self._pending((span.session_id, span.run_id))
            pending.update(span=span, sink=sink)

    def defer_span_end(self, sink, span):
        if span.name != SPAN_NAME:
            return False
        key = span.session_id, span.run_id
        with self._performance_lock:
            pending = self._performance.get(key)
            if pending is None or pending["span"] is None or pending["span"].span_id != span.span_id:
                return False
            pending["ended_span"] = span
            if pending["finished_requested"]:
                self._finish_performance(key)
            # Keep the Agent's own end timestamp, but allow host cleanup timing
            # and final Run logs to be added before the existing span is exported.
            return True

    def flush_trace_sink(self, sink):
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
                k: v for k, v in row.get("attributes", {}).items() if k in LOG_ATTRIBUTES
            }
        try:
            observed = timestamp(at) if at is not None else utc_now().timestamp()
            key = row["session_id"], row["run_id"]
            with self._performance_lock:
                pending = self._pending(key)
                if len(pending['rows']) < self._performance_max_rows:
                    pending["rows"].append({"kind": kind, "data": data, "at": observed})
                else:
                    pending['dropped_rows'] += 1
                    self.capture_failures += 1
                event = data.get("event", "")
                if event in {"server.run.performance.accepted", "server.run.performance.resuming"}:
                    pending["host_managed"] = True
                if event == "server.run.performance.finished" or (
                    event.startswith("agent.run.") and event != "agent.run.started" and not pending["host_managed"]
                ):
                    self._finish_performance(key)
        except Exception:
            self.capture_failures += 1

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
        interrupted = incomplete
        incomplete = incomplete or bool(pending['dropped_rows'])
        rows = pending["rows"]
        span = pending["ended_span"] or pending["span"].model_copy(update={
            "end_time": utc_now(), "status": TraceStatus.UNSET,
        })
        attrs = {**span.attributes, PAYLOAD: json.dumps(rows, default=str),
                 "sage.performance.format": "events/v3",
                 "sage.performance.service": self.service,
                 "sage.performance.environment": self.environment,
                 "sage.performance.incomplete": incomplete,
                 "sage.performance.dropped_rows": pending['dropped_rows']}
        if self.raw_capture:
            attrs["sage.diagnostic.log_count"] = pending["raw_logs"]
            attrs["sage.diagnostic.dropped_log_records"] = pending["raw_logs_dropped"]
        if interrupted:
            attrs["sage.interrupted"] = True
        agent_ids = [r["data"].get("attributes", {}).get("agent_id") for r in rows if r["kind"] == "log"]
        if any(agent_ids):
            attrs["agent_id"] = next(value for value in agent_ids if value)
        if rows:
            starts = [r["at"] for r in rows]
            starts.extend(timestamp(r["data"]["attributes"]["started_at"])
                          for r in rows if r["kind"] == "log"
                          and r["data"].get("event") in {
                              "server.run.performance.accepted", "server.run.performance.resuming"}
                          and r["data"].get("attributes", {}).get("started_at"))
            attrs.update({"sage.performance.started_at": datetime.fromtimestamp(min(starts), timezone.utc).isoformat(),
                          "sage.performance.finished_at": datetime.fromtimestamp(max(r["at"] for r in rows), timezone.utc).isoformat()})
        events, models = timing_rows([{
            "name": span.name, "start_time": span.start_time, "attributes": attrs,
            "context": {"trace_id": span.trace_id, "span_id": span.span_id},
        }])
        summary = build_run(events[key[1]], models[key[1]])
        if summary is not None:
            attrs.update({"sage.performance." + field: summary[field]
                for field in ("total_ms", "first_token_ms", "first_text_ms", "model_ms", "tool_ms", "framework_ms", "coverage")
                if summary.get(field) is not None})
        additions = [TraceEvent(name="sage.performance." + r["kind"],
                               timestamp=datetime.fromtimestamp(r["at"], timezone.utc),
                               attributes={"kind": r["kind"], PAYLOAD: json.dumps(r["data"], default=str)})
                     for r in rows]
        enriched = span.model_copy(update={"attributes": attrs, "events": [*span.events, *additions]})
        sink = pending["sink"]
        for event in additions:
            sink.add_event(span.span_id, event)
        sink.export_span(enriched)

    async def close(self):
        self.closed = True
        await self._query_cache.close()
        with self._performance_lock:
            for key in list(self._performance):
                try:
                    self._finish_performance(key, incomplete=True)
                except Exception:
                    self.capture_failures += 1
        await super().close()

    def _model(self, session_id, request, **fields):
        self.emit(
            "model",
            dict(
                session_id=session_id,
                run_id=request.run_id,
                request_id=request.request_id,
                **fields,
            ),
        )

    async def report(
        self,
        *,
        start,
        end,
        agent_id="",
        bucket="hour",
        timezone_name="Asia/Shanghai",
        client=None,
    ):
        async def build():
            if client is None:
                async with httpx.AsyncClient() as owned:
                    return await self._report(owned, start=start, end=end, agent_id=agent_id,
                                              bucket=bucket, timezone_name=timezone_name)
            return await self._report(client, start=start, end=end, agent_id=agent_id,
                                      bucket=bucket, timezone_name=timezone_name)
        return await self._query_cache.get((start, end, agent_id, bucket, timezone_name), build)

    async def _report(self, client, *, start, end, agent_id, bucket, timezone_name):
        spans, truncated = await self._query(client, start=start, end=end, agent_id=agent_id)
        def aggregate():
            events, models = timing_rows(spans)
            return timing_report(events, models, start=start, end=end, agent_id=agent_id,
                                 bucket=bucket, timezone_name=timezone_name, truncated=truncated)
        result = await asyncio.to_thread(aggregate)
        result.update(source=self.backend, capture_failures=self.capture_failures)
        return result

    def write(self, record):
        if (not self.closed and record.session_id and record.run_id and record.event in {
            'server.run.performance.accepted', 'server.run.performance.resuming', 'agent.run.started',
        }):
            # Count the first raw log of a segment, but late replay/download
            # logs must not resurrect an already exported performance buffer.
            with self._performance_lock:
                self._pending((record.session_id, record.run_id))
        super().write(record)
        if record.event in EVENTS:
            self.emit("log", {**{key: getattr(record, key) for key in LOG_FIELDS},
                              "attributes": record.attributes}, at=record.timestamp)

def timing_rows(spans):
    events, models = defaultdict(list), defaultdict(dict)
    seen = set()
    rows = []
    for span in sorted(spans, key=lambda s: timestamp(s["start_time"])):
        attrs = span["attributes"]
        if span["name"] != SPAN_NAME or attrs.get("sage.performance.format") != "events/v3":
            continue
        identity = (span["context"]["trace_id"], span["context"]["span_id"])
        if identity in seen:
            continue
        seen.add(identity)
        payload = attrs[PAYLOAD]
        rows.extend({**row, '_observation_incomplete': bool(attrs.get('sage.performance.incomplete'))}
                    for row in json.loads("".join(payload) if isinstance(payload, (list, tuple)) else payload))
    for observation in sorted(rows, key=lambda r: r["at"]):
        row = observation["data"]
        rid = row["run_id"]
        if observation["kind"] == "model":
            models[rid].setdefault(row["request_id"], {}).update(row)
            continue
        values = row.get("attributes", {})
        event = dict(
            session_id=row["session_id"],
            run_id=rid,
            event=row["event"],
            at=timestamp(row["timestamp"]),
            agent_id=values.get("agent_id"),
            identity=row.get("tool_call_id")
            if row["event"].startswith("tool.")
            else row.get("request_id"),
            purpose=values.get("purpose"),
            turn_id=row.get("turn_id"),
            started_at=timestamp(values.get("started_at")),
            state=values.get("run_state"),
            _observation_incomplete=observation.get('_observation_incomplete', False),
        )
        events[rid].append(event)
        if (
            row["event"] == "model.request.completed"
            and values.get("first_text_ms") is not None
            and values.get("duration_ms") is not None
        ):
            events[rid].append(
                {
                    **event,
                    "event": "model.first_text",
                    "at": event["at"]
                    - (values["duration_ms"] - values["first_text_ms"]) / 1000,
                }
            )
    normalized = defaultdict(list)
    for rid, requests in models.items():
        for row in requests.values():
            normalized[rid].append(
                {
                    **row,
                    "started_at": timestamp(row.get("started_at")),
                    "ended_at": timestamp(row.get("completed_at")),
                    "first_token_at": timestamp(row.get("first_token_at")),
                    "purpose": row.get("purpose", "agent"),
                }
            )
    return events, normalized


class UnqueryableDiagnostics(NoopDiagnosticSink):
    """An exporter without a supported query API must not enable local capture."""

    available = False
    raw_capture = False
    capture_failures = 0
    closed = False

    def __init__(self, backend):
        self.backend = backend

    def write(self, record):
        pass

    async def close(self):
        self.closed = True

    async def export_evidence(self, session_id, run_ids):
        raise NotImplementedError(f"{self.backend} does not support diagnostic queries")


def external_diagnostics(settings, selection):
    """Use the effective plugin choice, including saved admin overrides."""
    config = selection.config
    if selection.plugin == "sage.trace.phoenix":
        endpoint = config["endpoint"].rstrip("/")
        base = endpoint.removesuffix("/v1/traces")
        backend = "phoenix"
    elif (
        selection.plugin == "sage.trace.otlp"
        and settings.jaeger_url
        and not settings.trace_otlp_endpoint
    ):
        base, backend = settings.jaeger_public_url, "jaeger"
    elif selection.plugin != "sage.trace.noop":
        return UnqueryableDiagnostics(selection.plugin)
    else:
        return None
    headers = {}
    for entry in (
        os.getenv(settings.trace_query_headers_env, "")
        or os.getenv("OTEL_EXPORTER_OTLP_HEADERS", "")
    ).split(","):
        key, sep, value = entry.partition("=")
        if sep:
            headers[unquote(key.strip())] = unquote(value.strip())
    if backend == "phoenix" and (
        key := os.getenv(config.get("api_key_env", "PHOENIX_API_KEY"))
    ):
        headers["Authorization"] = f"Bearer {key}"
    return ExternalDiagnostics(
        backend=backend,
        query_url=settings.trace_query_url or base,
        project=config.get("project_name", "sage"),
        service=config.get("service_name", settings.trace_service_name),
        environment=config.get("environment", settings.trace_environment),
        headers=headers,
    )

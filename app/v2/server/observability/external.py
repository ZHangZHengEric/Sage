"""Server timing projection and observation-backend configuration."""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from urllib.parse import unquote
from uuid import uuid4
import httpx
from sagents.v2.contracts.common import utc_now
from sagents.v2.runtime.observability.contracts import TraceSpan
from sagents.v2.runtime.observability.evidence import ExternalEvidenceSink
from sagents.v2.runtime.observability.plugins.diagnostic_noop import NoopDiagnosticSink
from .performance import EVENTS, timing_report, timestamp

SPAN_NAME = "sage.performance"
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
            # The accepted boundary carries the SDK entry time, before admission.
            start = (
                timestamp(data["attributes"].get("started_at"))
                if kind == "log"
                and data.get("event") == "server.run.performance.accepted"
                else None
            )
            span = TraceSpan(
                trace_id=hashlib.sha256(
                    f"performance:{self.service}:{self.environment}:{row['run_id']}".encode()
                ).hexdigest()[:32],
                span_id=uuid4().hex[:16],
                name=SPAN_NAME,
                start_time=datetime.fromtimestamp(start or observed, timezone.utc),
                end_time=datetime.fromtimestamp(observed, timezone.utc),
                session_id=row["session_id"],
                run_id=row["run_id"],
                attributes={
                    PAYLOAD: json.dumps(data, default=str),
                    "sage.performance.kind": kind,
                    "sage.performance.event": data.get("event", "model"),
                    "sage.performance.service": self.service,
                    "sage.performance.environment": self.environment,
                },
            )
            if self.trace_sink is None:
                self.capture_failures += 1
                return
            self.trace_sink.start_span(span)
            self.trace_sink.end_span(span)
        except Exception:
            # A best-effort projection must not fail a model or recurse into logs.
            self.capture_failures += 1

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
        if client is None:
            async with httpx.AsyncClient() as owned:
                return await self.report(
                    start=start,
                    end=end,
                    agent_id=agent_id,
                    bucket=bucket,
                    timezone_name=timezone_name,
                    client=owned,
                )
        spans, truncated = await self._query(client, start=start, end=end)
        events, models = timing_rows(spans)
        result = timing_report(
            events,
            models,
            start=start,
            end=end,
            agent_id=agent_id,
            bucket=bucket,
            timezone_name=timezone_name,
            truncated=truncated,
        )
        result.update(source=self.backend, capture_failures=self.capture_failures)
        return result

    def write(self, record):
        super().write(record)
        if record.event in EVENTS:
            self.emit("log", record.model_dump(mode="python"), at=record.timestamp)

def timing_rows(spans):
    events, models = defaultdict(list), defaultdict(dict)
    seen = set()
    for span in sorted(spans, key=lambda s: timestamp(s["start_time"])):
        attrs = span["attributes"]
        if span["name"] != SPAN_NAME or PAYLOAD not in attrs:
            continue
        identity = (span["context"]["trace_id"], span["context"]["span_id"])
        if identity in seen:
            continue
        seen.add(identity)
        row = json.loads(attrs[PAYLOAD])
        rid = row["run_id"]
        if attrs["sage.performance.kind"] == "model":
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

"""External observation evidence capture and query, independent of business storage.

Phoenix REST and Jaeger Query v3 are read through the selected observation backend.
Only the host supplies the authorized Session and Run allowlist.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import traceback
from urllib.parse import quote, urlsplit
from uuid import uuid4
from threading import RLock
import httpx
from sagents.v2.contracts.common import utc_now
from sagents.v2.runtime.observability.contracts import TraceEvent, TraceSpan
from sagents.v2.runtime.observability.plugins.diagnostic_noop import NoopDiagnosticSink
from sagents.v2.runtime.observability.traces import current_trace_context, current_trace_sink
from sagents.v2.runtime.observability.tool_evidence import tool_evidence
from sagents.v2.runtime.observability.model_evidence import model_evidence

SPAN_NAME = "agent.run"

def timestamp(value):
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value.timestamp()


def _otlp_value(value):
    if "arrayValue" in value:
        return [_otlp_value(item) for item in value["arrayValue"].get("values", [])]
    return next(iter(value.values()), None)

class ExternalEvidenceSink(NoopDiagnosticSink):
    """Trace-backed diagnostic capability; never reads or writes Session storage."""
    available = True

    def __init__(
        self,
        *,
        backend,
        query_url,
        project="sage",
        service="sage-server",
        environment="production",
        headers=None,
        timeout=10,
    ):
        self.backend, self.query_url = backend, query_url.rstrip("/")
        parsed = urlsplit(self.query_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "trace query URL must be HTTP(S) without credentials, query or fragment"
            )
        self.project, self.service, self.environment = project, service, environment
        self.headers, self.timeout = dict(headers or {}), timeout
        self.trace_sink = None
        self.closed = False
        self.capture_failures = 0
        self.max_spans = 100000
        self._orphan_evidence = {}
        self._evidence_lock = RLock()

    @property
    def raw_capture(self):
        return (
            self.backend == "phoenix"
            and getattr(self.trace_sink, "content_mode", None) == "raw"
        )

    def _evidence(self, kind, *, session_id, run_id, **payload):
        if not self.raw_capture or self.closed or not session_id or not run_id:
            return
        try:
            active = current_trace_context()
            now = utc_now()
            event = TraceEvent(name="sage.diagnostic." + kind, timestamp=now,
                attributes={"sage.diagnostic.kind": kind,
                            "sage.diagnostic.data": json.dumps(payload, ensure_ascii=False, default=str),
                            "session_id": session_id, "run_id": run_id})
            log_target = self._log_target(session_id, run_id) if kind == "log" else None
            if log_target is not None:
                log_target[0].add_event(log_target[1], event)
            elif active and kind != "log":
                # Managed applications can have a different exporter instance
                # from the host; only the owning exporter has this live span.
                target = current_trace_sink() or self.trace_sink
                target.add_event(active[1], event)
            else:
                with self._evidence_lock:
                    self._orphan_evidence.setdefault((session_id, run_id), []).append(event)
        except Exception:
            self.capture_failures += 1

    def _log_target(self, session_id, run_id):
        return None

    async def begin_model_request(self, *, session_id, request, **kwargs):
        self._evidence(
            "request",
            session_id=session_id,
            run_id=request.run_id,
            request_id=request.request_id,
            request=kwargs.get("wire_request")
            if kwargs.get("wire_request") is not None
            else request.model_dump(mode="json"),
            normalized_request=request.model_dump(mode="json"),
            provider=kwargs.get("provider"),
            request_format="provider_wire" if kwargs.get("wire_request") is not None else "normalized",
        )
        self._model(
            session_id,
            request,
            started_at=utc_now().isoformat(),
            purpose=request.metadata.get("purpose", "agent"),
            turn_id=request.metadata.get("turn_id"),
        )

    async def complete_model_request(self, *, session_id, request, **kwargs):
        response = kwargs.get("response")
        self._evidence(
            "response",
            session_id=session_id,
            run_id=request.run_id,
            request_id=request.request_id,
            response=response.model_dump(mode="json") if response is not None else None,
        )
        self._model(session_id, request, completed_at=utc_now().isoformat())

    async def fail_model_request(self, *, session_id, request, **kwargs):
        error = kwargs.get("error")
        self._evidence(
            "failure",
            session_id=session_id,
            run_id=request.run_id,
            request_id=request.request_id,
            error={
                "type": type(error).__name__,
                "message": str(error),
                "stack_trace": "".join(traceback.format_exception(error)),
            }
            if error
            else None,
        )
        self._model(session_id, request, completed_at=utc_now().isoformat())

    async def record_model_first_token(self, *, session_id, request, observed_at):
        self._model(session_id, request, first_token_at=observed_at.isoformat())

    async def record_model_stream(self, *, session_id, request, evidence):
        self._evidence(
            "stream",
            session_id=session_id,
            run_id=request.run_id,
            request_id=request.request_id,
            stream=evidence,
        )

    def _take_evidence(self, key):
        with self._evidence_lock:
            return self._orphan_evidence.pop(key, [])

    async def close(self):
        self.closed = True
        # Standalone SDK use may have no host lifecycle or active Agent span.
        # Export one grouped observation per Run, rather than per log/model event.
        with self._evidence_lock:
            keys = list(self._orphan_evidence)
        for key in keys:
            events = self._take_evidence(key)
            try:
                span = TraceSpan(trace_id=hashlib.sha256(
                    f"diagnostic:{self.service}:{self.environment}:{key[1]}".encode()).hexdigest()[:32],
                    span_id=uuid4().hex[:16], name="sage.diagnostic",
                    session_id=key[0], run_id=key[1], events=events,
                    start_time=events[0].timestamp, end_time=events[-1].timestamp)
                self.trace_sink.start_span(span)
                for event in events:
                    self.trace_sink.add_event(span.span_id, event)
                self.trace_sink.end_span(span)
            except Exception:
                self.capture_failures += 1

    async def _request(self, client, path, params):
        # Do not follow a redirect with server credentials to a different host.
        async with client.stream(
            "GET",
            self.query_url + path,
            params=params,
            headers=self.headers,
            timeout=self.timeout,
            follow_redirects=False,
        ) as response:
            response.raise_for_status()
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if not self.raw_capture and len(body) > 32 * 1024 * 1024:
                    raise ValueError("trace query response exceeds limit")
        return body.decode()

    async def _phoenix(self, client, params):
        rows, cursor, seen = [], None, set()
        path = f"/v1/projects/{quote(self.project, safe='')}/spans"
        while True:
            query = [*params, ("limit", "1000")]
            if cursor:
                query.append(("cursor", cursor))
            payload = json.loads(await self._request(client, path, query))
            rows.extend(payload["data"])
            cursor = payload.get("next_cursor")
            if len(rows) >= self.max_spans:
                return rows[: self.max_spans], True
            if not cursor:
                return rows, False
            if cursor in seen:
                raise ValueError("trace query repeated a pagination cursor")
            seen.add(cursor)

    async def _query(self, client, *, start, end, session_id=None, run_id=None):
        # Agent execution can begin after the selected SDK-entry interval ends.
        # Discover completed Agent spans through now; timing_report applies the
        # exact original entry-time cohort from their performance attributes.
        discovery_end = max(end, utc_now().timestamp()) if session_id is None and run_id is None else end
        dates = {
            "start_time": datetime.fromtimestamp(start, timezone.utc).isoformat(),
            "end_time": datetime.fromtimestamp(discovery_end, timezone.utc).isoformat(),
        }
        if self.backend == "phoenix":
            filters = [
                ("attribute", f"sage.performance.service:{json.dumps(self.service)}"),
                (
                    "attribute",
                    f"sage.performance.environment:{json.dumps(self.environment)}",
                ),
            ]
            if session_id is not None:
                filters = [("attribute", f"session_id:{json.dumps(session_id)}")]
            params = [*dates.items(), *filters]
            if session_id is None:
                params.extend([("name", SPAN_NAME),
                               ("attribute", 'sage.performance.format:"events/v3"')])
            rows, truncated = await self._phoenix(client, params)
            complete = []
            if session_id is None:
                # Resumption can use a fresh execution trace. Select the cohort
                # by start time, then read every segment for the authorized Run.
                for run_id in sorted({s["attributes"]["run_id"] for s in rows}):
                    batch, cut = await self._phoenix(client, [*filters, ("name", SPAN_NAME),
                        ("attribute", f"run_id:{json.dumps(run_id)}"),
                        ("attribute", 'sage.performance.format:"events/v3"')])
                    complete.extend(batch)
                    truncated |= cut
                    if len(complete) >= self.max_spans:
                        return complete[:self.max_spans], True
            else:
                ids = sorted({s["context"]["trace_id"] for s in rows})
                for offset in range(0, len(ids), 100):
                    batch, cut = await self._phoenix(client, [("trace_id", t) for t in ids[offset:offset + 100]])
                    complete.extend(batch)
                    truncated |= cut
                    if len(complete) >= self.max_spans:
                        return complete[:self.max_spans], True
            return complete, truncated
        params = {
            "query.service_name": self.service,
            "query.start_time_min": dates["start_time"],
            "query.start_time_max": dates["end_time"],
            "query.search_depth": "10001",
            "query.raw_traces": "true",
            "query.attributes": json.dumps(
                {"session_id": session_id}
                if session_id
                else {
                    "sage.performance.environment": self.environment,
                    "sage.performance.format": "events/v3",
                    **({"run_id": run_id} if run_id is not None else {}),
                }
            ),
        }
        if session_id is None:
            params["query.operation_name"] = SPAN_NAME
        text = await self._request(client, "/api/v3/traces", params)
        rows, traces = [], set()
        for line in text.splitlines():
            envelope = json.loads(line)
            if "error" in envelope:
                raise ValueError("Jaeger query failed")
            for resource in envelope["result"].get("resourceSpans", []):
                for scope in resource.get("scopeSpans", []):
                    for span in scope.get("spans", []):
                        traces.add(span["traceId"])
                        rows.append(
                            {
                                "name": span["name"],
                                "context": {
                                    "trace_id": span["traceId"],
                                    "span_id": span["spanId"],
                                },
                                "start_time": int(span["startTimeUnixNano"]) / 1e9,
                                "end_time": int(span["endTimeUnixNano"]) / 1e9 if span.get("endTimeUnixNano") else None,
                                "status_code": {1:"OK", 2:"ERROR"}.get((span.get("status") or {}).get("code"), "UNSET"),
                                "status_message": (span.get("status") or {}).get("message"),
                                "otlp": span,
                                "events": [{"name": e["name"], "timestamp": int(e["timeUnixNano"]) / 1e9,
                                            "attributes": {a["key"]: _otlp_value(a["value"]) for a in e.get("attributes", [])}}
                                           for e in span.get("events", [])],
                                "resource": resource.get("resource", {}),
                                "attributes": {
                                    a["key"]: _otlp_value(a["value"])
                                    for a in span.get("attributes", [])
                                },
                            }
                        )
                        if len(rows) >= self.max_spans:
                            return rows, True
        truncated = len(traces) >= 10001
        if session_id is None and run_id is None:
            complete = []
            for identity in sorted({s["attributes"]["run_id"] for s in rows
                                    if s["name"] == SPAN_NAME}):
                batch, cut = await self._query(client, start=0, end=utc_now().timestamp(), run_id=identity)
                complete.extend(batch)
                truncated |= cut
                if len(complete) >= self.max_spans:
                    return complete[:self.max_spans], True
            return complete, truncated
        return rows, truncated

    async def snapshot(self, session_id, run_ids):
        async with httpx.AsyncClient() as client:
            spans, truncated = await self._query(
                client, start=0, end=utc_now().timestamp(), session_id=session_id
            )
        # Authoritative Session ownership/Run allowlist is checked by the caller.
        spans = [
            s
            for s in spans
            if s["attributes"].get("session_id") == session_id
            and s["attributes"].get("run_id") in run_ids
        ]
        models, logs = {}, []
        records = []
        for span in spans:
            for event in span.get("events", []):
                attrs = event.get("attributes", {})
                if "sage.diagnostic.data" in attrs:
                    # Scope is validated on both the containing span and event.
                    if attrs.get("session_id") != session_id or attrs.get("run_id") not in run_ids:
                        continue
                    records.append((timestamp(event["timestamp"]), attrs))
        for observed, attrs in sorted(records, key=lambda r: r[0]):
            payload = json.loads(attrs["sage.diagnostic.data"])
            if attrs["sage.diagnostic.kind"] == "log":
                logs.append(
                    dict(
                        payload,
                        session_id=attrs["session_id"],
                        run_id=attrs["run_id"],
                    )
                )
            else:
                identity = (attrs["run_id"], payload["request_id"])
                row = models.setdefault(
                    identity, dict(session_id=session_id, run_id=attrs["run_id"])
                )
                row.update(payload)
                kind = attrs["sage.diagnostic.kind"]
                observed_at = datetime.fromtimestamp(observed, timezone.utc).isoformat()
                if kind == "request":
                    row.update(status="started", started_at=observed_at)
                elif kind in {"response", "failure"}:
                    row.update(
                        status="completed" if kind == "response" else "failed",
                        completed_at=observed_at,
                    )
        projected_models = model_evidence(spans, models.values())
        return {
            **tool_evidence(spans, logs),
            "models": projected_models,
            "model_request_ids": sorted({r["request_id"] for r in projected_models}),
            "capture_modes": sorted({s["attributes"].get("sage.content.mode", "unknown") for s in spans}),
            "logs": logs,
            "traces": spans,
            "source": self.backend,
            "unavailable": False,
            "truncated": truncated,
            "raw_model_streams_available": any(
                row.get("stream", {}).get("wire_capture_available", False) for row in projected_models
            ),
        }

    def write(self, record):
        if self.raw_capture:
            self._evidence("log", **record.model_dump(mode="json"))

    def _model(self, session_id, request, **fields):
        """Optional timing projection supplied by the host."""

    async def export_evidence(self, session_id, run_ids):
        return await self.snapshot(session_id, run_ids)

"""External observation evidence capture and query, independent of business storage.

Phoenix REST and Jaeger Query v3 are read through the selected observation backend.
Only the host supplies the authorized Session and Run allowlist.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json
import traceback
from urllib.parse import quote, urlsplit
import httpx
from sagents.v2.runtime.observability.raw import RawEvidencePipeline, reconstruct
from sagents.v2.runtime.observability.query import query_budget, request as query_request
from sagents.v2.runtime.observability.plugins.external.query import performance_spans
from sagents.v2.contracts.common import utc_now
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

class ExternalEvidenceSink:
    """Trace-backed diagnostic capability; never reads or writes Session storage."""

    plugin_id = "sage.observability.external"
    name = "External observation evidence"
    description = "Diagnostic capture and authorized evidence queries over external trace backends."

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
        raw_max_bytes=16 * 1024 * 1024,
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
        self.max_response_bytes = 32 * 1024 * 1024
        self._raw_pipeline = RawEvidencePipeline(max_bytes=raw_max_bytes)

    @property
    def raw_capture(self):
        return (
            self.backend == "phoenix"
            and getattr(self.trace_sink, "content_mode", None) == "raw"
        )

    def _evidence(self, kind, *, session_id, run_id, _trace_context=None, _target_sink=None, _payload=None, **payload):
        if not self.raw_capture or self.closed or not session_id or not run_id:
            return False
        try:
            active = _trace_context or current_trace_context()
            target = _target_sink or current_trace_sink() or self.trace_sink
            trace_id = active[0] if active else hashlib.sha256(
                f"diagnostic:{self.project}:{self.service}:{self.environment}:{run_id}".encode()).hexdigest()[:32]
            accepted = self._raw_pipeline.submit(target, trace_id, active[1] if active else None,
                                                 session_id, run_id, kind, _payload if _payload is not None else payload, utc_now())
            if not accepted:
                self.capture_failures += 1
            self._raw_record_admitted(kind, session_id, run_id, accepted)
            return accepted
        except Exception:
            self.capture_failures += 1
            return False

    def _raw_record_admitted(self, kind, session_id, run_id, accepted):
        """Optional host projection; only counts, never raw content."""

    def record_model_stream_chunk(self, *, session_id, request, field, sequence, event, trace_context=None):
        return self._evidence("stream_" + field, session_id=session_id, run_id=request.run_id,
                              request_id=request.request_id, sequence=sequence, event=event,
                              _trace_context=trace_context)

    def raw_statistics(self):
        return self._raw_pipeline.statistics()

    async def flush_raw(self):
        return await asyncio.to_thread(self._raw_pipeline.flush)

    async def begin_model_request(self, *, session_id, request, **kwargs):
        self._evidence(
            "request",
            session_id=session_id,
            run_id=request.run_id,
            request_id=request.request_id,
            request=kwargs.get("wire_request")
            if kwargs.get("wire_request") is not None
            else request,
            normalized_request=request,
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
            response=response,
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

    async def record_model_stream(self, *, session_id, request, evidence, trace_context=None):
        self._evidence(
            "stream",
            session_id=session_id,
            run_id=request.run_id,
            request_id=request.request_id,
            stream=evidence,
            _trace_context=trace_context,
        )

    async def close(self):
        self.closed = True
        if not await asyncio.to_thread(self._raw_pipeline.close):
            self.capture_failures += 1

    async def _request(self, client, path, params):
        content, _ = await query_request(self, client, path, params)
        return content.decode()

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

    async def _query(self, client, *, start, end, session_id=None, run_id=None, agent_id=""):
        async with query_budget():
            if self.backend == "phoenix" and session_id is None and run_id is None:
                return await performance_spans(self, client, start=start, end=end, agent_id=agent_id)
            return await self._query_segments(client, start=start, end=end, session_id=session_id, run_id=run_id)

    async def _query_segments(self, client, *, start, end, session_id=None, run_id=None):
        # Agent execution can begin after the selected SDK-entry interval ends.
        # Discover completed Agent spans through now; timing_report applies the
        # exact original entry-time cohort from their performance attributes.
        discovery_end = max(end, utc_now().timestamp()) if session_id is None and run_id is None else end
        dates = {
            "start_time": datetime.fromtimestamp(start, timezone.utc).isoformat(),
            "end_time": datetime.fromtimestamp(discovery_end, timezone.utc).isoformat(),
        }
        if self.backend == "phoenix":
            # Every native and chunk span carries its exact Session/Run scope.
            # Reading by scope already includes every resumed execution trace;
            # fetching those traces again doubles full-content transfer.
            filters = []
            if session_id is not None:
                filters.append(("attribute", f"session_id:{json.dumps(session_id)}"))
            if run_id is not None:
                filters.append(("attribute", f"run_id:{json.dumps(run_id)}"))
            filters.append(("attribute", f"deployment.environment.name:{json.dumps(self.environment)}"))
            return await self._phoenix(client, [*dates.items(), *filters])
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
            identities = sorted({s["attributes"]["run_id"] for s in rows if s["name"] == SPAN_NAME})
            for offset in range(0, len(identities), 4):
                batches = await asyncio.gather(*(self._query(client, start=0, end=utc_now().timestamp(), run_id=identity)
                                                for identity in identities[offset:offset + 4]))
                for batch, cut in batches:
                    complete.extend(batch)
                    truncated |= cut
                    if len(complete) >= self.max_spans:
                        return complete[:self.max_spans], True
            return complete, truncated
        return rows, truncated

    async def snapshot(self, session_id, run_ids):
        raw_flushed = await self.flush_raw()
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
        restored, gaps = await asyncio.to_thread(reconstruct, spans)
        records = [(timestamp(at), attrs) for at, attrs in restored]
        stream_parts = {}
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
                    identity, dict(session_id=session_id, run_id=attrs["run_id"], request_id=payload["request_id"])
                )
                kind = attrs["sage.diagnostic.kind"]
                if kind in {"stream_wire", "stream_normalized"}:
                    stream_parts.setdefault(identity, {}).setdefault(kind, {})[payload["sequence"]] = payload["event"]
                    continue
                row.update(payload)
                observed_at = datetime.fromtimestamp(observed, timezone.utc).isoformat()
                if kind == "request":
                    row.update(status="started", started_at=observed_at)
                elif kind in {"response", "failure"}:
                    row.update(
                        status="completed" if kind == "response" else "failed",
                        completed_at=observed_at,
                    )
        for span in spans:
            attrs = span.get("attributes", {})
            if span.get("name") != "model.request" or not attrs.get("sage.diagnostic.stream_finalized"):
                continue
            identity = attrs["run_id"], attrs["request_id"]
            row = models.setdefault(identity, dict(session_id=session_id, run_id=identity[0], request_id=identity[1]))
            stream = row.setdefault("stream", {})
            stream.setdefault("chunk_format", "chunks/v1")
            for field in ("wire_event_count", "normalized_event_count", "dropped_wire_events", "dropped_normalized_events"):
                stream.setdefault(field, attrs.get("sage.diagnostic." + field, 0))
        for identity, row in models.items():
            if "stream" in row or identity in stream_parts:
                stream = row.setdefault("stream", {})
                parts = stream_parts.get(identity, {})
                if "chunk_format" in stream or parts:
                    for kind, field, count, dropped in (
                        ("stream_wire", "wire_events", "wire_event_count", "dropped_wire_events"),
                        ("stream_normalized", "normalized_events", "normalized_event_count", "dropped_normalized_events"),
                    ):
                        values = parts.get(kind, {})
                        stream[field] = [values[seq] for seq in sorted(values)]
                        missing = max(0, stream.get(count, len(values)) - len(values))
                        stream[dropped] = max(stream.get(dropped, 0), missing)
                    stream["complete"] = ("chunk_format" in stream and not stream.get("dropped_wire_events")
                                          and not stream.get("dropped_normalized_events"))
                    stream["wire_capture_available"] = bool(stream.get("wire_events"))
                    row["truncated"] = not stream["complete"]
        for gap in gaps:
            if gap["kind"] == "log":
                continue
            identity = gap["run_id"], gap["request_id"]
            row = models.setdefault(identity, dict(session_id=session_id, run_id=gap["run_id"], request_id=gap["request_id"]))
            row["truncated"] = True
            row.setdefault("evidence_gaps", []).append(gap)
            row.setdefault("stream", {})["complete"] = False
        projected_models = model_evidence(spans, models.values())
        if self.raw_capture or any(s["attributes"].get("sage.diagnostic.format") == "chunks/v1" for s in spans):
            for row in projected_models:
                fields = row.get("field_sources", {})
                complete = bool(fields.get("request") == "diagnostic_events" and
                                (fields.get("response") == "diagnostic_events" or fields.get("error") == "diagnostic_events") and
                                row.get("stream", {}).get("complete") and not row.get("evidence_gaps"))
                row["raw_capture_complete"] = complete
                row["truncated"] = bool(row.get("truncated") or not complete)
        log_counts = [s["attributes"]["sage.diagnostic.log_count"] for s in spans
                      if s.get("name") == "agent.run" and "sage.diagnostic.log_count" in s["attributes"]]
        expected_logs = sum(log_counts)
        dropped_logs = max(sum(gap["kind"] == "log" for gap in gaps), expected_logs - len(logs), 0)
        raw_statistics = self.raw_statistics()
        transport_statistics = getattr(self.trace_sink, 'statistics', None)
        export_statistics = transport_statistics() if callable(transport_statistics) else {}
        pending_writes = (not raw_flushed or raw_statistics['retained_bytes'] > 0
                          or export_statistics.get('retained_bytes', 0) > 0)
        logs_complete = bool(log_counts and expected_logs == len(logs) and not dropped_logs and not pending_writes)
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
            "evidence_gaps": gaps,
            "dropped_logs": dropped_logs,
            "logs_complete": logs_complete if self.raw_capture or log_counts else None,
            "expected_log_records": expected_logs if log_counts else None,
            "capture_failures_since_start": self.capture_failures,
            "raw_capture_statistics": raw_statistics,
            "trace_export_statistics": export_statistics,
            "pending_writes": pending_writes,
            "raw_flush_completed": raw_flushed,
            "raw_model_streams_available": any(
                row.get("stream", {}).get("wire_capture_available", False) for row in projected_models
            ),
        }

    def write(self, record):
        if self.raw_capture:
            self._evidence("log", session_id=record.session_id, run_id=record.run_id, _payload=record)

    def _model(self, session_id, request, **fields):
        """Optional timing projection supplied by the host."""

    async def export_evidence(self, session_id, run_ids):
        return await self.snapshot(session_id, run_ids)

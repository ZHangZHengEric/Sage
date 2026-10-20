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
import httpx
from sagents.v2.contracts.common import utc_now
from sagents.v2.runtime.observability.contracts import TraceSpan
from sagents.v2.runtime.observability.plugins.diagnostic_noop import NoopDiagnosticSink
from sagents.v2.runtime.observability.traces import current_trace_context
from sagents.v2.runtime.observability.tool_evidence import tool_evidence

SPAN_NAME = "sage.performance"

def timestamp(value):
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value.timestamp()

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
            span = TraceSpan(
                trace_id=active[0]
                if active
                else hashlib.sha256(
                    f"performance:{self.service}:{self.environment}:{run_id}".encode()
                ).hexdigest()[:32],
                parent_span_id=active[1] if active else None,
                span_id=uuid4().hex[:16],
                name="sage.diagnostic",
                start_time=now,
                end_time=now,
                session_id=session_id,
                run_id=run_id,
                request_id=payload.get("request_id"),
                attributes={
                    "sage.diagnostic.kind": kind,
                    "sage.diagnostic.data": json.dumps(
                        payload, ensure_ascii=False, default=str
                    ),
                },
            )
            self.trace_sink.start_span(span)
            self.trace_sink.end_span(span)
        except Exception:
            self.capture_failures += 1

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

    async def close(self):
        self.closed = True  # The application owns and flushes the trace exporter.

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

    async def _query(self, client, *, start, end, session_id=None):
        dates = {
            "start_time": datetime.fromtimestamp(start, timezone.utc).isoformat(),
            "end_time": datetime.fromtimestamp(end, timezone.utc).isoformat(),
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
                params.append(("name", SPAN_NAME))
                params.append(
                    (
                        "attribute",
                        "sage.performance.event:server.run.performance.accepted",
                    )
                )
            rows, truncated = await self._phoenix(client, params)
            # Time bounds select cohorts; fetch the whole timeline, including
            # completions/resumptions after the selected range's upper bound.
            ids = sorted({s["context"]["trace_id"] for s in rows})
            complete = []
            for offset in range(0, len(ids), 100):
                batch, cut = await self._phoenix(
                    client, [("trace_id", t) for t in ids[offset : offset + 100]]
                )
                complete.extend(batch)
                truncated |= cut
                if len(complete) >= self.max_spans:
                    return complete[: self.max_spans], True
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
                    "sage.performance.event": "server.run.performance.accepted",
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
                                "otlp": span,
                                "resource": resource.get("resource", {}),
                                "attributes": {
                                    a["key"]: next(iter(a["value"].values()))
                                    for a in span.get("attributes", [])
                                },
                            }
                        )
                        if len(rows) >= self.max_spans:
                            return rows, True
        return rows, len(traces) >= 10001

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
        diagnostic_spans = [s for s in spans if s["name"] == "sage.diagnostic"]
        for span in sorted(diagnostic_spans, key=lambda s: timestamp(s["start_time"])):
            attrs = span["attributes"]
            if span["name"] != "sage.diagnostic" or "sage.diagnostic.data" not in attrs:
                continue
            payload = json.loads(attrs["sage.diagnostic.data"])
            if attrs["sage.diagnostic.kind"] == "log":
                logs.append(
                    dict(
                        payload,
                        session_id=span["attributes"]["session_id"],
                        run_id=span["attributes"]["run_id"],
                    )
                )
            else:
                identity = (attrs["run_id"], payload["request_id"])
                row = models.setdefault(
                    identity, dict(session_id=session_id, run_id=attrs["run_id"])
                )
                row.update(payload)
                kind = attrs["sage.diagnostic.kind"]
                observed_at = datetime.fromtimestamp(timestamp(span["start_time"]), timezone.utc).isoformat()
                if kind == "request":
                    row.update(status="started", started_at=observed_at)
                elif kind in {"response", "failure"}:
                    row.update(
                        status="completed" if kind == "response" else "failed",
                        completed_at=observed_at,
                    )
        return {
            **tool_evidence(spans, logs),
            "models": list(models.values()),
            "logs": logs,
            "traces": spans,
            "source": self.backend,
            "unavailable": False,
            "truncated": truncated,
            "raw_model_streams_available": any(
                "stream" in row for row in models.values()
            ),
        }

    def write(self, record):
        if self.raw_capture:
            self._evidence("log", **record.model_dump(mode="json"))

    def _model(self, session_id, request, **fields):
        """Optional timing projection supplied by the host."""

    async def export_evidence(self, session_id, run_ids):
        return await self.snapshot(session_id, run_ids)

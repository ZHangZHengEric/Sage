"""External observation evidence capture and query, independent of business storage.

Phoenix REST and Jaeger Query v3 are read through the selected observation backend.
Only the host supplies the authorized Session and Run allowlist.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime, timezone
import hashlib
import json
import traceback
from urllib.parse import quote, urlsplit
import httpx
from sagents.v2.runtime.observability.evidence.raw import (
    RawEvidencePipeline,
    reconstruct,
)
from sagents.v2.runtime.observability.plugins._shared.query import (
    query_budget,
    request as query_request,
)
from sagents.v2.runtime.observability.plugins.external.query import performance_spans
from sagents.v2.contracts.common import utc_now
from sagents.v2.runtime.observability.traces import (
    current_trace_context,
    current_trace_sink,
)
from sagents.v2.runtime.observability.evidence.assembly import assemble_evidence
from sagents.v2.runtime.observability.contracts import TraceSink

SPAN_NAME = "agent.run"
_STATUS_CODES: dict[int | None, str] = {1: "OK", 2: "ERROR"}


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
        capture_mode="redacted",
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
        self.trace_sink: TraceSink | None = None
        self.capture_sink: TraceSink | None = None
        self.capture_mode = capture_mode
        self.closed = False
        self.capture_failures = 0
        self.max_spans = 100000
        self.max_response_bytes = 32 * 1024 * 1024
        self._raw_pipeline = RawEvidencePipeline(max_bytes=raw_max_bytes)

    @property
    def raw_capture(self):
        return self.capture_mode == "raw" and self.backend in {"phoenix", "jaeger"}

    def _evidence(
        self,
        kind,
        *,
        session_id,
        run_id,
        _trace_context=None,
        _target_sink=None,
        _payload=None,
        **payload,
    ):
        if not self.raw_capture or self.closed or not session_id or not run_id:
            return False
        try:
            active = _trace_context or current_trace_context()
            target = (
                self.capture_sink
                or _target_sink
                or current_trace_sink()
                or self.trace_sink
            )
            trace_id = (
                active[0]
                if active
                else hashlib.sha256(
                    f"diagnostic:{self.project}:{self.service}:{self.environment}:{run_id}".encode()
                ).hexdigest()[:32]
            )
            accepted = self._raw_pipeline.submit(
                target,
                trace_id,
                active[1] if active else None,
                session_id,
                run_id,
                kind,
                _payload if _payload is not None else payload,
                utc_now(),
            )
            if not accepted:
                self.capture_failures += 1
            self._raw_record_admitted(kind, session_id, run_id, accepted)
            return accepted
        except Exception:
            self.capture_failures += 1
            return False

    def _raw_record_admitted(self, kind, session_id, run_id, accepted):
        """Optional host projection; only counts, never raw content."""

    def record_model_stream_chunk(
        self, *, session_id, request, field, sequence, event, trace_context=None
    ):
        return self._evidence(
            "stream_" + field,
            session_id=session_id,
            run_id=request.run_id,
            request_id=request.request_id,
            sequence=sequence,
            event=event,
            _trace_context=trace_context,
        )

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
            request_format="provider_wire"
            if kwargs.get("wire_request") is not None
            else "normalized",
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

    async def record_model_stream(
        self, *, session_id, request, evidence, trace_context=None
    ):
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

    async def _query(
        self, client, *, start, end, session_id=None, run_id=None, agent_id=""
    ):
        async with query_budget():
            if self.backend == "phoenix" and session_id is None and run_id is None:
                return await performance_spans(
                    self, client, start=start, end=end, agent_id=agent_id
                )
            return await self._query_segments(
                client, start=start, end=end, session_id=session_id, run_id=run_id
            )

    async def _query_segments(
        self, client, *, start, end, session_id=None, run_id=None
    ):
        # Agent execution can begin after the selected SDK-entry interval ends.
        # Discover completed Agent spans through now; timing_report applies the
        # exact original entry-time cohort from their performance attributes.
        discovery_end = (
            max(end, utc_now().timestamp())
            if session_id is None and run_id is None
            else end
        )
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
            filters.append(
                (
                    "attribute",
                    f"deployment.environment.name:{json.dumps(self.environment)}",
                )
            )
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
                                "end_time": int(span["endTimeUnixNano"]) / 1e9
                                if span.get("endTimeUnixNano")
                                else None,
                                "status_code": _STATUS_CODES.get(
                                    (span.get("status") or {}).get("code"), "UNSET"
                                ),
                                "status_message": (span.get("status") or {}).get(
                                    "message"
                                ),
                                "otlp": span,
                                "events": [
                                    {
                                        "name": e["name"],
                                        "timestamp": int(e["timeUnixNano"]) / 1e9,
                                        "attributes": {
                                            a["key"]: _otlp_value(a["value"])
                                            for a in e.get("attributes", [])
                                        },
                                    }
                                    for e in span.get("events", [])
                                ],
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
            identities = sorted(
                {s["attributes"]["run_id"] for s in rows if s["name"] == SPAN_NAME}
            )
            for offset in range(0, len(identities), 4):
                batches = await asyncio.gather(
                    *(
                        self._query(
                            client, start=0, end=utc_now().timestamp(), run_id=identity
                        )
                        for identity in identities[offset : offset + 4]
                    )
                )
                for batch, cut in batches:
                    complete.extend(batch)
                    truncated |= cut
                    if len(complete) >= self.max_spans:
                        return complete[: self.max_spans], True
            return complete, truncated
        return rows, truncated

    async def snapshot(self, session_id, run_ids):
        raw_flushed = await self.flush_raw()
        async with httpx.AsyncClient() as client:
            spans, truncated = await self._query(
                client,
                start=0,
                end=utc_now().timestamp(),
                session_id=session_id,
            )
        # Filter before reconstruction; foreign records must never be decoded.
        spans = [
            span
            for span in spans
            if span["attributes"].get("session_id") == session_id
            and span["attributes"].get("run_id") in run_ids
        ]
        restored, gaps = await asyncio.to_thread(reconstruct, spans)
        evidence = assemble_evidence(
            spans,
            restored,
            gaps,
            session_id=session_id,
            run_ids=run_ids,
            raw_capture=self.raw_capture,
        )
        raw_statistics = self.raw_statistics()
        transport_statistics = getattr(self.trace_sink, "statistics", None)
        export_statistics = (
            transport_statistics() if callable(transport_statistics) else {}
        )
        if not isinstance(export_statistics, Mapping):
            raise ValueError("trace exporter returned invalid statistics")
        pending_writes = (
            not raw_flushed
            or raw_statistics["retained_bytes"] > 0
            or export_statistics.get("retained_bytes", 0) > 0
        )
        if pending_writes and evidence["logs_complete"] is not None:
            evidence["logs_complete"] = False
        return {
            **evidence,
            "source": self.backend,
            "unavailable": False,
            "truncated": truncated,
            "capture_failures_since_start": self.capture_failures,
            "raw_capture_statistics": raw_statistics,
            "trace_export_statistics": export_statistics,
            "pending_writes": pending_writes,
            "raw_flush_completed": raw_flushed,
        }

    def write(self, record):
        if self.raw_capture:
            self._evidence(
                "log",
                session_id=record.session_id,
                run_id=record.run_id,
                _payload=record,
            )

    def _model(self, session_id, request, **fields):
        """Optional timing projection supplied by the host."""

    async def export_evidence(self, session_id, run_ids):
        return await self.snapshot(session_id, run_ids)
